"""AC-185: a quiz change is offered to the planned or open run and applied by the answer."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import transaction

from app.contracts import REWARD_SOURCE
from app.domain import (
    attempts,
    authoring,
    data_policy,
    rewards,
    run_flow,
    run_flow_change,
    run_links,
    setting_rules,
    settings,
)
from app.domain.models import QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, keep, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def save(quiz, key, value):
    settings.set_override(key, quiz, value, admin_id=ADMIN_ID)


def open_run(**plan):
    quiz = published_quiz()
    return quiz, authoring.open_run(quiz, admin_id=ADMIN_ID)


def settle(quiz, key, value, choice):
    before = run_flow.snapshot(quiz)
    with transaction.atomic():
        save(quiz, key, value)
        run_flow_change.settle(quiz, before, choice, admin_id=ADMIN_ID)


def threshold():
    texts = {"cs": {"name": "Cena", "description": "", "claim": ""}}
    return rewards.RuleData(
        kind="threshold", texts=texts, threshold_unit="percent", threshold_value=Decimal(50)
    )


def test_without_a_live_run_nothing_is_offered():
    """AC-185: no run, a closed run, an archived run or only a test run is not asked."""
    quiz = published_quiz()
    before = run_flow.snapshot(quiz)
    after = before | {settings.SHUFFLE_OPTIONS: "on"}
    assert run_flow_change.offer_for(quiz, before, after) is None
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert run_flow_change.offer_for(quiz, before, after) is not None
    for status in (QuizRun.Status.CLOSED, QuizRun.Status.ARCHIVED):
        QuizRun.objects.filter(pk=run.pk).update(status=status)
        assert run_flow_change.offer_for(quiz, before, after) is None


def test_a_test_run_is_never_offered_the_change():
    """AC-185: a test run alone gets no offer and no write; beside a normal run it is skipped."""
    quiz = published_quiz()
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    test_run = QuizRun.all_kinds.get(pk=link.run_id)
    assert test_run.status == QuizRun.Status.OPEN
    before = run_flow.snapshot(quiz)
    after = before | {settings.SHUFFLE_OPTIONS: "on"}
    assert run_flow_change.offer_for(quiz, before, after) is None
    kept = test_run.flow_json
    with transaction.atomic():
        save(quiz, settings.SHUFFLE_OPTIONS, "on")
        run_flow_change.settle(quiz, before, run_flow_change.RUN, admin_id=ADMIN_ID)
    assert QuizRun.all_kinds.get(pk=test_run.pk).flow_json == kept
    normal = authoring.open_run(quiz, admin_id=ADMIN_ID)
    later = run_flow.snapshot(quiz) | {settings.SHUFFLE_QUESTIONS: "on"}
    offer = run_flow_change.offer_for(quiz, run_flow.snapshot(quiz), later)
    assert offer.run.pk == normal.pk


def test_an_unchanged_value_offers_nothing():
    """AC-185: before equal to after offers nothing."""
    quiz, _ = open_run()
    before = run_flow.snapshot(quiz)
    assert run_flow_change.offer_for(quiz, before, dict(before)) is None


def test_a_value_the_run_already_has_offers_nothing():
    """AC-185: the run already keeps the new value."""
    quiz, run = open_run()
    before = run_flow.snapshot(quiz)
    keep(run, settings.SHUFFLE_OPTIONS, "on")
    after = before | {settings.SHUFFLE_OPTIONS: "on"}
    assert run_flow_change.offer_for(quiz, before, after) is None


def test_only_the_keys_this_save_changed_are_offered():
    """AC-185: an earlier "next run" answer is not offered again."""
    quiz = published_quiz()
    save(quiz, settings.REVEAL_MOMENT, "never")
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    keep(run, settings.REVEAL_MOMENT, "at_end")
    before = run_flow.snapshot(quiz)
    after = before | {settings.SHUFFLE_QUESTIONS: "on"}
    offer = run_flow_change.offer_for(quiz, before, after)
    assert [c.key for c in offer.changes] == [settings.SHUFFLE_QUESTIONS]
    assert offer.changes[0].kept == run_flow.of(run)[settings.SHUFFLE_QUESTIONS]
    assert offer.changes[0].new == "on"


def test_no_answer_rolls_the_save_back():
    """AC-185: without a choice nothing is saved."""
    quiz, _ = open_run()
    before = run_flow.snapshot(quiz)
    with pytest.raises(run_flow_change.ChoiceNeeded), transaction.atomic():
        settings.set_override(settings.NAVIGATION_MODE, quiz, "pages", admin_id=ADMIN_ID)
        run_flow_change.settle(quiz, before, None, admin_id=ADMIN_ID)
    assert settings.quiz_override(settings.NAVIGATION_MODE, quiz) is None


def test_next_leaves_the_run():
    """AC-185: "next run" keeps the quiz change and leaves the run as it is."""
    quiz, run = open_run()
    kept = run_flow.of(run)
    settle(quiz, settings.SHUFFLE_OPTIONS, "on", run_flow_change.NEXT)
    run.refresh_from_db()
    assert run_flow.of(run) == kept
    assert settings.quiz_override(settings.SHUFFLE_OPTIONS, quiz) == "on"


def test_run_writes_only_the_changed_keys_and_audits_keys_only():
    """AC-185: the run takes the changed key, audit has keys and no values."""
    quiz, run = open_run()
    kept = run_flow.of(run)
    settle(quiz, settings.SHUFFLE_OPTIONS, "on", run_flow_change.RUN)
    run.refresh_from_db()
    assert run_flow.of(run) == kept | {settings.SHUFFLE_OPTIONS: "on"}
    event = AuditEvent.objects.get(action="run.flow_applied")
    assert event.entity_id == str(run.id)
    assert event.details_json == {"keys": [settings.SHUFFLE_OPTIONS]}


def test_a_run_with_rewards_cannot_take_after_each():
    """AC-185: reward rules refuse answers after each question for the run only."""
    quiz = published_quiz()
    rewards.save_rule(quiz, threshold(), rule=None, admin_id=ADMIN_ID)
    save(quiz, REWARD_SOURCE, "quiz")
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    before = run_flow.snapshot(quiz)
    after = before | {settings.REVEAL_MOMENT: "after_each"}
    offer = run_flow_change.offer_for(quiz, before, after)
    assert [c.reason for c in offer.refused] == [setting_rules.RUN_REWARDS]
    with pytest.raises(run_flow_change.FlowRefused) as raised, transaction.atomic():
        save(quiz, settings.REVEAL_MOMENT, "after_each")
        run_flow_change.settle(quiz, before, run_flow_change.RUN, admin_id=ADMIN_ID)
    assert raised.value.offer.refused
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) is None
    settle(quiz, settings.REVEAL_MOMENT, "after_each", run_flow_change.NEXT)
    run.refresh_from_db()
    assert run_flow.of(run)[settings.REVEAL_MOMENT] != "after_each"


def test_run_clashes_follow_the_old_run_rules():
    """AC-185: flow, profile and board clashes judged for one run."""
    quiz, run = open_run()
    values = run_flow.of(run)
    after_each = values | {settings.REVEAL_MOMENT: "after_each"}
    pages = after_each | {settings.NAVIGATION_MODE: "pages"}
    assert [c.reason for c in setting_rules.run_clashes(run, pages)] == [setting_rules.FLOW]
    after_close = values | {settings.REVEAL_MOMENT: "after_close"}
    assert [c.reason for c in setting_rules.run_clashes(run, after_close)] == [
        setting_rules.RUN_PROFILE
    ]
    run.retention_json = run.retention_json | {data_policy.PROFILE: "answers"}
    run.save(update_fields=["retention_json"])
    assert setting_rules.run_clashes(run, after_close) == []
    run.results_json = (run.results_json or {}) | {"scoreboard_visibility": "live"}
    run.save(update_fields=["results_json"])
    assert [c.reason for c in setting_rules.run_clashes(run, after_each)] == [
        setting_rules.RUN_BOARD
    ]


def test_an_attempt_in_progress_keeps_its_settings():
    """AC-185: an attempt keeps what it started with; a new one takes the changed run."""
    quiz, run = open_run()
    keep(run, settings.NAVIGATION_MODE, "step_back")
    first = attempts.start(run)
    settle(quiz, settings.NAVIGATION_MODE, "all_at_once", run_flow_change.RUN)
    run.refresh_from_db()
    assert run_flow.of(run)[settings.NAVIGATION_MODE] == "all_at_once"
    assert attempts.resume(first.attempt).attempt.settings_json["navigation"] == "step_back"
    assert attempts.start(run).attempt.settings_json["navigation"] == "all_at_once"
