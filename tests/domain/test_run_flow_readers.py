"""AC-185: attempts and run checks read the run's kept values, not the quiz as it is now."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import REWARD_SOURCE, SCOREBOARD_VISIBILITY
from app.domain import attempts, authoring, data_policy, results, rewards, run_schedule, settings
from app.domain.models import QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = NOW + timedelta(hours=1)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def change(quiz, key, value):
    settings.set_override(key, quiz, value, admin_id=ADMIN_ID)


def threshold():
    texts = {"cs": {"name": "Cena", "description": "", "claim": ""}}
    return rewards.RuleData(
        kind="threshold", texts=texts, threshold_unit="percent", threshold_value=Decimal(50)
    )


def test_a_new_attempt_plays_by_the_run():
    """AC-185: an attempt takes navigation and shuffle from the run, not the changed quiz."""
    quiz = published_quiz()
    change(quiz, settings.NAVIGATION_MODE, "step_back")
    change(quiz, settings.SHUFFLE_OPTIONS, "off")
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    change(quiz, settings.NAVIGATION_MODE, "all_at_once")
    change(quiz, settings.SHUFFLE_OPTIONS, "on")

    started = attempts.start(run)

    assert started.attempt.settings_json["navigation"] == "step_back"
    assert started.attempt.selection_json["seed"] is None


def test_rewards_conflicts_read_the_run():
    """AC-185: a run kept at the end of the quiz is not in conflict when the quiz reveals later."""
    quiz = published_quiz()
    rewards.save_rule(quiz, threshold(), rule=None, admin_id=ADMIN_ID)
    change(quiz, REWARD_SOURCE, "quiz")
    change(quiz, settings.REVEAL_MOMENT, "at_end")
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    change(quiz, settings.REVEAL_MOMENT, "after_each")

    assert rewards.conflicts(run) == []


def test_set_display_judges_the_run_reveal():
    """AC-185: showing the board live passes when the run reveals at the end."""
    quiz = published_quiz()
    change(quiz, settings.REVEAL_MOMENT, "at_end")
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    change(quiz, settings.REVEAL_MOMENT, "after_each")

    results.set_display(run, {SCOREBOARD_VISIBILITY: "live"}, admin_id=ADMIN_ID)

    run.refresh_from_db()
    assert run.results_json[SCOREBOARD_VISIBILITY] == "live"


def test_a_plan_edit_judges_the_kept_reveal():
    """AC-185: a plan kept at the end accepts a profile that drops answers after the quiz moved."""
    quiz = published_quiz()
    change(quiz, settings.REVEAL_MOMENT, "at_end")
    run = run_schedule.plan(
        quiz, starts_at=START, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID
    )
    change(quiz, settings.REVEAL_MOMENT, "after_close")

    run_schedule.update_plan(
        run,
        starts_at=START,
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        data={data_policy.PROFILE: "score"},
    )

    run.refresh_from_db()
    assert run.retention_json[data_policy.PROFILE] == "score"


def test_opening_a_plan_judges_the_kept_reveal(monkeypatch):
    """AC-185: a plan with a score profile opens when the quiz moved to after_close meanwhile."""
    quiz = published_quiz()
    change(quiz, settings.REVEAL_MOMENT, "at_end")
    run = run_schedule.plan(
        quiz,
        starts_at=START,
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        data={data_policy.PROFILE: "score"},
    )
    change(quiz, settings.REVEAL_MOMENT, "after_close")
    freeze(monkeypatch, START + timedelta(minutes=1))

    run_schedule.settle()

    run = QuizRun.all_kinds.get(pk=run.pk)
    assert run.status == QuizRun.Status.OPEN
