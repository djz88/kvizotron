"""The server decides whether a submission is in time (FR-11, AC-07, ADR-0025)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import attempts, authoring, run_links, run_schedule, settings
from app.domain.models import Attempt, QuizRun
from tests.domain.helpers import ADMIN_ID, add_question, open_quiz_run, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 9, 50, tzinfo=UTC)
LIMIT = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
KEY = "k" * 20


@pytest.fixture(autouse=True)
def before_the_end(monkeypatch):
    freeze(monkeypatch, NOW)


def a_run(deadline=None, limit=None):
    return authoring.open_run(
        published_quiz(), admin_id=ADMIN_ID, deadline_at=deadline, limit_sec=limit
    )


def send(started, received_at=None):
    return attempts.submit(started.attempt.id, started.token, {}, KEY, received_at=received_at)


def status_of(started):
    return Attempt.objects.get(pk=started.attempt.id).status


def expired_code(started, received_at):
    with pytest.raises(attempts.AttemptError) as caught:
        send(started, received_at)
    return caught.value.code


def test_submission_in_the_boundary_second_is_accepted():
    started = attempts.start(a_run(deadline=LIMIT))
    send(started, LIMIT + timedelta(milliseconds=900))
    assert status_of(started) == Attempt.Status.SUBMITTED


def test_submission_after_it_is_rejected():
    started = attempts.start(a_run(deadline=LIMIT))
    assert expired_code(started, LIMIT + timedelta(seconds=1)) == "attempt_expired"
    assert status_of(started) == Attempt.Status.IN_PROGRESS


def test_a_limit_ends_the_attempt():
    started = attempts.start(a_run(limit=600))
    send(started, LIMIT + timedelta(milliseconds=900))
    assert status_of(started) == Attempt.Status.SUBMITTED


def test_after_the_limit_it_is_rejected():
    started = attempts.start(a_run(limit=600))
    assert expired_code(started, LIMIT + timedelta(seconds=1)) == "attempt_expired"


def test_the_earlier_of_deadline_and_limit_wins():
    started = attempts.start(a_run(deadline=LIMIT, limit=7200))
    assert attempts.ends_at(started.attempt) == LIMIT
    started = attempts.start(a_run_on_another_quiz(deadline=LIMIT + timedelta(hours=2), limit=600))
    assert attempts.ends_at(started.attempt) == LIMIT


def a_run_on_another_quiz(deadline, limit):
    quiz = published_quiz(slug="druhy")
    return authoring.open_run(quiz, admin_id=ADMIN_ID, deadline_at=deadline, limit_sec=limit)


def test_no_time_applies_without_deadline_and_limit():
    started = attempts.start(a_run())
    assert attempts.ends_at(started.attempt) is None
    send(started, NOW + timedelta(hours=20))
    assert status_of(started) == Attempt.Status.SUBMITTED


def test_a_moved_deadline_applies_to_attempts_in_progress():
    run = a_run(deadline=LIMIT)
    started = attempts.start(run)
    later = LIMIT + timedelta(hours=1)
    run_schedule.set_deadline(run, later, admin_id=ADMIN_ID)
    send(started, LIMIT + timedelta(minutes=30))
    assert status_of(started) == Attempt.Status.SUBMITTED


def test_a_deadline_moved_earlier_applies_too():
    run = a_run(deadline=LIMIT)
    started = attempts.start(run)
    earlier = NOW + timedelta(minutes=2)
    run_schedule.set_deadline(run, earlier, admin_id=ADMIN_ID)
    assert expired_code(started, earlier + timedelta(seconds=1)) == "attempt_expired"


def test_received_in_time_counts_after_another_request_closed_the_run():
    run = a_run(deadline=LIMIT)
    started = attempts.start(run)
    run_schedule.settle(LIMIT + timedelta(seconds=1))
    assert QuizRun.objects.get(pk=run.pk).status == QuizRun.Status.CLOSED
    send(started, LIMIT + timedelta(milliseconds=900))
    assert status_of(started) == Attempt.Status.SUBMITTED


def test_a_manual_close_still_rejects_later_submissions():
    run = a_run()
    started = attempts.start(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert expired_code(started, NOW + timedelta(milliseconds=1)) == "run_closed"


def test_a_submission_received_before_a_manual_close_counts(monkeypatch):
    run = a_run()
    started = attempts.start(run)
    freeze(monkeypatch, NOW + timedelta(minutes=1))
    authoring.close_run(run, admin_id=ADMIN_ID)
    send(started, NOW + timedelta(seconds=30))
    assert status_of(started) == Attempt.Status.SUBMITTED


def test_without_a_deadline_it_works_until_a_manual_close():
    run = a_run()
    started = attempts.start(run)
    send(started, NOW + timedelta(hours=1))
    assert status_of(started) == Attempt.Status.SUBMITTED


def test_start_before_the_plan_is_refused():
    run = run_schedule.plan(
        published_quiz(),
        starts_at=LIMIT,
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
    )
    with pytest.raises(attempts.AttemptError) as caught:
        attempts.start(run)
    assert caught.value.code == "run_not_started"


def test_start_after_the_deadline_is_refused_before_any_settle(monkeypatch):
    run = a_run(deadline=LIMIT)
    freeze(monkeypatch, LIMIT + timedelta(seconds=1))
    with pytest.raises(attempts.AttemptError) as caught:
        attempts.start(run)
    assert caught.value.code == "run_closed"


def test_switching_revision_gains_no_time(monkeypatch):
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, limit_sec=600)
    started = attempts.start(run)
    add_question(quiz, prompt="Nová")
    authoring.publish(quiz, admin_id=ADMIN_ID, decision="notify_switch")
    freeze(monkeypatch, NOW + timedelta(minutes=5))
    switched = attempts.switch(started.attempt.id, started.token, {})
    replacement = switched.started.attempt
    assert replacement.pk != started.attempt.pk
    assert replacement.started_at == NOW
    assert replacement.settings_json["limit_sec"] == 600
    assert attempts.ends_at(Attempt.objects.get(pk=replacement.pk)) == LIMIT
    assert attempts.time_left(replacement) == 300


def test_a_limit_changed_on_the_quiz_later_does_not_touch_an_attempt():
    run = a_run(limit=600)
    started = attempts.start(run)
    settings.set_override(settings.ATTEMPT_LIMIT, run.quiz, "1", admin_id=None)
    assert attempts.ends_at(Attempt.objects.get(pk=started.attempt.pk)) == LIMIT


def test_a_test_link_takes_the_limit_from_the_quiz():
    quiz = published_quiz()
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "10", admin_id=None)
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    started = attempts.start(QuizRun.all_kinds.get(pk=link.run_id))
    assert attempts.ends_at(started.attempt) == LIMIT


def test_time_left_counts_down_and_stops_at_zero(monkeypatch):
    started = attempts.start(a_run(limit=600))
    assert attempts.time_left(started.attempt) == 600
    freeze(monkeypatch, LIMIT + timedelta(seconds=30))
    assert attempts.time_left(started.attempt) == 0


def test_time_left_is_zero_on_an_ended_run():
    run = a_run(limit=600)
    started = attempts.start(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert attempts.remaining(started.attempt.id, started.token) == 0


def test_remaining_is_none_without_time_and_after_submitting():
    started = attempts.start(a_run())
    assert attempts.remaining(started.attempt.id, started.token) is None
    limited = attempts.start(a_run_on_another_quiz(None, 600))
    send(limited)
    assert attempts.remaining(limited.attempt.id, limited.token) is None


def test_time_answers_seconds_remaining_and_nothing_else(client):
    started = attempts.start(a_run(limit=600))
    response = client.post(f"/a/{started.attempt.id}/time", {"attempt_token": started.token})
    assert response.status_code == 200
    assert response.json() == {"remaining": 600}


def test_time_refuses_a_bad_token(client):
    started = attempts.start(a_run(limit=600))
    response = client.post(f"/a/{started.attempt.id}/time", {"attempt_token": "nonsense"})
    assert response.status_code == 403
    assert "remaining" not in response.json()


def test_time_is_post_only(client):
    started = attempts.start(a_run(limit=600))
    assert client.get(f"/a/{started.attempt.id}/time").status_code == 405


def test_the_page_refuses_a_start_before_the_plan(client):
    run = run_schedule.plan(
        published_quiz(), starts_at=LIMIT, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID
    )
    response = client.post(f"/r/{run.id}/start", {"lang": "en"})
    assert response.status_code == 409
    assert "ještě nezačal" in response.content.decode()


def test_the_page_passes_the_receipt_time(client, monkeypatch):
    """Storing a photo happens first, and must not use up the participant's time."""
    started = attempts.start(a_run(limit=600))
    seen = {}
    real = attempts.submit

    def spy(*args, **kwargs):
        seen["received_at"] = kwargs.get("received_at")
        return real(*args, **kwargs)

    monkeypatch.setattr(attempts, "submit", spy)
    client.post(
        f"/a/{started.attempt.id}/submit",
        {"attempt_token": started.token, "submission_key": KEY, "lang": "en"},
    )
    assert seen["received_at"] == NOW


def test_a_run_without_a_limit_has_none():
    assert open_quiz_run().attempt_limit_sec is None
