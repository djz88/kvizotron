"""AC-11, AC-80: an unsubmitted attempt carries on from the token the browser kept."""

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import LOCAL_RESUME
from app.domain import attempts, authoring, settings
from app.domain.models import Attempt
from tests.domain.helpers import ADMIN_ID, add_question, open_quiz_run, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)
KEY = "k" * 20


@pytest.fixture(autouse=True)
def at_nine(monkeypatch):
    freeze(monkeypatch, NOW)
    return monkeypatch


def code_of(call):
    with pytest.raises(attempts.AttemptError) as caught:
        call()
    return caught.value.code


def resume(run, started):
    return attempts.resume_by_token(run, started.attempt.id, started.token)


def test_resume_returns_same_attempt_questions_and_start():
    run = open_quiz_run(questions=2)
    started = attempts.start(run)
    again = resume(run, started)
    assert again.attempt.id == started.attempt.id
    assert attempts.questions_of(again.attempt) == attempts.questions_of(started.attempt)
    assert again.attempt.started_at == started.attempt.started_at
    assert again.token and again.submission_key


def test_resume_needs_no_code_cookie():
    run = open_quiz_run()
    started = attempts.start(run)
    from app.domain import access_codes

    access_codes.set_code(run, "ABCD2345", admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert resume(run, started).attempt.id == started.attempt.id


def test_resume_refused_for_other_run():
    run, other = open_quiz_run(), open_quiz_run("jiny")
    started = attempts.start(run)
    assert code_of(lambda: resume(other, started)) == "not_in_run"


def test_resume_refused_after_submit():
    run = open_quiz_run()
    started = attempts.start(run)
    attempts.submit(started.attempt.id, started.token, {}, KEY)
    assert code_of(lambda: resume(run, started)) == "already_submitted"


def test_resume_refused_after_stateless_submit():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, data={"profile": "none"})
    started = attempts.start(run)
    attempts.submit(started.attempt.id, started.token, {}, KEY)
    assert code_of(lambda: resume(run, started)) == "attempt_gone"


def test_resume_refused_after_limit(at_nine):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, limit_sec=60)
    started = attempts.start(run)
    freeze(at_nine, NOW + timedelta(seconds=120))
    assert code_of(lambda: resume(run, started)) == "attempt_expired"


def test_resume_refused_when_run_closed():
    run = open_quiz_run()
    started = attempts.start(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert code_of(lambda: resume(run, started)) == "run_closed"


def test_resume_refused_when_abandoned():
    run = open_quiz_run()
    started = attempts.start(run)
    Attempt.objects.filter(pk=started.attempt.id).update(status=Attempt.Status.ABANDONED)
    assert code_of(lambda: resume(run, started)) == "attempt_closed"


def test_resume_refused_with_a_bad_token():
    run = open_quiz_run()
    started = attempts.start(run)
    assert code_of(lambda: attempts.resume_by_token(run, started.attempt.id, "x.y")) == (
        "invalid_token"
    )


def test_resume_follows_switch_chain():
    run = open_quiz_run(questions=2)
    started = attempts.start(run)
    first = run.current_revision.snapshot_json["questions"][0]["id"]
    add_question(run.quiz, question_id=first, prompt="Jina")
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    run.refresh_from_db()
    moved = attempts.switch(started.attempt.id, started.token, {}).started
    assert moved.attempt.id != started.attempt.id
    again = resume(run, started)  # the copy holds the token of the first attempt
    assert again.attempt.id == moved.attempt.id


def test_resume_off_refused():
    run = open_quiz_run()
    started = attempts.start(run)
    Attempt.objects.filter(pk=started.attempt.id).update(
        settings_json={**started.attempt.settings_json, "local_resume": "off"}
    )
    assert code_of(lambda: resume(run, started)) == "resume_off"


def test_local_resume_is_frozen_at_start():
    run = open_quiz_run()
    assert attempts.start(run).attempt.settings_json["local_resume"] == "on"
    settings.set_override(LOCAL_RESUME, run.quiz, "off", admin_id=ADMIN_ID)
    started = attempts.start(run)
    assert started.attempt.settings_json["local_resume"] == "off"


def test_copy_expiry_takes_limit_deadline_or_24h():
    day = NOW + timedelta(hours=24)
    plain = attempts.start(open_quiz_run()).attempt
    assert attempts.copy_expiry(plain) == day
    limited = attempts.start(
        authoring.open_run(published_quiz("a"), admin_id=ADMIN_ID, limit_sec=600)
    ).attempt
    assert attempts.copy_expiry(limited) == NOW + timedelta(seconds=600)
    soon = NOW + timedelta(hours=2)
    dated = attempts.start(
        authoring.open_run(published_quiz("b"), admin_id=ADMIN_ID, deadline_at=soon)
    ).attempt
    assert attempts.copy_expiry(dated) == soon
    long = attempts.start(
        authoring.open_run(published_quiz("c"), admin_id=ADMIN_ID, limit_sec=48 * 3600)
    ).attempt
    assert attempts.copy_expiry(long) == day


def test_used_mode_allows_resume_of_same_attempt():
    rules = {"repeat_attempts": "forbid", "unfinished_attempt": "used"}
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules)
    from app.domain import participants

    person = participants.find_or_create(run, "a" * 20)
    started = attempts.start(run, participant=person)
    assert resume(run, started).attempt.id == started.attempt.id
