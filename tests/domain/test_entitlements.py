"""AC-10, AC-16, AC-91: entitlements follow the participant's official attempt.

The server grants them in the transaction that stores the submission, and recomputes them when a
later attempt becomes official or when grading ends. A recomputation cancels only what it granted
itself and what was not handed over yet; an attempt that waits for grading counts for nothing.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.db import IntegrityError

from app.contracts import OFFICIAL_ATTEMPT, REWARD_SOURCE, REWARD_THRESHOLDS
from app.domain import (
    access_codes,
    attempts,
    authoring,
    grading,
    participants,
    results,
    rewards,
    run_links,
    run_schedule,
    settings,
)
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    Participant,
    Quiz,
    QuizRun,
    RewardEntitlement,
    RewardRule,
)
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, make_quiz, published_quiz
from tests.support.clock import freeze
from tests.support.graded import add_graded

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
GRANTED = RewardEntitlement.Status.GRANTED
HANDED_OVER = RewardEntitlement.Status.HANDED_OVER
CANCELLED = RewardEntitlement.Status.CANCELLED
ASSET = "a" * 32


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def tier(percent, name=None):
    return rewards.RuleData(
        kind="threshold",
        threshold_unit="percent",
        threshold_value=Decimal(percent),
        texts={"cs": {"name": name or f"Za {percent} %", "description": "", "claim": ""}},
    )


def kind(name):
    return rewards.RuleData(kind=name, texts={"cs": {"name": name, "description": "", "claim": ""}})


def with_rules(quiz, *rules):
    for data in rules:
        rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    return quiz


def a_run(*rules, questions=10, slug="kviz", **chosen):
    quiz = with_rules(published_quiz(slug, questions=questions), *rules)
    return authoring.open_run(quiz, admin_id=ADMIN_ID, **chosen)


def person(run, key="k" * 20):
    return participants.find_or_create(run, key)


def play(run, who, right, key="key-00000001"):
    """Answers the first `right` questions correctly and the rest wrong."""
    started = attempts.start(run, participant=who)
    questions = attempts.questions_of(started.attempt)
    answers = {
        question["id"]: {"options": [OPTION_A if number < right else OPTION_B]}
        for number, question in enumerate(questions)
    }
    attempts.submit(started.attempt.id, started.token, answers, key)
    return Attempt.objects.get(pk=started.attempt.id)


def held(who):
    """Rule name and status of every entitlement, cancelled ones included."""
    rows = RewardEntitlement.objects.filter(participant=who).select_related("rule")
    return sorted((row.rule.texts_json["cs"]["name"], row.status) for row in rows)


def entitlement(who, name):
    return RewardEntitlement.objects.get(
        participant=who, rule__texts_json__cs__name=name, status__in=[GRANTED, HANDED_OVER]
    )


def test_threshold_granted_in_submission_transaction():
    run = a_run(tier(50), questions=2)
    who = person(run)
    attempt = play(run, who, 2)
    row = RewardEntitlement.objects.get()
    assert (row.status, row.source, row.run_id) == (GRANTED, "auto", run.id)
    assert row.participant_id == who.id and row.attempt_id == attempt.id
    assert [found.id for found in rewards.of_participant(who)] == [row.id]
    # When the entitlement cannot be stored, nothing of the submission stays.
    other = person(run, "j" * 20)
    started = attempts.start(run, participant=other)
    with (
        mock.patch.object(rewards, "refresh", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        attempts.submit(started.attempt.id, started.token, {}, "key-00000002")
    assert Attempt.objects.get(pk=started.attempt.id).status == Attempt.Status.IN_PROGRESS


def test_four_of_five_is_80_percent_and_earns_no_90_percent_reward():
    """AC-10: five equal questions, 4 correct: the 80 % reward is granted, the 90 % one is not."""
    run = a_run(tier(80), tier(90), questions=5, rewards={REWARD_THRESHOLDS: "all"})
    who = person(run)
    attempt = play(run, who, 4)
    assert (attempt.score, attempt.max_score) == (Decimal(4), Decimal(5))
    assert held(who) == [("Za 80 %", GRANTED)]


def test_participation_granted_once():
    run = a_run(kind("participation"))
    who = person(run)
    play(run, who, 0)
    play(run, who, 10, key="key-00000002")
    assert held(who) == [("participation", GRANTED)]
    assert RewardEntitlement.objects.get().source == "auto"


def test_better_attempt_moves_tier_under_highest():
    run = a_run(tier(70), tier(90))
    assert rewards.of(run)[REWARD_THRESHOLDS] == "highest"
    who = person(run)
    play(run, who, 7)
    assert held(who) == [("Za 70 %", GRANTED)]
    best = play(run, who, 10, key="key-00000002")
    assert held(who) == [("Za 70 %", CANCELLED), ("Za 90 %", GRANTED)]
    lower = RewardEntitlement.objects.get(status=CANCELLED)
    assert lower.reason == "no_longer_reached" and lower.changed_at is not None
    assert entitlement(who, "Za 90 %").attempt_id == best.id
    assert [row.rule.texts_json["cs"]["name"] for row in rewards.of_participant(who)] == ["Za 90 %"]


def test_all_mode_keeps_both():
    run = a_run(tier(70), tier(90), rewards={REWARD_THRESHOLDS: "all"})
    who = person(run)
    play(run, who, 7)
    assert held(who) == [("Za 70 %", GRANTED)]
    play(run, who, 10, key="key-00000002")
    assert held(who) == [("Za 70 %", GRANTED), ("Za 90 %", GRANTED)]
    assert [row.rule.position for row in rewards.of_participant(who)] == [1, 2]


def test_handed_over_never_cancelled_by_recompute():
    run = a_run(tier(70), tier(90))
    who = person(run)
    play(run, who, 7)
    rewards.hand_over(entitlement(who, "Za 70 %"), admin_id=ADMIN_ID)
    play(run, who, 10, key="key-00000002")
    assert held(who) == [("Za 70 %", HANDED_OVER), ("Za 90 %", GRANTED)]


def photo_run(*rules, slug="kviz"):
    quiz = make_quiz(slug)
    add_graded(quiz)  # 2 of 10 points at once, 8 for a person to give
    authoring.publish(quiz, admin_id=ADMIN_ID)
    with_rules(quiz, *rules)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def send_photo(run, who):
    started = attempts.start(run, participant=who)
    question = attempts.questions_of(started.attempt)[0]["id"]
    attempts.submit(started.attempt.id, started.token, {question: {"image": ASSET}}, "key-1")
    return Attempt.objects.get(pk=started.attempt.id)


def test_pending_photo_grants_nothing_until_graded(graded_type):
    """AC-16: thresholds are not evaluated while a photo waits for grading."""
    run = photo_run(tier(50), kind("participation"))
    who = person(run)
    attempt = send_photo(run, who)
    assert attempt.status == Attempt.Status.PENDING_GRADING
    assert results.official_attempt(who) is None
    assert held(who) == []
    grading.save_manual(AttemptAnswer.objects.get(), Decimal(5), admin_id=ADMIN_ID)
    assert results.official_attempt(who) == attempt
    assert held(who) == [("Za 50 %", GRANTED), ("participation", GRANTED)]


def test_regrade_below_threshold_cancels_granted(graded_type):
    run = photo_run(tier(50), kind("participation"))
    who = person(run)
    send_photo(run, who)
    answer = AttemptAnswer.objects.get()
    grading.save_manual(answer, Decimal(5), admin_id=ADMIN_ID)
    grading.save_manual(answer, Decimal(0), admin_id=ADMIN_ID)
    assert held(who) == [("Za 50 %", CANCELLED), ("participation", GRANTED)]
    assert RewardEntitlement.objects.get(status=CANCELLED).reason == "no_longer_reached"
    # Once handed over, a lower grade leaves it alone; a removed photo as well.
    grading.save_manual(answer, Decimal(5), admin_id=ADMIN_ID)
    rewards.hand_over(entitlement(who, "Za 50 %"), admin_id=ADMIN_ID)
    grading.remove_photo(answer, admin_id=ADMIN_ID)
    assert ("Za 50 %", HANDED_OVER) in held(who)


def test_first_official_attempt_ignores_later_better():
    run = a_run(tier(70), tier(90), results={OFFICIAL_ATTEMPT: "first"})
    who = person(run)
    first = play(run, who, 7)
    play(run, who, 10, key="key-00000002")
    assert results.official_attempt(who) == first
    assert held(who) == [("Za 70 %", GRANTED)]
    assert entitlement(who, "Za 70 %").attempt_id == first.id


def test_manual_grant_hand_over_cancel_audited_without_names():
    run = a_run(kind("manual"), tier(70))
    who = person(run)
    Participant.objects.filter(pk=who.pk).update(display_name="Ema", email="ema@example.org")
    who.refresh_from_db()
    attempt = play(run, who, 0)
    manual = next(rule for rule in rewards.rules_of(run) if rule.kind == "manual")
    granted = rewards.grant_manual(manual, who, admin_id=ADMIN_ID)
    assert (granted.status, granted.source) == (GRANTED, "manual")
    assert rewards.grant_manual(manual, who, admin_id=ADMIN_ID).id == granted.id
    assert RewardEntitlement.objects.count() == 1
    # A recomputation leaves what the admin granted alone.
    play(run, who, 0, key="key-00000002")
    assert held(who) == [("manual", GRANTED)]
    rewards.hand_over(granted, admin_id=ADMIN_ID)
    granted.refresh_from_db()
    assert granted.status == HANDED_OVER and granted.changed_by == ADMIN_ID
    with pytest.raises(rewards.RuleInvalid) as refused:
        rewards.hand_over(granted, admin_id=ADMIN_ID)
    assert refused.value.code == "status"
    for reason in ("", "   ", "x" * 201):
        with pytest.raises(rewards.RuleInvalid) as refused:
            rewards.cancel(granted, reason, admin_id=ADMIN_ID)
        assert refused.value.code == "reason"
    rewards.cancel(granted, "  Nepřišla si  ", admin_id=ADMIN_ID)
    granted.refresh_from_db()
    assert (granted.status, granted.reason) == (CANCELLED, "Nepřišla si")
    assert rewards.of_participant(who) == []
    with pytest.raises(rewards.RuleInvalid) as refused:
        rewards.cancel(granted, "Znovu", admin_id=ADMIN_ID)
    assert refused.value.code == "status"
    # After a cancellation the admin may grant it again, as a new row.
    again = rewards.grant_manual(manual, who, admin_id=ADMIN_ID)
    assert again.id != granted.id and again.status == GRANTED
    events = AuditEvent.objects.filter(action__startswith="reward.entitlement_")
    assert sorted(event.action for event in events) == [
        "reward.entitlement_cancelled",
        "reward.entitlement_granted",
        "reward.entitlement_granted",
        "reward.entitlement_handed_over",
    ]
    for event in events:
        assert event.actor_id == ADMIN_ID and event.entity_type == "reward_entitlement"
        text = str(event.details_json)
        for secret in ("Ema", "ema@example.org", str(who.id), str(attempt.id), "Nepřišla"):
            assert secret not in text


def test_grant_manual_refuses_a_participant_without_a_submitted_attempt():
    run = a_run(kind("manual"))
    who = person(run)
    attempts.start(run, participant=who)
    manual = rewards.rules_of(run)[0]
    with pytest.raises(rewards.NotGrantable):
        rewards.grant_manual(manual, who, admin_id=ADMIN_ID)
    assert not RewardEntitlement.objects.exists()


def test_grant_manual_refuses_other_kinds_and_other_runs():
    run = a_run(tier(70), kind("manual"))
    other = a_run(kind("manual"), slug="jiny")
    threshold, manual = rewards.rules_of(run)
    who = person(run)
    play(run, who, 1)
    with pytest.raises(rewards.RuleInvalid) as refused:
        rewards.grant_manual(threshold, who, admin_id=ADMIN_ID)
    assert refused.value.code == "kind"
    stranger = person(other)
    play(other, stranger, 1, key="key-00000009")
    with pytest.raises(rewards.RuleInvalid) as refused:
        rewards.grant_manual(manual, stranger, admin_id=ADMIN_ID)
    assert refused.value.code == "not_this_run"
    assert not RewardEntitlement.objects.exists()


def test_test_run_attempt_grants_nothing():
    quiz = published_quiz()
    link = run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id="a")
    assert link.run.kind == QuizRun.Kind.TEST
    # Forced onto it here: a test run never gets rules through any service.
    RewardRule.objects.create(quiz=quiz, run=link.run, kind="participation", position=1)
    who = Participant.objects.create(run=link.run, anonymous_key_hash="h")
    Attempt.objects.create(
        run=link.run,
        participant=who,
        revision=link.run.current_revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=NOW,
        score=Decimal(1),
        max_score=Decimal(1),
        correct_count=1,
    )
    rewards.refresh(who)
    assert not RewardEntitlement.objects.exists()


def test_planned_run_whose_rewards_conflict_stays_planned():
    quiz = with_rules(published_quiz(), tier(70))
    run = run_schedule.plan(
        quiz,
        starts_at=NOW + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
    )
    # No service lets a planned run with rules lose its scores; forced here.
    QuizRun.objects.filter(pk=run.pk).update(retention_json={"profile": "none"})
    run_schedule.settle(NOW + timedelta(hours=2))
    run_schedule.settle(NOW + timedelta(hours=3))
    run.refresh_from_db()
    assert run.status == QuizRun.Status.SCHEDULED
    event = AuditEvent.objects.get(action="run.open_refused")
    assert event.details_json == {"keys": ["profile"]}
    assert event.entity_id == str(run.id)


def test_admin_cancelled_threshold_is_not_granted_back(graded_type):
    run = a_run(tier(50))
    who = person(run)
    play(run, who, 7)
    rewards.cancel(entitlement(who, "Za 50 %"), "Opisoval", admin_id=ADMIN_ID)
    play(run, who, 10, key="key-00000002")
    assert held(who) == [("Za 50 %", CANCELLED)]
    assert rewards.of_participant(who) == []
    # The same after a regrade.
    photos = photo_run(tier(50), slug="fotky")
    other = person(photos, "j" * 20)
    send_photo(photos, other)
    answer = AttemptAnswer.objects.get()
    grading.save_manual(answer, Decimal(5), admin_id=ADMIN_ID)
    rewards.cancel(entitlement(other, "Za 50 %"), "Opisoval", admin_id=ADMIN_ID)
    grading.save_manual(answer, Decimal(8), admin_id=ADMIN_ID)
    assert held(other) == [("Za 50 %", CANCELLED)]


def test_admin_cancelled_participation_is_not_granted_back():
    run = a_run(kind("participation"))
    who = person(run)
    play(run, who, 0)
    rewards.cancel(entitlement(who, "participation"), "Dvakrát", admin_id=ADMIN_ID)
    play(run, who, 10, key="key-00000002")
    assert held(who) == [("participation", CANCELLED)]


def test_reached_again_after_no_longer_reached_is_granted_again(graded_type):
    run = photo_run(tier(50))
    who = person(run)
    send_photo(run, who)
    answer = AttemptAnswer.objects.get()
    grading.save_manual(answer, Decimal(5), admin_id=ADMIN_ID)
    grading.save_manual(answer, Decimal(0), admin_id=ADMIN_ID)
    assert held(who) == [("Za 50 %", CANCELLED)]
    grading.save_manual(answer, Decimal(5), admin_id=ADMIN_ID)
    assert held(who) == [("Za 50 %", CANCELLED), ("Za 50 %", GRANTED)]


def test_disabling_the_threshold_plugin_is_refused_so_submission_keeps_working():
    from app.kernel import lifecycle

    run = a_run(tier(50), questions=2)
    with pytest.raises(lifecycle.ModuleInUse):
        lifecycle.set_enabled("rewards.threshold", False, actor_type="admin", actor_id=ADMIN_ID)
    who = person(run)
    play(run, who, 2)
    assert held(who) == [("Za 50 %", GRANTED)]


def test_cancelled_top_tier_does_not_grant_the_lower_one_under_highest():
    # Pinned ruling: "highest" only decides between tiers the participant may still hold; an
    # admin's cancellation of the top tier is final for that tier and does not open the lower one.
    run = a_run(tier(70), tier(90))
    who = person(run)
    play(run, who, 10)
    assert held(who) == [("Za 90 %", GRANTED)]
    rewards.cancel(entitlement(who, "Za 90 %"), "Opisoval", admin_id=ADMIN_ID)
    play(run, who, 10, key="key-00000002")
    assert held(who) == [("Za 90 %", CANCELLED)]


def test_an_integrity_error_of_the_submission_key_is_submission_key_used():
    """A key taken by another attempt of a participant is named as what it is."""
    run = a_run(tier(50), questions=2)
    play(run, person(run), 2, key="key-00000001")
    other = attempts.start(run, participant=person(run, "j" * 20))
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(other.attempt.id, other.token, {}, "key-00000001")
    assert error.value.code == "submission_key_used"
    assert Attempt.objects.get(pk=other.attempt.id).status == Attempt.Status.IN_PROGRESS


def test_an_integrity_error_of_another_constraint_is_not_called_a_used_key():
    """TD-051: a unique failure raised by the rewards must not pose as a used submission key."""
    run = a_run(tier(50), questions=2)
    started = attempts.start(run, participant=person(run))
    failure = IntegrityError("UNIQUE constraint failed: other.col")
    with (
        mock.patch.object(rewards, "refresh", side_effect=failure),
        pytest.raises(IntegrityError) as error,
    ):
        attempts.submit(started.attempt.id, started.token, {}, "key-00000001")
    assert error.value is failure
    assert Attempt.objects.get(pk=started.attempt.id).status == Attempt.Status.IN_PROGRESS


def test_refresh_costs_a_fixed_number_of_queries_for_one_participant(django_assert_num_queries):
    run = a_run(tier(50), tier(80), kind("participation"), questions=2)
    who = person(run)
    play(run, who, 2)
    who = Participant.objects.get(pk=who.pk)
    with django_assert_num_queries(5):
        rewards.refresh(who)


def test_reward_threshold_on_average():
    """ADR-0063: 70 % and 90 % average 80 %; the entitlement points at the last attempt."""
    run = a_run(tier(80), results={OFFICIAL_ATTEMPT: "average"})
    who = person(run)
    play(run, who, 7)
    assert held(who) == []  # 70 % alone is below 80 %
    last = play(run, who, 9, key="key-00000002")
    assert held(who) == [("Za 80 %", GRANTED)]
    assert entitlement(who, "Za 80 %").attempt_id == last.id


def test_reward_cancelled_when_the_average_falls_below():
    run = a_run(tier(80), results={OFFICIAL_ATTEMPT: "average"})
    who = person(run)
    play(run, who, 10)
    assert held(who) == [("Za 80 %", GRANTED)]
    play(run, who, 2, key="key-00000002")
    assert held(who) == [("Za 80 %", CANCELLED)]


def test_waiting_average_changes_no_reward():
    run = a_run(tier(50), results={OFFICIAL_ATTEMPT: "average"})
    who = person(run)
    play(run, who, 10)
    pending = play(run, who, 0, key="key-00000002")
    Attempt.objects.filter(pk=pending.pk).update(status=Attempt.Status.PENDING_GRADING)
    rewards.refresh(who)
    assert held(who) == [("Za 50 %", GRANTED)]  # the waiting attempt counts for nothing


def test_best_grants_from_the_submitted_attempt_while_another_waits():
    run = a_run(tier(50), results={OFFICIAL_ATTEMPT: "best"})
    who = person(run)
    first = play(run, who, 6)
    pending = play(run, who, 0, key="key-00000002")
    Attempt.objects.filter(pk=pending.pk).update(status=Attempt.Status.PENDING_GRADING)
    rewards.refresh(who)
    assert results.official_attempt(who) == first
    assert results.kept(who).waiting is True
    assert entitlement(who, "Za 50 %").attempt_id == first.id


def archived(run):
    """The run closes first: a quiz with a run still open cannot be archived."""
    authoring.close_run(run, admin_id=ADMIN_ID)
    Quiz.objects.filter(pk=run.quiz_id).update(archived_at=NOW)
    run.refresh_from_db()
    return run


def test_rewards_refuse_an_archived_quiz():
    run = a_run(kind("participation"), kind("manual"))
    who = person(run)
    play(run, who, 1)
    manual = RewardRule.objects.get(run=run, kind="manual")
    row = RewardEntitlement.objects.get()
    archived(run)
    with pytest.raises(authoring.QuizArchived):
        rewards.grant_manual(manual, who, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        rewards.hand_over(row, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        rewards.cancel(row, "Důvod", admin_id=ADMIN_ID)
    row.refresh_from_db()
    assert row.status == GRANTED and RewardEntitlement.objects.count() == 1


def test_run_changes_refuse_an_archived_quiz():
    """The scoreboard display, a nickname and the access code are changes too."""
    run = a_run()
    who = person(run)
    play(run, who, 1)
    archived(run)
    with pytest.raises(authoring.QuizArchived):
        results.set_display(run, {}, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        participants.rename(who, "Nové", admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        access_codes.set_code(run, "ABCDEFGH", admin_id=ADMIN_ID)
    who.refresh_from_db()
    assert who.display_name != "Nové"
