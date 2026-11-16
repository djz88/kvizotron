from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from app.domain import attempts, authoring, reveal, settings
from app.domain.models import Attempt, QuizRun
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    OPTION_B,
    definition,
    make_quiz,
    published_quiz,
)

pytestmark = pytest.mark.django_db
A, B, C = "aaaa1111", "bbbb2222", "cccc3333"


def question(**fields):
    quiz = make_quiz(locales=("cs",))
    authoring.save_question(quiz, None, "choice", definition(("cs",)), **fields)
    return authoring.editable_questions(quiz)[0]


def of(q, answer, level="verdict"):
    return reveal.of_question(q, answer, level, "cs")


def test_full_points_is_right():
    revealed = of(question(), {"options": [OPTION_A]})
    assert revealed.state == reveal.State.RIGHT
    assert revealed.earned == revealed.maximum == Decimal(1)


def test_part_of_the_points_is_partial_with_points():
    q = question(points=4, scoring="partial")
    q["definition"] = {
        "prompt": {"cs": "O"},
        "options": [{"id": i, "text": {"cs": i}} for i in (A, B, C)],
        "correct": [A, B],
        "allow_multiple": True,
    }
    revealed = of(q, {"options": [A]})
    assert revealed.state == reveal.State.PARTIAL
    assert revealed.earned == Decimal(2)
    assert revealed.maximum == Decimal(4)


def test_zero_answered_is_wrong():
    assert of(question(), {"options": [OPTION_B]}).state == reveal.State.WRONG


def test_nothing_answered_is_unanswered():
    revealed = of(question(), None)
    assert revealed.state == reveal.State.UNANSWERED
    assert revealed.earned == 0
    assert revealed.maximum == 1


def test_pairs_left_on_the_placeholder_are_unanswered():
    assert reveal.is_blank({"pair_a": "", "pair_b": ""})
    assert reveal.is_blank({"options": []})
    assert reveal.is_blank(None)
    assert not reveal.is_blank({"pair_a": "", "pair_b": "x"})
    assert not reveal.is_blank({"options": ["x"]})
    q = question()
    q.update(
        type="matching",
        definition={
            "prompt": {"cs": "S"},
            "mode": "pairs",
            "items": [
                {"id": "a1", "match_id": "b1", "text": {"cs": "A"}, "match": {"cs": "1"}},
                {"id": "a2", "match_id": "b2", "text": {"cs": "B"}, "match": {"cs": "2"}},
            ],
        },
    )
    assert of(q, {"pair_a1": "", "pair_a2": ""}).state == reveal.State.UNANSWERED


def test_verdict_level_shows_no_answers_or_explanation():
    revealed = of(question(explanation={"cs": "Protože"}), {"options": [OPTION_A]})
    assert not revealed.show_answers
    assert revealed.explanation is None


def test_answers_level_shows_answers_only():
    q = question(explanation={"cs": "Protože"})
    revealed = of(q, {"options": [OPTION_A]}, "answers")
    assert revealed.show_answers
    assert revealed.explanation is None


def test_explanations_level_shows_both():
    q = question(explanation={"cs": "Protože"})
    revealed = of(q, {"options": [OPTION_A]}, "explanations")
    assert revealed.show_answers
    assert revealed.explanation == "Protože"


def test_question_without_the_key_has_no_explanation():
    q = question()
    del q["explanation"]
    assert of(q, None, "explanations").explanation is None


def test_publication_keeps_explanations():
    quiz = make_quiz(slug="pub")
    authoring.save_question(
        quiz, None, "choice", definition(("cs",)), explanation={"cs": "Protože"}
    )
    revision = authoring.publish(quiz, admin_id=ADMIN_ID)
    assert revision.snapshot_json["questions"][0]["explanation"] == {"cs": "Protože"}


def after_close_attempt(**run_fields):
    quiz = published_quiz()
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "participant", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_close", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    attempt = Attempt.objects.create(
        run=run, revision=run.current_revision, settings_json={"moment": "after_close"}
    )
    if run_fields:
        QuizRun.objects.filter(pk=run.pk).update(**run_fields)
        attempt = Attempt.objects.select_related("run").get(pk=attempt.pk)
    return attempt


def test_window_is_ten_minutes():
    assert attempts.LATE_UPLOAD_WINDOW == timedelta(minutes=10)


def test_answers_wait_for_the_window_after_close():
    """AC-175: answers show from the close plus the late-upload window."""
    now = timezone.now()
    attempt = after_close_attempt(
        status=QuizRun.Status.CLOSED, closed_at=now - timedelta(minutes=9, seconds=59)
    )
    assert not reveal.is_shown(attempt, now)
    assert reveal.is_shown(attempt, now + timedelta(seconds=1))
    assert reveal.shown_from(attempt.run) == attempt.run.closed_at + attempts.LATE_UPLOAD_WINDOW


def test_an_open_run_shows_nothing_and_knows_its_deadline():
    attempt = after_close_attempt()
    assert not reveal.is_shown(attempt, timezone.now() + timedelta(days=9))
    assert reveal.shown_from(attempt.run) is None
    deadline = timezone.now() + timedelta(hours=1)
    QuizRun.objects.filter(pk=attempt.run_id).update(deadline_at=deadline)
    attempt.run.refresh_from_db()
    assert reveal.shown_from(attempt.run) == deadline + attempts.LATE_UPLOAD_WINDOW


def test_an_archived_run_shows_after_the_window():
    now = timezone.now()
    attempt = after_close_attempt(
        status=QuizRun.Status.ARCHIVED, closed_at=now - timedelta(minutes=11)
    )
    assert reveal.is_shown(attempt, now)


def test_a_test_run_shows_at_once():
    """AC-175: a test run shows the answers at the end, like "at the end"."""
    attempt = after_close_attempt(kind=QuizRun.Kind.TEST)
    assert reveal.is_shown(attempt, timezone.now())


def test_other_moments_are_not_after_close():
    attempt = after_close_attempt(status=QuizRun.Status.CLOSED, closed_at=timezone.now())
    attempt.settings_json = {"moment": "at_end"}
    assert not reveal.is_shown(attempt, timezone.now() + timedelta(days=1))


def test_allowed_moments_are_an_allowlist():
    """AC-175: only listed moments show answers."""
    now = timezone.now()
    attempt = after_close_attempt()
    for moment, expected in (
        ("never", False),
        ("at_end", True),
        ("after_each", True),
        ("after_close", False),
        ("something_new", False),
    ):
        attempt.settings_json = {"moment": moment}
        assert reveal.shows_answers(attempt, now) is expected, moment
