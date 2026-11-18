"""AC-185: a run keeps navigation, page size, reveal, shuffle and sources (ADR-0069)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import authoring, run_flow, run_links, run_schedule, settings
from app.domain.models import QuizRun
from tests.domain.helpers import ADMIN_ID, add_question, open_quiz_run, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = NOW + timedelta(hours=1)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def change(quiz, key, value):
    settings.set_override(key, quiz, value, admin_id=ADMIN_ID)


def plan(quiz):
    return run_schedule.plan(
        quiz, starts_at=START, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID
    )


def test_a_planned_run_keeps_the_quiz_values():
    """AC-185: planning copies the seven values the quiz resolves."""
    quiz = published_quiz()
    change(quiz, settings.REVEAL_MOMENT, "at_end")

    run = plan(quiz)

    run.refresh_from_db()
    assert set(run.flow_json) == set(run_flow.KEYS)
    assert run.flow_json == run_flow.snapshot(quiz)
    assert run.flow_json[settings.REVEAL_MOMENT] == "at_end"


def test_an_opened_run_keeps_the_quiz_values():
    """AC-185: opening copies the seven values the quiz resolves."""
    quiz = published_quiz()
    change(quiz, settings.SHUFFLE_QUESTIONS, "on")

    run = authoring.open_run(quiz, admin_id=ADMIN_ID)

    run.refresh_from_db()
    assert run.flow_json == run_flow.snapshot(quiz)
    assert run.flow_json[settings.SHUFFLE_QUESTIONS] == "on"


def test_a_quiz_change_after_opening_does_not_reach_the_run():
    """AC-185: a later quiz or global change leaves the open run as it was."""
    run = open_quiz_run()
    before = run_flow.of(run)

    change(run.quiz, settings.NAVIGATION_MODE, "pages")
    settings.set_global(settings.SHOW_SOURCES, "off", admin_id=ADMIN_ID)

    assert run_flow.of(run)[settings.NAVIGATION_MODE] == before[settings.NAVIGATION_MODE]
    assert run_flow.of(run)[settings.SHOW_SOURCES] == before[settings.SHOW_SOURCES]
    assert run_flow.flow(run).navigation == before[settings.NAVIGATION_MODE]


def test_a_test_run_follows_the_quiz():
    """AC-185: a test run has no plan and reads the quiz as it is now."""
    quiz = published_quiz()
    link = run_links.create(quiz, None, expires_at=None, admin_id=ADMIN_ID)
    run = QuizRun.all_kinds.get(pk=link.run_id)
    assert run.flow_json == {}

    change(quiz, settings.NAVIGATION_MODE, "pages")

    assert run_flow.of(run)[settings.NAVIGATION_MODE] == "pages"
    assert run_flow.flow(run).navigation == "pages"


def test_a_plan_edit_keeps_the_kept_values():
    """AC-185: editing a plan does not copy the quiz values again."""
    quiz = published_quiz()
    run = plan(quiz)
    old = run.flow_json[settings.REVEAL_MOMENT]

    change(quiz, settings.REVEAL_MOMENT, "never" if old != "never" else "at_end")
    run_schedule.update_plan(
        run, starts_at=START, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID
    )

    run.refresh_from_db()
    assert run.flow_json[settings.REVEAL_MOMENT] == old


def test_a_revision_switch_keeps_the_values():
    """AC-185: moving the run to a newer revision leaves its values."""
    run = open_quiz_run()
    kept = dict(run.flow_json)
    change(run.quiz, settings.SHUFFLE_OPTIONS, "on")
    add_question(run.quiz)

    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)

    run.refresh_from_db()
    assert run.current_revision.revision_no == 2
    assert run.flow_json == kept


def test_a_value_no_longer_offered_falls_back_to_the_quiz():
    """AC-185: a stored value the catalogue no longer offers is read from the quiz."""
    run = open_quiz_run()
    run.flow_json[settings.PAGE_SIZE] = "999"
    del run.flow_json[settings.REVEAL_LEVEL]

    values = run_flow.of(run)

    assert values[settings.PAGE_SIZE] == settings.resolve(settings.PAGE_SIZE, run.quiz)
    assert values[settings.REVEAL_LEVEL] == settings.resolve(settings.REVEAL_LEVEL, run.quiz)
