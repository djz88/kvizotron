"""AC-77: an attempt stores exactly what its data profile allows."""

import pytest

from app.domain import attempts, authoring, run_links, settings
from app.domain.models import Attempt, AttemptAnswer
from tests.domain.helpers import ADMIN_ID, OPTION_A, add_question, make_quiz
from tests.support.graded import add_graded

pytestmark = pytest.mark.django_db


def running(profile, *, graded=False):
    quiz = make_quiz()
    add_question(quiz)
    if graded:
        add_graded(quiz)
    settings.set_override(settings.DATA_PROFILE, quiz, profile, admin_id=ADMIN_ID)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def play(started, answers_for):
    ids = [question["id"] for question in attempts.questions_of(started.attempt)]
    answers = answers_for(ids)
    attempts.submit(started.attempt.id, started.token, answers, started.submission_key)
    return Attempt.objects.get(pk=started.attempt.id)


def choice_only(ids):
    return {ids[0]: {"options": [OPTION_A]}}


def test_profile_is_frozen_on_the_attempt_at_start():
    started = attempts.start(running("answers"))
    assert started.attempt.settings_json["profile"] == "answers"
    assert "store_answers" not in started.attempt.settings_json


def test_score_keeps_score_and_time_only():
    attempt = play(attempts.start(running("score")), choice_only)
    assert not AttemptAnswer.objects.exists()
    assert attempt.duration_ms is None
    assert attempt.score == 1 and attempt.submitted_at is not None


def test_score_keeps_answers_needing_a_person(graded_type):
    started = attempts.start(running("score", graded=True))
    photo = {"image": "x"}
    attempt = play(started, lambda ids: {ids[0]: {"options": [OPTION_A]}, ids[1]: photo})
    rows = AttemptAnswer.objects.filter(attempt=attempt)
    assert rows.count() == 1 and rows[0].manual_max > 0
    assert attempt.duration_ms is None


def test_answers_keeps_every_answered_question_without_duration():
    attempt = play(attempts.start(running("answers")), choice_only)
    assert AttemptAnswer.objects.filter(attempt=attempt).count() == 1
    assert attempt.duration_ms is None


def test_detailed_keeps_answers_and_duration():
    attempt = play(attempts.start(running("detailed")), choice_only)
    assert AttemptAnswer.objects.filter(attempt=attempt).count() == 1
    assert attempt.duration_ms is not None


def test_attempt_started_before_upgrade_keeps_its_frozen_store_answers():
    started = attempts.start(running("score"))
    Attempt.objects.filter(pk=started.attempt.id).update(
        settings_json={"store_answers": "all", "navigation": "all_at_once"}
    )
    attempt = play(started, choice_only)
    assert AttemptAnswer.objects.filter(attempt=attempt).count() == 1
    assert attempt.duration_ms is None


def test_test_link_follows_quiz_profile():
    quiz = make_quiz()
    add_question(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    revision = authoring.latest_published(quiz)
    link = run_links.create(quiz, revision, expires_at=None, admin_id=ADMIN_ID)
    settings.set_override(settings.DATA_PROFILE, quiz, "detailed", admin_id=ADMIN_ID)
    attempt = play(attempts.start(link.run), choice_only)
    assert AttemptAnswer.objects.filter(attempt=attempt).count() == 1
    assert attempt.duration_ms is not None
