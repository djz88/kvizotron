"""What a submission keeps of the answers (AC-59), and who may see it."""

from decimal import Decimal

import pytest

from app.domain import attempts, authoring, settings
from app.domain.models import Attempt, AttemptAnswer
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, add_question, make_quiz
from tests.support.graded import add_graded

pytestmark = pytest.mark.django_db


def running(*, store="score", questions=1, build=None):
    quiz = make_quiz()
    for _ in range(questions):
        add_question(quiz)
    if build:
        build(quiz)
    settings.set_override(settings.DATA_PROFILE, quiz, store, admin_id=ADMIN_ID)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def submit(started, answers):
    return attempts.submit(started.attempt.id, started.token, answers, started.submission_key)


def question_ids(started):
    return [question["id"] for question in attempts.questions_of(started.attempt)]


def test_default_stores_nothing_for_types_without_a_file():
    started = attempts.start(running())
    submit(started, {question_ids(started)[0]: {"options": [OPTION_A]}})
    assert AttemptAnswer.objects.count() == 0


def test_default_value_is_score():
    assert settings.resolve(settings.DATA_PROFILE) == "score"
    assert settings.resolve(settings.ANSWERS_VISIBILITY) == "admins"
    assert settings.resolve(settings.GRADING_VIEW) == "by_question"


def test_store_all_stores_each_answered_question_with_its_points():
    started = attempts.start(running(store="answers", questions=2))
    first, second = question_ids(started)
    submit(started, {first: {"options": [OPTION_A]}, second: {"options": [OPTION_B]}})
    rows = {row.question_id: row for row in AttemptAnswer.objects.all()}
    assert rows[first].answer_json == {"options": [OPTION_A]}
    assert rows[first].auto_points == 1 and rows[second].auto_points == 0
    assert rows[first].manual_max == 0 and rows[first].manual_points is None


@pytest.mark.parametrize("answer", [{}, {"options": []}])
def test_blank_answers_are_not_stored(answer):
    started = attempts.start(running(store="answers"))
    submit(started, {question_ids(started)[0]: answer})
    assert AttemptAnswer.objects.count() == 0


def test_setting_is_frozen_at_start():
    run = running(store="answers")
    started = attempts.start(run)
    settings.set_override(settings.DATA_PROFILE, run.quiz, "score", admin_id=ADMIN_ID)
    submit(started, {question_ids(started)[0]: {"options": [OPTION_A]}})
    assert AttemptAnswer.objects.count() == 1


def test_attempt_without_the_frozen_value_counts_as_images():
    started = attempts.start(running())
    Attempt.objects.filter(pk=started.attempt.id).update(settings_json=None, selection_json=None)
    submit(started, {question_ids(started)[0]: {"options": [OPTION_A]}})
    assert AttemptAnswer.objects.count() == 0


def test_replaced_attempt_keeps_no_rows():
    run = running(store="answers")
    started = attempts.start(run)
    question = question_ids(started)[0]
    authoring.save_question(
        run.quiz,
        None,
        "choice",
        {
            "prompt": {"cs": "Nová"},
            "options": [
                {"id": OPTION_A, "text": {"cs": "A"}},
                {"id": OPTION_B, "text": {"cs": "B"}},
            ],
            "correct": [OPTION_A],
        },
    )
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    moved = attempts.switch(started.attempt.id, started.token, {question: {"options": [OPTION_A]}})
    assert AttemptAnswer.objects.count() == 0
    submit(moved.started, {question: {"options": [OPTION_A]}})
    rows = AttemptAnswer.objects.all()
    assert [row.attempt_id for row in rows] == [moved.started.attempt.id]


def test_image_is_stored_under_images_with_its_asset(graded_type):
    run = running(questions=0, build=add_graded)
    started = attempts.start(run)
    question = question_ids(started)[0]
    submit(started, {question: {"image": "a" * 32}})
    row = AttemptAnswer.objects.get()
    assert row.asset_id == "a" * 32
    assert (row.auto_points, row.manual_max, row.manual_points) == (2, 8, None)


def test_no_image_stores_nothing_and_needs_no_grading(graded_type):
    run = running(questions=0, build=add_graded)
    started = attempts.start(run)
    result = submit(started, {question_ids(started)[0]: {}})
    assert AttemptAnswer.objects.count() == 0
    assert result.pending is False and result.earned_points == Decimal(0)


def test_visibility_conflict_behaves_as_admins():
    quiz = make_quiz()
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "public", admin_id=ADMIN_ID)
    assert settings.answers_visibility(quiz) == "admins"
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    assert settings.answers_visibility(quiz) == "public"


@pytest.mark.parametrize(
    "store,visibility,conflict",
    [
        ("score", "admins", False),
        ("score", "participant", True),
        ("score", "public", True),
        ("none", "public", True),
        ("answers", "public", False),
        ("detailed", "participant", False),
    ],
)
def test_is_visibility_conflict(store, visibility, conflict):
    assert settings.is_visibility_conflict(store, visibility) is conflict
