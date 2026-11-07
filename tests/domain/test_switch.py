from datetime import timedelta
from unittest import mock

import pytest

from app.domain import attempts, authoring, settings, tokens
from app.domain.models import Attempt, QuizRevision
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    OPTION_B,
    add_question,
    definition,
    make_quiz,
    open_quiz_run,
)

pytestmark = pytest.mark.django_db
NOTIFY = authoring.Decision.NOTIFY_SWITCH
FINISH = authoring.Decision.LET_FINISH
STAY = authoring.Decision.STAY


def question_ids(run):
    run.refresh_from_db()
    return [q["id"] for q in run.current_revision.snapshot_json["questions"]]


def publish(run, decision=NOTIFY, change=0, correct=OPTION_B):
    """Changes the `change`-th question of the current revision."""
    add_question(run.quiz, correct, question_id=question_ids(run)[change])
    revision = authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=decision)
    run.refresh_from_db()
    return revision


def code_of(error):
    return error.value.code


@pytest.fixture
def run():
    return open_quiz_run(questions=2)


@pytest.fixture
def started(run):
    return attempts.start(run)


def test_switch_creates_attempt_on_current_revision(run, started):
    second = publish(run)
    result = attempts.switch(started.attempt.id, started.token, {})
    assert result.started.attempt.revision_id == second.id
    assert result.started.attempt.id != started.attempt.id
    assert tokens.verify(result.started.token).revision_id == second.id


def test_old_attempt_is_switched_and_cannot_be_submitted(run, started):
    publish(run)
    result = attempts.switch(started.attempt.id, started.token, {})
    old = Attempt.objects.get(pk=started.attempt.id)
    assert old.status == Attempt.Status.SWITCHED
    assert old.replaced_by_id == result.started.attempt.id
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, started.token, {}, "key-00000001")
    assert code_of(error) == "attempt_switched"


def test_new_attempt_inherits_start_and_expiry(run, started):
    publish(run)
    result = attempts.switch(started.attempt.id, started.token, {})
    new = Attempt.objects.get(pk=result.started.attempt.id)
    assert new.started_at == started.attempt.started_at
    assert result.started.attempt.started_at == started.attempt.started_at
    claims = tokens.verify(result.started.token)
    assert claims.started_at == started.attempt.started_at
    assert claims.expires_at == started.attempt.started_at + attempts.ATTEMPT_LIFETIME


def test_duration_counts_from_the_original_start(run, started):
    publish(run)
    result = attempts.switch(started.attempt.id, started.token, {})
    later = started.attempt.started_at + timedelta(minutes=5)
    with mock.patch("app.domain.attempts.timezone.now", return_value=later):
        attempts.submit(result.started.attempt.id, result.started.token, {}, "key-00000001")
    assert Attempt.objects.get(pk=result.started.attempt.id).duration_ms == 300_000


def test_answer_to_unchanged_question_is_kept_and_changed_one_dropped(run, started):
    first, second = question_ids(run)
    publish(run, change=0)
    answers = {first: {"options": [OPTION_A]}, second: {"options": [OPTION_B]}}
    result = attempts.switch(started.attempt.id, started.token, answers)
    assert result.answers == {second: {"options": [OPTION_B]}}
    assert result.changed == {first}


def test_answer_kept_when_only_points_differ(run, started):
    first, second = question_ids(run)
    draft = authoring.get_draft(run.quiz)
    draft.snapshot_json["questions"][1]["settings"]["points"] = 5
    draft.save()
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=NOTIFY)
    result = attempts.switch(started.attempt.id, started.token, {second: {"options": [OPTION_B]}})
    assert result.answers == {second: {"options": [OPTION_B]}}
    assert result.changed == set()


def test_answer_failing_new_validation_is_dropped(run, started):
    first, second = question_ids(run)
    publish(run, change=0)
    result = attempts.switch(started.attempt.id, started.token, {second: {"options": ["garbage"]}})
    assert result.answers == {}


def test_new_and_removed_questions(run, started):
    first, second = question_ids(run)
    authoring.delete_question(run.quiz, first)
    new = add_question(run.quiz)
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=NOTIFY)
    answers = {first: {"options": [OPTION_A]}, second: {"options": [OPTION_A]}}
    result = attempts.switch(started.attempt.id, started.token, answers)
    assert result.answers == {second: {"options": [OPTION_A]}}
    assert new not in result.changed and first not in result.changed


def test_double_request_creates_one_attempt(run, started):
    publish(run)
    first = attempts.switch(started.attempt.id, started.token, {})
    second = attempts.switch(started.attempt.id, started.token, {})
    assert first.started.attempt.id == second.started.attempt.id
    assert first.started.submission_key != second.started.submission_key
    assert Attempt.objects.count() == 2


def test_chain_is_followed_to_its_end(run, started):
    publish(run)
    middle = attempts.switch(started.attempt.id, started.token, {})
    third = publish(run, correct=OPTION_A)
    end = attempts.switch(middle.started.attempt.id, middle.started.token, {})
    assert end.started.attempt.revision_id == third.id
    again = attempts.switch(started.attempt.id, started.token, {})
    assert again.started.attempt.id == end.started.attempt.id


