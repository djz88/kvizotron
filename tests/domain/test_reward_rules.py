"""AC-09, AC-18, AC-90, AC-93: reward rules are copied onto a run, and refused where they fail.

A run gets its rules when it is planned or opened, from the source the settings name; their
structure is fixed once the run opens, their texts never are. Rules cannot go with the data
profile "none", with answers after each question, or, under "a draw requires an e-mail", with a
draw on a run that does not require one.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import translation

from app.contracts import ASK_EMAIL, REWARD_SOURCE, REWARD_THRESHOLDS, WINNER_CONTACT
from app.domain import authoring, participants, rewards, run_links, run_schedule, settings
from app.domain.models import QuizRun, RewardRule
from app.kernel.models import AdminUser, AuditEvent
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)

THRESHOLD = rewards.RuleData(
    kind="threshold",
    threshold_unit="percent",
    threshold_value=Decimal("80"),
    texts={"cs": {"name": "Odznak", "description": "Za 80 %", "claim": "U pultu"}},
)
DRAW = rewards.RuleData(
    kind="draw",
    winners=1,
    alternates=2,
    texts={"cs": {"name": "Hlavní cena", "description": "", "claim": ""}},
)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


@pytest.fixture
def logged_in():
    client = FormClient()
    client.force_login(AdminUser.objects.create_admin("alice", "dlouhe-a-neobvykle-heslo"))
    return client


def with_template(*rules, source="quiz", slug="kviz"):
    quiz = published_quiz(slug)
    for data in rules:
        rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, source, admin_id=ADMIN_ID)
    return quiz


def plan(quiz, **kwargs):
    return run_schedule.plan(
        quiz,
        starts_at=NOW + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        **kwargs,
    )


def names(run):
    return [rule.texts_json["cs"]["name"] for rule in rewards.rules_of(run)]


def answers_after_each(quiz):
    settings.set_override(settings.NAVIGATION_MODE, quiz, "step_back", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=ADMIN_ID)


def test_source_none_copies_nothing():
    quiz = with_template(THRESHOLD, source="none")
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert not rewards.has_rules(run)
    assert rewards.rules_of(run) == []


def test_source_quiz_copies_template():
    quiz = with_template(THRESHOLD, DRAW)
    template = rewards.template_of(quiz)
    run = plan(quiz)
    copied = rewards.rules_of(run)
    assert names(run) == ["Odznak", "Hlavní cena"]
    assert [rule.kind for rule in copied] == ["threshold", "draw"]
    assert copied[0].threshold_value == Decimal("80")
    assert copied[1].winners == 1 and copied[1].alternates == 2
    assert all(rule.run_id == run.id and not rule.winners_public for rule in copied)
    assert {rule.id for rule in copied}.isdisjoint({rule.id for rule in template})
    assert len(rewards.template_of(quiz)) == 2


def test_source_previous_run_copies_last_run_and_falls_back_to_template():
    quiz = with_template(THRESHOLD, source="previous_run")
    first = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert names(first) == ["Odznak"]  # no earlier run: the template
    rewards.save_texts(
        rewards.rules_of(first)[0],
        {"cs": {"name": "Odznak běhu 1", "description": "", "claim": ""}},
        admin_id=ADMIN_ID,
    )
    authoring.close_run(first, admin_id=ADMIN_ID)
    second = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert names(second) == ["Odznak běhu 1"]


def test_template_change_does_not_reach_planned_run():
    quiz = with_template(THRESHOLD)
    run = plan(quiz)
    rewards.save_rule(quiz, DRAW, rule=None, admin_id=ADMIN_ID)
    template_rule = rewards.template_of(quiz)[0]
    rewards.save_texts(
        template_rule, {"cs": {"name": "Jiný", "description": "", "claim": ""}}, admin_id=ADMIN_ID
    )
    assert names(run) == ["Odznak"]


def test_test_run_gets_no_rules():
    quiz = with_template(THRESHOLD)
    link = run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id="a")
    rewards.copy_rules(link.run)
    assert not RewardRule.objects.filter(run=link.run).exists()
    assert not rewards.has_rules(link.run)
    assert rewards.conflicts(link.run) == []


def test_rules_refused_with_profile_none():
    quiz = with_template(THRESHOLD)
    with pytest.raises(rewards.RewardConflict) as refused:
        authoring.open_run(quiz, admin_id=ADMIN_ID, data={"profile": "none"})
    assert refused.value.keys == ["profile"]
    with translation.override("en"):
        assert refused.value.messages() == ["Rewards need a data profile that keeps scores."]
    with pytest.raises(rewards.RewardConflict):
        plan(quiz, data={"profile": "none"})
    assert not QuizRun.objects.exists()
    assert not RewardRule.objects.filter(run__isnull=False).exists()
    authoring.open_run(
        with_template(source="quiz", slug="bez"), admin_id=ADMIN_ID, data={"profile": "none"}
    )


def test_rules_refused_with_after_each():
    quiz = with_template(THRESHOLD)
    answers_after_each(quiz)
    with pytest.raises(rewards.RewardConflict) as refused:
        authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert refused.value.keys == ["reveal"]
    assert not QuizRun.objects.exists()


def test_require_email_refuses_draw_without_required_email():
    quiz = with_template(DRAW)
    settings.set_override(WINNER_CONTACT, quiz, "require_email", admin_id=ADMIN_ID)
    with pytest.raises(rewards.RewardConflict) as refused:
        plan(quiz, rules={ASK_EMAIL: "optional"})
    assert refused.value.keys == ["contact"]
    assert not QuizRun.objects.exists()
    run = plan(quiz, rules={ASK_EMAIL: "required"})
    assert rewards.of(run)[WINNER_CONTACT] == "require_email"
    with pytest.raises(rewards.RewardConflict):
        run_schedule.update_plan(
            run,
            starts_at=NOW + timedelta(hours=2),
            deadline_at=None,
            limit_sec=None,
            admin_id=ADMIN_ID,
            rules={ASK_EMAIL: "off"},
        )
    run.refresh_from_db()
    assert participants.rules_of(run)[ASK_EMAIL] == "required"
    # A threshold rule needs no contact.
    other = with_template(THRESHOLD, slug="prah")
    settings.set_override(WINNER_CONTACT, other, "require_email", admin_id=ADMIN_ID)
    planned = plan(other)
    # Adding a draw to the plan is checked as well.
    with pytest.raises(rewards.RewardConflict):
        rewards.save_rule(planned, DRAW, rule=None, admin_id=ADMIN_ID)
    assert len(rewards.rules_of(planned)) == 1


@pytest.mark.parametrize("contact", ["warn", "silent"])
def test_warn_and_silent_allow_it(contact):
    quiz = with_template(DRAW)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, rewards={WINNER_CONTACT: contact})
    assert rewards.of(run)[WINNER_CONTACT] == contact
    assert rewards.conflicts(run) == []
    assert rewards.has_rules(run)


def test_structure_locked_once_open_texts_editable():
    quiz = with_template(THRESHOLD)
    planned = plan(quiz)
    rule = rewards.rules_of(planned)[0]
    changed = rewards.RuleData(
        kind="threshold", threshold_unit="points", threshold_value=Decimal("3"), texts={}
    )
    rewards.save_rule(planned, changed, rule=rule, admin_id=ADMIN_ID)
    rule.refresh_from_db()
    assert (rule.threshold_unit, rule.threshold_value) == ("points", Decimal("3"))
    run_schedule.start_now(planned, admin_id=ADMIN_ID)
    run = QuizRun.objects.get(pk=planned.pk)
    with pytest.raises(rewards.RuleLocked):
        rewards.save_rule(run, THRESHOLD, rule=rule, admin_id=ADMIN_ID)
    with pytest.raises(rewards.RuleLocked):
        rewards.save_rule(run, DRAW, rule=None, admin_id=ADMIN_ID)
    with pytest.raises(rewards.RuleLocked):
        rewards.delete_rule(rule, admin_id=ADMIN_ID)
    texts = {"cs": {"name": "Nový", "description": "Popis", "claim": "Napište nám"}}
    rewards.save_texts(rule, texts, admin_id=ADMIN_ID)
    rule.refresh_from_db()
    assert rule.texts_json == texts
    assert rule.threshold_value == Decimal("3")
    events = AuditEvent.objects.filter(action__startswith="reward.", entity_id=str(rule.id))
    assert {event.action for event in events} == {"reward.rule_saved", "reward.texts_saved"}
    assert all("Nový" not in str(event.details_json) for event in events)


def test_rule_values_are_checked():
    quiz = published_quiz()
    for data in (
        rewards.RuleData(kind="threshold", threshold_unit="percent", threshold_value=Decimal(101)),
        rewards.RuleData(kind="threshold", threshold_unit="points", threshold_value=Decimal(0)),
        rewards.RuleData(kind="draw", winners=0),
        rewards.RuleData(kind="draw", winners=1, alternates=21),
        rewards.RuleData(kind="lottery"),
    ):
        with pytest.raises(rewards.RuleInvalid):
            rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    rule = rewards.save_rule(
        quiz, rewards.RuleData(kind="draw", winners=2), rule=None, admin_id=ADMIN_ID
    )
    assert rule.alternates == 2


def test_rules_make_participant_needed():
    plain = authoring.open_run(published_quiz("bez"), admin_id=ADMIN_ID)
    assert not participants.needs_participant(plain)
    run = authoring.open_run(with_template(THRESHOLD), admin_id=ADMIN_ID)
    assert participants.needs_participant(run)


def test_start_now_rechecks():
    quiz = with_template(THRESHOLD)
    run = plan(quiz)
    QuizRun.objects.filter(pk=run.pk).update(
        retention_json={"profile": "none", "period": "forever"}
    )
    run.refresh_from_db()
    with pytest.raises(rewards.RewardConflict):
        run_schedule.start_now(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.status == QuizRun.Status.SCHEDULED


def test_plan_stores_run_settings():
    quiz = with_template(THRESHOLD)
    settings.set_override(REWARD_THRESHOLDS, quiz, "all", admin_id=ADMIN_ID)
    run = plan(quiz, rewards={WINNER_CONTACT: "silent"})
    assert rewards.of(run) == {REWARD_THRESHOLDS: "all", WINNER_CONTACT: "silent"}
    settings.set_override(REWARD_THRESHOLDS, quiz, "highest", admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert rewards.of(run)[REWARD_THRESHOLDS] == "all"


def test_quiz_after_each_refused_when_run_has_rules(logged_in):
    quiz = with_template(THRESHOLD)
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings?lang=en",
        {"slug": quiz.slug, "navigation_mode": "step_back", "reveal_moment": "after_each"},
    )
    assert "Answers after each question cannot go with rewards." in response.content.decode()
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) is None


@pytest.mark.django_db(transaction=True)
def test_migration_0016_leaves_runs_without_rules():
    executor = MigrationExecutor(connection)
    before = [("domain", "0015_navigation_default")]
    executor.migrate(before)
    old = executor.loader.project_state(before).apps
    quiz = old.get_model("domain", "Quiz").objects.create(
        slug="kviz", title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    revision = old.get_model("domain", "QuizRevision").objects.create(
        quiz=quiz, revision_no=1, status="PUBLISHED"
    )
    old.get_model("domain", "QuizRun").objects.create(
        quiz=quiz, run_no=1, current_revision=revision
    )
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        run = QuizRun.objects.get()
        assert run.rewards_json == {}
        assert not rewards.has_rules(run)
        assert rewards.of(run) == {REWARD_THRESHOLDS: "highest", WINNER_CONTACT: "warn"}
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def test_winners_are_bounded_like_the_form():
    from app.domain import rewards as module

    for winners in (0, module.MAX_WINNERS + 1):
        with pytest.raises(module.RuleInvalid) as caught:
            module._structure(module.RuleData(kind="draw", winners=winners))
        assert caught.value.code == "winners_invalid"
    assert module._structure(module.RuleData(kind="draw", winners=module.MAX_WINNERS))["winners"]
