"""Moving the deadline of a running run (FR-11, ADR-0048)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import attempts, authoring, clock
from app.domain.models import QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
DEADLINE = NOW + timedelta(hours=2)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def a_run(deadline=DEADLINE, limit=None):
    return authoring.open_run(
        published_quiz(), admin_id=ADMIN_ID, deadline_at=deadline, limit_sec=limit
    )


def url(run):
    return f"/admin/runs/{run.id}/deadline?lang=en"


def stored(run):
    return QuizRun.objects.get(pk=run.pk)


def test_the_run_page_shows_times_and_the_form(logged_in):
    run = a_run(limit=600)
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert "2030-01-01 13:00 CET" in html
    assert 'name="deadline_at"' in html
    assert 'value="2030-01-01T13:00"' in html
    assert 'id="clock"' in html
    assert "10 min" in html


def test_an_ended_run_has_no_form(logged_in):
    run = a_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert 'name="deadline_at"' not in text(logged_in.get(f"/admin/runs/{run.id}"))


def test_moving_later_applies_at_once(logged_in):
    run = a_run()
    response = logged_in.post(url(run), {"deadline_at": "2030-01-01T15:00"})
    assert response.status_code == 302
    assert stored(run).deadline_at == NOW + timedelta(hours=4)


def test_moving_earlier_asks_with_the_number_in_progress(logged_in):
    run = a_run()
    attempts.start(run)
    response = logged_in.post(url(run), {"deadline_at": "2030-01-01T12:00"})
    html = text(response)
    assert response.status_code == 200
    assert "Attempts in progress: 1" in html
    assert 'name="confirmed"' in html
    assert 'value="2030-01-01T12:00"' in html
    assert stored(run).deadline_at == DEADLINE


def test_confirming_applies_it(logged_in):
    run = a_run()
    logged_in.post(url(run), {"deadline_at": "2030-01-01T12:00", "confirmed": "1"})
    assert stored(run).deadline_at == NOW + timedelta(hours=1)


def test_adding_a_first_deadline_asks_as_well(logged_in):
    run = a_run(deadline=None)
    response = logged_in.post(url(run), {"deadline_at": "2030-01-01T12:00"})
    assert 'name="confirmed"' in text(response)
    assert stored(run).deadline_at is None


def test_removing_the_deadline_applies_at_once(logged_in):
    run = a_run()
    logged_in.post(url(run), {"deadline_at": ""})
    assert stored(run).deadline_at is None


def test_less_than_a_minute_ahead_is_refused_with_a_message(logged_in):
    run = a_run()
    response = logged_in.post(
        url(run), {"deadline_at": clock.form_value(NOW + timedelta(seconds=30)), "confirmed": "1"}
    )
    assert "at least a minute" in text(response)
    assert stored(run).deadline_at == DEADLINE


def test_a_time_that_cannot_be_read_is_refused(logged_in):
    run = a_run()
    response = logged_in.post(url(run), {"deadline_at": "nonsense"})
    assert response.status_code == 200
    assert stored(run).deadline_at == DEADLINE


def test_an_ended_run_is_refused(logged_in):
    run = a_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    logged_in.post(url(run), {"deadline_at": "2030-01-01T15:00"})
    assert stored(run).deadline_at == DEADLINE


def test_the_limit_cannot_be_changed_on_an_open_run(logged_in):
    run = a_run(limit=600)
    assert 'name="limit_minutes"' not in text(logged_in.get(f"/admin/runs/{run.id}"))
    assert logged_in.get(f"/admin/runs/{run.id}/plan").status_code == 404
    response = logged_in.post(
        f"/admin/runs/{run.id}/plan",
        {"starts_at": "2030-01-01T15:00", "deadline_at": "", "limit_minutes": "1"},
    )
    assert response.status_code == 404
    assert stored(run).attempt_limit_sec == 600


def test_a_page_learns_a_moved_deadline(logged_in):
    run = a_run()
    started = attempts.start(run)
    assert attempts.remaining(started.attempt.id, started.token) == 7200
    logged_in.post(url(run), {"deadline_at": "2030-01-01T11:30", "confirmed": "1"})
    assert attempts.remaining(started.attempt.id, started.token) == 1800


def test_login_is_required(client):
    run = a_run()
    assert client.post(url(run), {"deadline_at": ""}).status_code == 302
    assert stored(run).deadline_at == DEADLINE


def test_the_run_page_clock_links_to_the_zone_setting(logged_in):
    run = a_run(limit=600)
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    panel = html[html.index('id="clock"') :]
    assert 'href="/admin/settings' in panel
    assert 'name="time_zone"' not in html
