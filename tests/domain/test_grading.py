"""An attempt waits for a person, and the score follows what they decide (AC-55, AC-56)."""

from decimal import Decimal

import pytest

from app.domain import attempts, authoring, grading, reveal, run_links
from app.domain.models import Attempt, AttemptAnswer
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz
from tests.support.graded import add_graded

pytestmark = pytest.mark.django_db
ASSET = "a" * 32


def running(photos=1, plain=0, **definition):
    quiz = make_quiz()
    for _ in range(plain):
        add_question(quiz)
    for _ in range(photos):
        add_graded(quiz, **definition)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def submitted(run, **extra):
    started = attempts.start(run)
    answers = {
        question["id"]: {"image": ASSET}
        for question in attempts.questions_of(started.attempt)
        if question["type"] == "graded"
    }
    result = attempts.submit(
        started.attempt.id, started.token, answers | extra, started.submission_key
    )
    return started, result


def refreshed(started):
    return Attempt.objects.get(pk=started.attempt.id)


def test_needs_grading_gives_pending_and_automatic_score(graded_type):
    started, result = submitted(running())
    assert result.pending is True
    assert (result.earned_points, result.max_points) == (2, 10)
    attempt = refreshed(started)
    assert attempt.status == Attempt.Status.PENDING_GRADING
    assert attempt.score == 2 and attempt.auto_score == 2 and attempt.submitted_at


def test_no_image_is_submitted_not_pending(graded_type):
    run = running()
    started = attempts.start(run)
    question = attempts.questions_of(started.attempt)[0]["id"]
    attempts.submit(started.attempt.id, started.token, {question: {}}, started.submission_key)
    assert refreshed(started).status == Attempt.Status.SUBMITTED


def test_fully_automatic_share_has_nothing_to_wait_for(graded_type):
    started, result = submitted(running(share=(10, 10)))
    assert result.pending is False and result.earned_points == 10
    assert refreshed(started).status == Attempt.Status.SUBMITTED
    assert grading.waiting(started.attempt.run) == 0


def test_save_manual_recalculates_and_leaves_pending_when_none_waits(graded_type):
    run = running()
    started, _ = submitted(run)
    assert grading.waiting(run) == 1
    grading.save_manual(AttemptAnswer.objects.get(), Decimal(5), admin_id=ADMIN_ID)
    attempt = refreshed(started)
    assert attempt.status == Attempt.Status.SUBMITTED and attempt.score == 7
    assert grading.waiting(run) == 0
    row = AttemptAnswer.objects.get()
    assert row.manual_points == 5 and row.graded_by == ADMIN_ID and row.graded_at


def test_two_photos_stay_pending_until_both_are_graded(graded_type):
    started, _ = submitted(running(photos=2))
    first, second = AttemptAnswer.objects.order_by("question_id")
    grading.save_manual(first, Decimal(1), admin_id=ADMIN_ID)
    assert refreshed(started).status == Attempt.Status.PENDING_GRADING
    grading.save_manual(second, Decimal(1), admin_id=ADMIN_ID)
    assert refreshed(started).status == Attempt.Status.SUBMITTED


def test_automatic_points_of_other_questions_stay(graded_type):
    run = running(plain=1)
    started = attempts.start(run)
    questions = attempts.questions_of(started.attempt)
    plain = next(question for question in questions if question["type"] == "choice")
    photo = next(question for question in questions if question["type"] == "graded")
    answers = {plain["id"]: {"options": ["aaaa1111"]}, photo["id"]: {"image": ASSET}}
    attempts.submit(started.attempt.id, started.token, answers, started.submission_key)
    grading.save_manual(AttemptAnswer.objects.get(), Decimal(8), admin_id=ADMIN_ID)
    assert refreshed(started).score == 11


@pytest.mark.parametrize("points", ["-1", "8.01", "1.23456", "NaN", "Infinity"])
def test_points_outside_zero_to_max_refused(graded_type, points):
    submitted(running())
    with pytest.raises(grading.InvalidPoints):
        grading.save_manual(AttemptAnswer.objects.get(), Decimal(points), admin_id=ADMIN_ID)
    assert AttemptAnswer.objects.get().manual_points is None


def test_row_without_a_manual_part_cannot_be_graded(graded_type):
    submitted(running(share=(10, 10)))
    with pytest.raises(grading.InvalidPoints):
        grading.save_manual(AttemptAnswer.objects.get(), Decimal(0), admin_id=ADMIN_ID)


