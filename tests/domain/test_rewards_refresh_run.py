"""Rewards follow the counted attempt when it changes without a new attempt (TD-047, ADR-0053).

A changed revision mode of the run, or a switch of an open run to another revision at
publication, can change which attempt counts. The run's entitlements are then recomputed in the
same transaction by the usual rules: only automatic thresholds not handed over are cancelled,
nothing an admin cancelled comes back, and drawn, manual and participation entitlements stay.
"""

from decimal import Decimal
from unittest import mock

import pytest
from django.db import connection
from django.forms.models import model_to_dict
from django.test.utils import CaptureQueriesContext

from app.contracts import REVISION_MODE, REWARD_SOURCE, REWARD_THRESHOLDS, SCOREBOARD_VISIBILITY
from app.domain import (
    attempts,
    authoring,
    draws,
    participants,
    results,
    rewards,
    run_links,
    settings,
)
from app.domain.models import Attempt, Draw, DrawEntry, RewardEntitlement, RewardRule
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, add_question, published_quiz

pytestmark = pytest.mark.django_db
GRANTED = RewardEntitlement.Status.GRANTED
HANDED_OVER = RewardEntitlement.Status.HANDED_OVER
CANCELLED = RewardEntitlement.Status.CANCELLED
Decision = authoring.Decision


def tier(percent):
    return rewards.RuleData(
        kind="threshold",
        threshold_unit="percent",
        threshold_value=Decimal(percent),
        texts={"cs": {"name": f"Za {percent} %", "description": "", "claim": ""}},
    )


def kind(name, **fields):
    texts = {"cs": {"name": name, "description": "", "claim": ""}}
    return rewards.RuleData(kind=name, texts=texts, **fields)


def with_template(quiz, *rules):
    for data in rules:
        rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    return quiz


def a_run(*rules, mode="percent", slug="kviz", **chosen):
    """An open run of a quiz with 10 one-point questions, its rules copied from the template."""
    quiz = with_template(published_quiz(slug, questions=10), *rules)
    return authoring.open_run(quiz, admin_id=ADMIN_ID, results={REVISION_MODE: mode}, **chosen)


def person(run, letter="k"):
    return participants.find_or_create(run, letter * 20)


def play(run, who, right, key):
    """Answers the first `right` questions of the run's current revision correctly."""
    started = attempts.start(run, participant=who)
    questions = attempts.questions_of(started.attempt)
    answers = {
        question["id"]: {"options": [OPTION_A if number < right else OPTION_B]}
        for number, question in enumerate(questions)
    }
    attempts.submit(started.attempt.id, started.token, answers, key)
    return Attempt.objects.get(pk=started.attempt.id)


def switch(run, decision=Decision.LET_FINISH):
    """Publishes revision 2 of 11 points; the open run moves to it unless the admin says stay."""
    add_question(run.quiz)
    revision = authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=decision)
    run.refresh_from_db()
    return revision


def set_mode(run, mode):
    results.set_display(run, {REVISION_MODE: mode}, admin_id=ADMIN_ID)


def held(who):
    """Rule name and status of every entitlement, cancelled ones included."""
    rows = RewardEntitlement.objects.filter(participant=who).select_related("rule")
    return sorted((row.rule.texts_json["cs"]["name"], row.status) for row in rows)


def entitlement(who, name):
    return RewardEntitlement.objects.get(
        participant=who, rule__texts_json__cs__name=name, status__in=[GRANTED, HANDED_OVER]
    )


def test_switching_to_latest_cancels_a_threshold_no_longer_reached():
    run = a_run(tier(70))
    ema = person(run, "e")
    play(run, ema, 8, "key-00000001")  # revision 1: 8 of 10
    switch(run)
    jan = person(run, "j")
    play(run, jan, 9, "key-00000002")  # revision 2: 9 of 11, 81.8 %
    assert held(ema) == [("Za 70 %", GRANTED)]  # percent counts every revision
    set_mode(run, "latest")
    row = RewardEntitlement.objects.get(participant=ema)
    assert (row.status, row.reason, row.changed_by) == (CANCELLED, rewards.NO_LONGER_REACHED, None)
    assert held(jan) == [("Za 70 %", GRANTED)]  # the current revision still counts