def test_chain_ending_in_submitted_is_already_submitted(run, started):
    publish(run)
    middle = attempts.switch(started.attempt.id, started.token, {})
    attempts.submit(middle.started.attempt.id, middle.started.token, {}, "key-00000001")
    with pytest.raises(attempts.AttemptError) as error:
        attempts.switch(started.attempt.id, started.token, {})
    assert code_of(error) == "already_submitted"


def test_invalid_token_is_refused(run, started):
    publish(run)
    with pytest.raises(attempts.AttemptError) as error:
        attempts.switch(started.attempt.id, "nope", {})
    assert code_of(error) == "invalid_token"
    assert Attempt.objects.get(pk=started.attempt.id).status == Attempt.Status.IN_PROGRESS


def test_token_of_other_attempt_is_refused(run, started):
    other = attempts.start(run)
    publish(run)
    with pytest.raises(attempts.AttemptError) as error:
        attempts.switch(started.attempt.id, other.token, {})
    assert code_of(error) == "invalid_token"


def test_closed_round_is_refused(run, started):
    publish(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    with pytest.raises(attempts.AttemptError) as error:
        attempts.switch(started.attempt.id, started.token, {})
    assert code_of(error) == "run_closed"


def test_expired_attempt_is_refused(run, started):
    publish(run)
    later = started.attempt.started_at + attempts.ATTEMPT_LIFETIME + timedelta(seconds=2)
    with mock.patch("app.domain.attempts.timezone.now", return_value=later):
        with pytest.raises(attempts.AttemptError) as error:
            attempts.switch(started.attempt.id, started.token, {})
    assert code_of(error) == "attempt_expired"


def test_same_revision_changes_nothing(run, started):
    first, second = question_ids(run)
    result = attempts.switch(started.attempt.id, started.token, {second: {"options": [OPTION_A]}})
    assert result.started.attempt.id == started.attempt.id
    assert result.answers == {second: {"options": [OPTION_A]}}
    assert result.changed == set()
    assert Attempt.objects.count() == 1


def test_switched_attempt_counts_in_no_result(run, started):
    publish(run)
    attempts.switch(started.attempt.id, started.token, {})
    old = Attempt.objects.get(pk=started.attempt.id)
    assert old.score is None and old.submitted_at is None


def test_score_comes_from_the_new_revision(run, started):
    first, second = question_ids(run)
    publish(run, change=0, correct=OPTION_B)
    result = attempts.switch(started.attempt.id, started.token, {})
    answers = {first: {"options": [OPTION_B]}, second: {"options": [OPTION_A]}}
    scored = attempts.submit(
        result.started.attempt.id, result.started.token, answers, "key-00000001"
    )
    assert scored.earned_points == 2


def test_revision_of_old_attempt_stays_unchanged(run, started):
    old = started.attempt.revision
    publish(run)
    attempts.switch(started.attempt.id, started.token, {})
    assert QuizRevision.objects.get(pk=old.pk).checksum == old.checksum


def test_let_finish_does_not_ask(run, started):
    publish(run, FINISH)
    assert not attempts.must_switch(Attempt.objects.get(pk=started.attempt.id))


def test_notify_switch_asks(run, started):
    publish(run)
    assert attempts.must_switch(Attempt.objects.get(pk=started.attempt.id))


def test_attempt_on_current_revision_does_not_ask(run):
    publish(run)
    assert not attempts.must_switch(attempts.start(run).attempt)


def test_last_decision_wins(run, started):
    publish(run)
    publish(run, FINISH, correct=OPTION_A)
    assert not attempts.must_switch(Attempt.objects.get(pk=started.attempt.id))


def test_stay_after_switch_still_asks(run, started):
    publish(run)
    publish(run, STAY, correct=OPTION_A)
    assert attempts.must_switch(Attempt.objects.get(pk=started.attempt.id))


def test_switched_attempt_always_asks(run, started):
    publish(run)
    attempts.switch(started.attempt.id, started.token, {})
    assert attempts.must_switch(Attempt.objects.get(pk=started.attempt.id))


def test_submitted_attempt_does_not_ask(run, started):
    attempts.submit(started.attempt.id, started.token, {}, "key-00000001")
    publish(run)
    assert not attempts.must_switch(Attempt.objects.get(pk=started.attempt.id))


def test_closed_round_does_not_ask(run, started):
    publish(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert not attempts.must_switch(Attempt.objects.get(pk=started.attempt.id))


def test_a_question_with_its_own_shuffle_keeps_its_order_after_a_switch():
    quiz = make_quiz()
    values = {settings.SHUFFLE_OPTIONS: "on"}
    question_id = authoring.save_question(
        quiz, None, "choice", definition(("cs",)), setting_values=values
    )
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    started = attempts.start(run)
    question = attempts.questions_of(started.attempt)[0]
    before = attempts.option_seed_for(started.attempt, question)
    for _ in range(2):  # a second switch keeps it too
        add_question(quiz)
        authoring.publish(quiz, admin_id=ADMIN_ID, decision=NOTIFY)
        started = attempts.switch(started.attempt.id, started.token, {}).started
        same = [q for q in attempts.questions_of(started.attempt) if q["id"] == question_id]
        assert attempts.option_seed_for(started.attempt, same[0]) == before
