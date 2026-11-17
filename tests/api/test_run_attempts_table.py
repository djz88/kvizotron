"""AC-75: the run page lists who sent an attempt; the e-mail stays in the administration."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import attempts, authoring, participants, tokens
from app.domain.models import Attempt, Participant
from tests.api.test_identity_flow import Browser
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)
EMAIL = "tajne@x.cz"


@pytest.fixture(autouse=True)
def at_nine(monkeypatch):
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def a_run(**rules):
    rules = {"ask_name": "optional", "ask_email": "optional"} | rules
    return authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules)


def send(run, name="", email="", key="k"):
    who = participants.find_or_create(run, key)
    started = attempts.start(run, participant=who)
    identity = participants.read_identity(participants.rules_of(run), name, email, automatic=False)
    attempts.submit(
        started.attempt.id,
        started.token,
        {},
        "s" * 12 + key + str(Attempt.objects.count()),
        identity=identity,
    )
    return Attempt.objects.get(pk=started.attempt.id)


def page(client, run):
    return text(client.get(f"/admin/runs/{run.id}/attempts?lang=en"))


def test_table_shows_name_email_score_time(logged_in):
    run = a_run()
    send(run, "Jana Nováková", EMAIL)
    html = page(logged_in, run)
    assert "Jana Nováková" in html
    assert EMAIL in html
    assert "0 / 1" in html
    assert "2030-01-01" in html


def test_table_lists_only_finished(logged_in):
    run = a_run()
    send(run, "Hotová", key="a")
    attempts.start(run, participant=participants.find_or_create(run, "b"))
    authoring.close_run(run, admin_id=ADMIN_ID)
    html = page(logged_in, run)
    assert "Hotová" in html
    assert html.count("data-attempt-row") == 1
    assert "Not sent: 1" in text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))


def test_empty_name_shows_bez_jmena(logged_in):
    run = a_run()
    send(run)
    assert "no name" in page(logged_in, run)
    assert "bez jména" in text(logged_in.get(f"/admin/runs/{run.id}/attempts?lang=cs"))


def test_rows_follow_submission_time(logged_in, monkeypatch):
    run = a_run()
    send(run, "Druhá", key="a")
    freeze(monkeypatch, NOW - timedelta(hours=1))
    send(run, "První", key="b")
    html = page(logged_in, run)
    assert html.index("První") < html.index("Druhá")


def test_email_absent_from_public_pages():
    run = a_run(ask_when="start")
    browser = Browser(run)
    browser.start(participant_name="Jana", participant_email=EMAIL)
    browser.submit()
    assert EMAIL not in browser.result
    attempt = Attempt.objects.get()
    assert Participant.objects.get().email == EMAIL
    client = FormClient()
    result = text(client.get(f"/v/{tokens.issue_result(attempt.id)}"))
    assert EMAIL not in result
    assert EMAIL not in text(client.get(f"/q/{run.quiz.slug}"))
    walk = text(client.get(f"/q/{run.quiz.slug}/r/{run.id}/answers"))
    assert EMAIL not in walk


def test_table_needs_login():
    run = a_run()
    send(run, "Jana", EMAIL)
    response = FormClient().get(f"/admin/runs/{run.id}")
    assert response.status_code in (302, 401, 403)
    assert EMAIL not in text(response)