def test_participation_and_handed_over_grants_stay():
    run = a_run(
        tier(50),
        tier(70),
        kind("participation"),
        kind("manual"),
        rewards={REWARD_THRESHOLDS: "all"},
    )
    ema = person(run, "e")
    play(run, ema, 8, "key-00000001")
    rewards.hand_over(entitlement(ema, "Za 50 %"), admin_id=ADMIN_ID)
    manual = RewardRule.objects.get(run=run, kind="manual")
    rewards.grant_manual(manual, ema, admin_id=ADMIN_ID)
    switch(run)
    set_mode(run, "latest")
    assert held(ema) == [
        ("Za 50 %", HANDED_OVER),
        ("Za 70 %", CANCELLED),
        ("manual", GRANTED),
        ("participation", GRANTED),
    ]


def test_an_admin_cancelled_grant_is_not_granted_back():
    run = a_run(tier(70))
    cheat, fair = person(run, "c"), person(run, "f")
    play(run, cheat, 8, "key-00000001")
    play(run, fair, 8, "key-00000002")
    rewards.cancel(entitlement(cheat, "Za 70 %"), "Opisoval", admin_id=ADMIN_ID)
    switch(run)
    set_mode(run, "latest")
    assert held(fair) == [("Za 70 %", CANCELLED)]
    set_mode(run, "percent")
    row = RewardEntitlement.objects.get(participant=cheat)
    assert (row.status, row.reason, row.changed_by) == (CANCELLED, "Opisoval", ADMIN_ID)
    # what the recomputation cancelled itself is granted again
    assert held(fair) == [("Za 70 %", CANCELLED), ("Za 70 %", GRANTED)]


def test_draw_history_is_unchanged_by_a_mode_change():
    run = a_run(tier(70), kind("draw", winners=1, alternates=2))
    ema = person(run, "e")
    play(run, ema, 8, "key-00000001")  # only on revision 1
    switch(run)
    for number, letter in enumerate("jk", start=2):
        play(run, person(run, letter), 9, f"key-{number:08d}")
    authoring.close_run(run, admin_id=ADMIN_ID)
    rule = RewardRule.objects.get(run=run, kind="draw")
    draws.draw(rule, admin_id=ADMIN_ID)

    def rows():
        return [
            sorted((str(row.pk), sorted(model_to_dict(row).items())) for row in model.objects.all())
            for model in (Draw, DrawEntry)
        ] + [
            sorted(
                (str(row.pk), row.status, row.reason, row.changed_at)
                for row in RewardEntitlement.objects.filter(source="draw")
            )
        ]

    before = rows()
    assert len(draws.preview(rule).participant_ids) == 3
    set_mode(run, "latest")
    assert rows() == before  # draws, their entries and drawn entitlements, row for row
    assert ("Za 70 %", CANCELLED) in held(ema)  # the recomputation did run
    assert str(ema.id) not in draws.preview(rule).participant_ids  # the next action rebuilds


@pytest.mark.parametrize(
    ("decision", "status"),
    [
        (Decision.LET_FINISH, CANCELLED),
        (Decision.NOTIFY_SWITCH, CANCELLED),
        (Decision.STAY, GRANTED),
    ],
)
def test_a_revision_switch_recomputes(decision, status):
    """Under `latest` a switch to revision 2 leaves revision 1's attempt out; stay keeps it."""
    run = a_run(tier(70), mode="latest")
    ema = person(run, "e")
    play(run, ema, 8, "key-00000001")
    assert held(ema) == [("Za 70 %", GRANTED)]
    switch(run, decision)
    row = RewardEntitlement.objects.get(participant=ema)
    assert row.status == status
    if status == CANCELLED:
        assert (row.reason, row.changed_by) == (rewards.NO_LONGER_REACHED, None)


