"""What a participant sees of a planned run (FR-10, ADR-0048)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import authoring, run_schedule, settings
from tests.domain.helpers import ADMIN_ID, add_question, published_quiz
from tests.support.clock import freeze
from tests.support.requirements import needs_reveal_at_end

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = datetime(2030, 1, 1, 17, 0, tzinfo=UTC)
START_SHOWN = "2030-01-01 18:00 CET"


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def planned_quiz(**fields):
    quiz = published_quiz(locales=("en",), **fields)
    run_schedule.plan(quiz, starts_at=START, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID)
    return quiz


def test_address_of_a_planned_quiz_shows_title_and_start_without_a_button(client):
    quiz = planned_quiz()
    html = text(client.get(f"/q/{quiz.slug}?lang=en"))
    assert "Název en" in html
    assert "Popis en" in html
    assert START_SHOWN in html
    assert "/start" not in html


def test_its_run_address_shows_the_same(client):
    quiz = planned_quiz()
    run = quiz.runs.get()
    html = text(client.get(f"/q/{quiz.slug}/r/{run.id}?lang=en"))
    assert START_SHOWN in html
    assert "/start" not in html


def test_a_planned_quiz_is_not_on_the_list_by_default(client):
    quiz = planned_quiz()
    assert f"/q/{quiz.slug}" not in text(client.get("/?lang=en"))


def test_it_is_under_coming_up_when_announced_globally(client):
    settings.set_global(settings.ANNOUNCE_PLANNED, "on", admin_id=None)
    quiz = planned_quiz()
    html = text(client.get("/?lang=en"))
    assert "Coming up" in html
    assert f"/q/{quiz.slug}" in html
    assert START_SHOWN in html


def test_a_quiz_override_beats_the_global_value(client):
    settings.set_global(settings.ANNOUNCE_PLANNED, "on", admin_id=None)
    quiz = planned_quiz()
    settings.set_override(settings.ANNOUNCE_PLANNED, quiz, "off", admin_id=None)
    assert "Coming up" not in text(client.get("/?lang=en"))


def test_a_quiz_can_announce_itself_alone(client):
    quiz = planned_quiz()
    settings.set_override(settings.ANNOUNCE_PLANNED, quiz, "on", admin_id=None)
    assert f"/q/{quiz.slug}" in text(client.get("/?lang=en"))


def test_no_section_without_a_planned_quiz(client):
    settings.set_global(settings.ANNOUNCE_PLANNED, "on", admin_id=None)
    assert "Coming up" not in text(client.get("/?lang=en"))


def test_announcing_is_not_a_question_setting():
    assert settings.ANNOUNCE_PLANNED in settings.keys_for("quiz")
    assert settings.ANNOUNCE_PLANNED not in settings.keys_for("question")
    assert settings.resolve(settings.ANNOUNCE_PLANNED) == "off"


def test_a_passed_start_that_could_not_open_says_not_started_yet_without_a_time(
    client, monkeypatch
):
    quiz = published_quiz(locales=("en",))
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=None)
    run_schedule.plan(quiz, starts_at=START, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID)
    freeze(monkeypatch, START + timedelta(minutes=1))
    with needs_reveal_at_end():
        html = text(client.get(f"/q/{quiz.slug}?lang=en"))
    assert "has not started yet" in html
    assert START_SHOWN not in html
    assert "data-starts-in" not in html
    assert "/start" not in html


def test_the_page_says_seconds_to_the_start_while_it_is_ahead(client):
    quiz = planned_quiz()
    assert 'data-starts-in="25200"' in text(client.get(f"/q/{quiz.slug}?lang=en"))


def test_when_it_opens_the_page_has_the_button(client, monkeypatch):
    quiz = planned_quiz()
    freeze(monkeypatch, START)
    assert "/start" in text(client.get(f"/q/{quiz.slug}?lang=en"))


def test_a_draft_title_does_not_reach_the_page(client):
    quiz = planned_quiz()
    quiz.title = {"en": "Secret draft"}
    quiz.save()
    add_question(quiz, prompt="Koncept")
    html = text(client.get(f"/q/{quiz.slug}?lang=en"))
    assert "Secret draft" not in html
    assert "Název en" in html


def test_a_new_publication_changes_what_the_page_says(client):
    quiz = planned_quiz()
    quiz.title = {"en": "Better title"}
    quiz.save()
    add_question(quiz, prompt="Nová")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    assert "Better title" in text(client.get(f"/q/{quiz.slug}?lang=en"))


def test_a_running_quiz_is_still_listed_first(client):
    settings.set_global(settings.ANNOUNCE_PLANNED, "on", admin_id=None)
    running = published_quiz(slug="bezi", locales=("en",))
    authoring.open_run(running, admin_id=ADMIN_ID)
    planned_quiz(slug="chysta")
    html = text(client.get("/?lang=en"))
    assert html.index("/q/bezi") < html.index("/q/chysta")