def test_regrading_after_the_run_ended(graded_type):
    run = running()
    started, _ = submitted(run)
    grading.save_manual(AttemptAnswer.objects.get(), Decimal(5), admin_id=ADMIN_ID)
    authoring.close_run(run, admin_id=ADMIN_ID)
    grading.save_manual(AttemptAnswer.objects.get(), Decimal(3), admin_id=ADMIN_ID)
    assert refreshed(started).score == 5


def test_every_change_is_audited_without_content(graded_type):
    submitted(running())
    row = AttemptAnswer.objects.get()
    grading.save_manual(row, Decimal(5), admin_id=ADMIN_ID)
    grading.set_approved(row, True, admin_id=ADMIN_ID)
    grading.remove_photo(row, admin_id=ADMIN_ID)
    events = AuditEvent.objects.filter(entity_type="attempt_answer")
    assert {event.action for event in events} == {
        "answer.graded",
        "answer.approved",
        "answer.photo_removed",
    }
    assert all(ASSET not in str(event.details_json) for event in events)
    assert all(event.actor_id == ADMIN_ID for event in events)


def test_remove_photo_sets_zero_keeps_automatic_and_returns_asset(graded_type):
    started, _ = submitted(running())
    row = AttemptAnswer.objects.get()
    assert grading.remove_photo(row, admin_id=ADMIN_ID) == ASSET
    row.refresh_from_db()
    assert row.removed and row.asset_id is None and row.manual_points == 0 and not row.approved
    attempt = refreshed(started)
    assert attempt.score == 2 and attempt.status == Attempt.Status.SUBMITTED


def test_remove_photo_twice_returns_nothing(graded_type):
    submitted(running())
    row = AttemptAnswer.objects.get()
    grading.remove_photo(row, admin_id=ADMIN_ID)
    assert grading.remove_photo(AttemptAnswer.objects.get(), admin_id=ADMIN_ID) is None


def test_removed_photo_cannot_be_graded_or_approved(graded_type):
    submitted(running())
    row = AttemptAnswer.objects.get()
    grading.remove_photo(row, admin_id=ADMIN_ID)
    with pytest.raises(grading.InvalidPoints):
        grading.save_manual(row, Decimal(1), admin_id=ADMIN_ID)
    grading.set_approved(row, True, admin_id=ADMIN_ID)
    assert not AttemptAnswer.objects.get().approved


def test_decimal_points_stay_exact(graded_type):
    started, _ = submitted(running(share=(33, 100)))
    row = AttemptAnswer.objects.get()
    assert row.auto_points == Decimal("3.3") and row.manual_max == Decimal("6.7")
    grading.save_manual(row, Decimal("6.7"), admin_id=ADMIN_ID)
    assert refreshed(started).score == 10


def test_test_link_deletes_return_their_assets(graded_type):
    quiz = make_quiz()
    add_graded(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    link = run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id="a")
    submitted(link.run)
    assert run_links.delete_attempts(link, admin_id=ADMIN_ID) == [ASSET]
    assert AttemptAnswer.objects.count() == 0
    submitted(link.run)
    assert run_links.delete(link, admin_id=ADMIN_ID) == [ASSET]
    assert AttemptAnswer.objects.count() == 0


# A pending attempt meeting code that knew only SUBMITTED


def test_resubmit_of_a_pending_attempt_returns_its_result(graded_type):
    started, first = submitted(running())
    again = attempts.submit(started.attempt.id, started.token, {}, started.submission_key)
    assert again == first


def test_resubmit_with_another_key_is_refused(graded_type):
    started, _ = submitted(running())
    with pytest.raises(attempts.AttemptError, match="already_submitted"):
        attempts.submit(started.attempt.id, started.token, {}, "another-key-1234")


def test_switch_of_a_pending_attempt_is_already_submitted(graded_type):
    started, _ = submitted(running())
    with pytest.raises(attempts.AttemptError, match="already_submitted"):
        attempts.switch(started.attempt.id, started.token, {})


def test_reveal_says_it_waits_and_earned_shows_the_automatic_part(graded_type):
    run = running()
    started = attempts.start(run)
    question = attempts.questions_of(started.attempt)[0]
    revealed = reveal.of_question(question, {"image": ASSET}, "answers", "cs")
    assert revealed.state == reveal.State.PENDING
    assert revealed.earned == 2 and revealed.maximum == 10
    empty = reveal.of_question(question, {}, "answers", "cs")
    assert empty.state == reveal.State.UNANSWERED