def test_only_a_changed_mode_or_revision_recomputes():
    run = a_run(tier(70))
    with mock.patch.object(rewards, "refresh_run") as recompute:
        results.set_display(run, {SCOREBOARD_VISIBILITY: "live"}, admin_id=ADMIN_ID)
        assert results.of(run)[SCOREBOARD_VISIBILITY] == "live"  # saved, the mode unchanged
        set_mode(run, "percent")  # the same mode again
        switch(run, Decision.STAY)
        assert recompute.call_count == 0
        set_mode(run, "latest")
        assert recompute.call_count == 1
        switch(run, Decision.LET_FINISH)
        assert recompute.call_count == 2
        set_mode(run, "separate")
        assert recompute.call_count == 3
        switch(run, Decision.LET_FINISH)  # not `latest`: a switch cannot change what counts
        assert recompute.call_count == 3


def test_a_run_without_rules_and_a_test_run_get_nothing():
    run = a_run()
    play(run, person(run), 8, "key-00000001")
    rewards.refresh_run(run)
    quiz = published_quiz("test-run", questions=10)
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    play(link.run, person(link.run), 8, "key-00000002")
    # a test run never gets rules (ADR-0044); one written by hand must still grant nothing
    RewardRule.objects.create(
        quiz=quiz,
        run=link.run,
        position=1,
        kind="threshold",
        threshold_unit="percent",
        threshold_value=Decimal(50),
        texts_json={},
    )
    rewards.refresh_run(link.run)
    assert not RewardEntitlement.objects.exists()


def test_refresh_run_costs_a_fixed_number_of_queries_per_participant(
    django_assert_max_num_queries,
):
    """Three reads for the run, plus three for each participant: the run is not read again."""
    run = a_run(tier(50), tier(80), kind("participation"))
    for number, letter in enumerate("abc"):
        play(run, person(run, letter), 8, f"key-{number:08d}")
    switch(run)
    with django_assert_max_num_queries(3 + 3 * 3):
        rewards.refresh_run(run)


def test_participation_goes_to_an_old_revision_finisher_under_latest():
    """Participation means "took part", not a place: LET_FINISH under `latest` still grants it."""
    run = a_run(tier(70), kind("participation"), mode="latest")
    early = person(run, "e")
    play(run, early, 8, "key-00000001")  # before the switch, then pushed out of `latest`
    late = person(run, "l")
    started = attempts.start(run, participant=late)  # revision 1, still open at the switch
    questions = attempts.questions_of(started.attempt)
    switch(run, Decision.LET_FINISH)
    answers = {q["id"]: {"options": [OPTION_A]} for q in questions}
    attempts.submit(started.attempt.id, started.token, answers, "key-00000002")
    assert held(late) == [("participation", GRANTED)]  # 10/10, but no threshold: not counted
    assert held(early) == [("Za 70 %", CANCELLED), ("participation", GRANTED)]
    rewards.refresh_run(run)
    assert held(late) == [("participation", GRANTED)]  # never taken back


def _queries_of_refresh_run(participants):
    """Queries of `refresh_run` under `percent` when each participant played both revisions."""
    run = a_run(tier(50), tier(80), kind("participation"), slug=f"kviz-{participants}")
    people = [person(run, chr(ord("a") + number)) for number in range(participants)]
    for number, who in enumerate(people):
        play(run, who, 8, f"key-a{participants}-{number:06d}")  # revision 1: a maximum of 10
    switch(run)
    for number, who in enumerate(people):
        play(run, who, 9, f"key-b{participants}-{number:06d}")  # revision 2: a maximum of 11
    with CaptureQueriesContext(connection) as captured:
        rewards.refresh_run(run)
    return len(captured)


def test_refresh_run_queries_grow_at_most_linearly_with_attempts_over_two_revisions():
    """Each participant costs a small bound, also when attempts span revisions of other maxima."""
    per_participant_bound = 8
    few = _queries_of_refresh_run(3)
    many = _queries_of_refresh_run(6)
    assert many - few <= 3 * per_participant_bound
