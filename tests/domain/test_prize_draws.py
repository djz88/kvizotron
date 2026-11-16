"""AC-12, AC-16, AC-92: the prize draw, its alternates and its append-only history.

A draw runs only on the admin's command after the run closed, never while grading waits and never
on a run that keeps nothing. Every action, the first draw, a move-up, a substitute and a redraw,
appends one record; no record is ever changed. The audit names participants by pseudonyms only.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.forms.models import model_to_dict

from app.contracts import OFFICIAL_ATTEMPT, REWARD_SOURCE
from app.domain import (
    attempts,
    authoring,
    draws,
    participants,
    retention,
    rewards,
    run_links,
    settings,
)
from app.domain.models import (
    Attempt,
    Draw,
    DrawEntry,
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
ALGORITHM = "secrets.SystemRandom.sample+sha256"


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def draw_rule(winners=1, alternates=2, min_unit=None, min_value=None):
    return rewards.RuleData(
        kind="draw",
        winners=winners,
        alternates=alternates,
        min_unit=min_unit,
        min_value=None if min_value is None else Decimal(min_value),
        texts={"cs": {"name": "Hlavní cena", "description": "", "claim": ""}},
    )


def open_with(data, questions=10, quiz=None):
    quiz = quiz or published_quiz(questions=questions)
    rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    return run, rewards.rules_of(run)[0]


def play(run, number, right=10, name=""):
    who = participants.find_or_create(run, f"key-{number:016d}")
    if name:
        type(who).objects.filter(pk=who.pk).update(display_name=name, email=f"{name}@example.org")
        who.refresh_from_db()
    started = attempts.start(run, participant=who)
    questions = attempts.questions_of(started.attempt)
    answers = {
        question["id"]: {"options": [OPTION_A if index < right else OPTION_B]}
        for index, question in enumerate(questions)
    }
    attempts.submit(started.attempt.id, started.token, answers, f"submit-{number:010d}")
    return who


def closed(run):
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    return run


def with_players(count, data=None, right=10):
    run, rule = open_with(data or draw_rule())
    people = [play(run, number, right) for number in range(count)]
    closed(run)
    return run, rule, people


def entries(draw):
    return [
        (entry.role, entry.position, entry.participant_id)
        for entry in draw.entries.order_by("role", "position")
    ]


def held(rule):
    return sorted(
        (str(row.participant_id), row.status)
        for row in RewardEntitlement.objects.filter(rule=rule, source="draw")
    )


def refused(reason, action, *args, **kwargs):
    with pytest.raises(draws.DrawRefused) as caught:
        action(*args, **kwargs)
    assert caught.value.reason == reason


def test_refused_while_open_stateless_or_pending(graded_type):
    """AC-09, AC-16: no draw while open, on a run that keeps nothing, or with a photo waiting."""
    run, rule = open_with(draw_rule())
    play(run, 1)
    refused("run_not_closed", draws.draw, rule, admin_id=ADMIN_ID)
    closed(run)
    QuizRun.objects.filter(pk=run.pk).update(retention_json={"profile": "none"})
    refused("stateless", draws.draw, rule, admin_id=ADMIN_ID)
    # A photo still waiting for a person keeps the draw back (AC-16).
    quiz = make_quiz("foto")
    add_graded(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    photo_run, photo_rule = open_with(draw_rule(), quiz=quiz)
    who = participants.find_or_create(photo_run, "f" * 20)
    started = attempts.start(photo_run, participant=who)
    question = attempts.questions_of(started.attempt)[0]["id"]
    attempts.submit(started.attempt.id, started.token, {question: {"image": "a" * 32}}, "key-1")
    assert Attempt.objects.get(pk=started.attempt.id).status == Attempt.Status.PENDING_GRADING
    closed(photo_run)
    refused("grading_pending", draws.draw, photo_rule, admin_id=ADMIN_ID)
    # A rule of another kind is no draw.
    threshold = rewards.RuleData(kind="participation", texts={})
    other = rewards.save_rule(published_quiz("jiny"), threshold, rule=None, admin_id=ADMIN_ID)
    refused("not_a_draw_rule", draws.draw, other, admin_id=ADMIN_ID)
    assert not Draw.objects.exists() and not DrawEntry.objects.exists()


def test_test_attempts_never_eligible():
    """AC-12: attempts made through a test link are excluded from the eligible snapshot."""
    quiz = published_quiz(questions=2)
    run, rule = open_with(draw_rule(), quiz=quiz)
    real = play(run, 1)
    link = run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id="a")
    tester = play(link.run, 2)
    closed(run)
    assert draws.preview(rule).participant_ids == [str(real.id)]
    assert str(tester.id) not in draws.preview(rule).participant_ids
    # A draw rule on a test run is never drawn (test runs get no rules; one forced in is refused).
    forced = RewardRule.objects.create(quiz=quiz, run=link.run, kind="draw", winners=1)
    QuizRun.all_kinds.filter(pk=link.run.pk).update(status=QuizRun.Status.CLOSED)
    refused("not_a_draw_rule", draws.draw, forced, admin_id=ADMIN_ID)


def test_preview_fingerprint_equals_draw_fingerprint():
    run, rule, people = with_players(3)
    snapshot = draws.preview(rule)
    assert snapshot.participant_ids == sorted(str(who.id) for who in people)
    assert draws.preview(rule) == snapshot
    done = draws.draw(rule, admin_id=ADMIN_ID)
    assert done.eligible_set_hash == snapshot.fingerprint
    assert done.eligible_count == 3
    assert done.algorithm == ALGORITHM
    assert len(done.rules_version) == 64
    assert (done.action, done.parent_id, done.admin_id, done.reason) == ("draw", None, ADMIN_ID, "")


def test_minimum_filters_eligible():
    run, rule = open_with(draw_rule(min_unit="percent", min_value="50"))
    low = play(run, 1, right=4)
    exact = play(run, 2, right=5)
    high = play(run, 3, right=10)
    closed(run)
    eligible = draws.preview(rule).participant_ids
    assert eligible == sorted([str(exact.id), str(high.id)])
    assert str(low.id) not in eligible


def test_winners_and_ordered_alternates():
    run, rule, people = with_players(6, draw_rule(winners=2, alternates=3))
    done = draws.draw(rule, admin_id=ADMIN_ID)
    rows = list(done.entries.all())
    winners = sorted(entry.position for entry in rows if entry.role == "winner")
    alternates = sorted(entry.position for entry in rows if entry.role == "alternate")
    assert winners == [1, 2] and alternates == [1, 2, 3]
    assert len({entry.participant_id for entry in rows}) == 5
    assert done.audit_json["count"] == 5 and done.audit_json["requested"] == 5
    standing = draws.standing(rule)
    assert standing.draw == done
    assert [entry.position for entry in standing.winners] == [1, 2]
    assert [entry.position for entry in standing.alternates] == [1, 2, 3]
    # Selection order: winners first, then alternates by rank.
    expected = [entry.pseudonym for entry in standing.winners + standing.alternates]
    assert done.audit_json["selected"] == expected
    assert held(rule) == sorted((str(entry.participant_id), GRANTED) for entry in standing.winners)
    refused("already_drawn", draws.draw, rule, admin_id=ADMIN_ID)


def test_fewer_eligible_draws_everybody():
    run, rule, people = with_players(2, draw_rule(winners=1, alternates=3))
    done = draws.draw(rule, admin_id=ADMIN_ID)
    assert done.audit_json["count"] == 2 and done.audit_json["requested"] == 4
    roles = sorted(entry.role for entry in done.entries.all())
    assert roles == ["alternate", "winner"]
    assert {entry.participant_id for entry in done.entries.all()} == {who.id for who in people}


def test_nobody_eligible_stores_nothing():
    run, rule = open_with(draw_rule(min_unit="points", min_value="5"))
    play(run, 1, right=2)
    closed(run)
    refused("nobody_eligible", draws.draw, rule, admin_id=ADMIN_ID)
    assert not Draw.objects.exists() and not AuditEvent.objects.filter(action__startswith="draw.")


def test_move_up_takes_first_alternate_and_keeps_original_rows():
    run, rule, people = with_players(4, draw_rule(winners=1, alternates=2))
    first = draws.draw(rule, admin_id=ADMIN_ID)
    before = entries(first)
    standing = draws.standing(rule)
    old, alternate = standing.winners[0], standing.alternates[0]
    refused("reason_missing", draws.move_up, rule, old, " ", admin_id=ADMIN_ID)
    moved = draws.move_up(rule, old, "Nepřevzal", admin_id=ADMIN_ID)
    assert (moved.action, moved.parent_id, moved.reason) == ("move_up", first.id, "Nepřevzal")
    assert entries(first) == before
    assert sorted(entries(moved)) == sorted(
        [("out", 1, old.participant_id), ("winner", 1, alternate.participant_id)]
    )
    now = draws.standing(rule)
    assert [entry.participant_id for entry in now.winners] == [alternate.participant_id]
    assert [entry.participant_id for entry in now.alternates] == [
        standing.alternates[1].participant_id
    ]
    assert held(rule) == sorted(
        [(str(old.participant_id), CANCELLED), (str(alternate.participant_id), GRANTED)]
    )
    cancelled = RewardEntitlement.objects.get(status=CANCELLED)
    assert cancelled.reason == "Nepřevzal" and cancelled.changed_by == ADMIN_ID
    # The old winner's entry is no longer a winner of the chain.
    refused("not_drawn", draws.move_up, rule, old, "Znovu", admin_id=ADMIN_ID)
    draws.move_up(rule, now.winners[0], "Také ne", admin_id=ADMIN_ID)
    last = draws.standing(rule).winners[0]
    refused("no_alternate", draws.move_up, rule, last, "x", admin_id=ADMIN_ID)
    assert Draw.objects.count() == 3


def test_move_up_keeps_handed_over():
    run, rule, people = with_players(2, draw_rule(winners=1, alternates=1))
    draws.draw(rule, admin_id=ADMIN_ID)
    winner = draws.standing(rule).winners[0]
    rewards.hand_over(RewardEntitlement.objects.get(), admin_id=ADMIN_ID)
    draws.move_up(rule, winner, "Druhá cena", admin_id=ADMIN_ID)
    assert sorted(status for _who, status in held(rule)) == [GRANTED, HANDED_OVER]


def test_substitute_excludes_everyone_drawn():
    run, rule, people = with_players(4, draw_rule(winners=1, alternates=2))
    first = draws.draw(rule, admin_id=ADMIN_ID)
    drawn = {entry.participant_id for entry in first.entries.all()}
    outside = {who.id for who in people} - drawn
    old = draws.standing(rule).winners[0]
    done = draws.substitute(rule, old, "Odstoupil", admin_id=ADMIN_ID)
    assert (done.action, done.parent_id) == ("substitute", first.id)
    new = [entry for entry in done.entries.all() if entry.role == "winner"]
    assert [entry.participant_id for entry in new] == list(outside)
    assert done.audit_json["requested"] == 1 and done.audit_json["count"] == 1
    standing = draws.standing(rule)
    assert [entry.participant_id for entry in standing.winners] == list(outside)
    assert len(standing.alternates) == 2


def test_substitute_excludes_by_participant_not_by_recomputed_pseudonym():
    # A changed secret key would give every person a new pseudonym; the stored ones then differ.
    run, rule, people = with_players(4, draw_rule(winners=1, alternates=2))
    first = draws.draw(rule, admin_id=ADMIN_ID)
    drawn = {entry.participant_id for entry in first.entries.all()}
    outside = {who.id for who in people} - drawn
    DrawEntry.objects.update(pseudonym="stored-under-an-old-key")
    old = draws.standing(rule).winners[0]
    done = draws.substitute(rule, old, "Odstoupil", admin_id=ADMIN_ID)
    new = [entry for entry in done.entries.all() if entry.role == "winner"]
    assert [entry.participant_id for entry in new] == list(outside)


def test_substitute_still_skips_an_entry_whose_participant_link_is_gone():
    run, rule, people = with_players(3, draw_rule(winners=1, alternates=1))
    draws.draw(rule, admin_id=ADMIN_ID)
    gone = DrawEntry.objects.filter(role="alternate").get()
    DrawEntry.objects.filter(pk=gone.pk).update(participant=None)
    old = draws.standing(rule).winners[0]
    done = draws.substitute(rule, old, "Odstoupil", admin_id=ADMIN_ID)
    new = [entry for entry in done.entries.all() if entry.role == "winner"]
    assert len(new) == 1
    assert new[0].pseudonym != gone.pseudonym and new[0].pseudonym != old.pseudonym


def test_substitute_with_nobody_left_refused():
    run, rule, people = with_players(3, draw_rule(winners=1, alternates=2))
    draws.draw(rule, admin_id=ADMIN_ID)
    winner = draws.standing(rule).winners[0]
    refused("nobody_left", draws.substitute, rule, winner, "Nikdo", admin_id=ADMIN_ID)
    assert Draw.objects.count() == 1
    assert held(rule) == [(str(winner.participant_id), GRANTED)]


def test_redraw_supersedes_and_keeps_handed_over():
    run, rule, people = with_players(5, draw_rule(winners=2, alternates=0))
    refused("not_drawn", draws.redraw, rule, "Chyba", admin_id=ADMIN_ID)
    first = draws.draw(rule, admin_id=ADMIN_ID)
    kept, dropped = draws.standing(rule).winners
    handed = RewardEntitlement.objects.get(participant_id=kept.participant_id)
    rewards.hand_over(handed, admin_id=ADMIN_ID)
    again = draws.redraw(rule, "Chybná pravidla", admin_id=ADMIN_ID)
    assert (again.action, again.parent_id, again.reason) == ("redraw", first.id, "Chybná pravidla")
    standing = draws.standing(rule)
    assert standing.draw == again
    assert [row.id for row in standing.history] == [first.id, again.id]
    handed.refresh_from_db()
    assert handed.status == HANDED_OVER
    # The superseded winner's granted entitlement is cancelled, even if the redraw picks them again.
    old = RewardEntitlement.objects.get(
        participant_id=dropped.participant_id, created_at__lte=again.created_at, status=CANCELLED
    )
    assert (old.reason, old.changed_by) == ("Chybná pravidla", ADMIN_ID)
    # Every new winner holds exactly one active entitlement of the rule.
    for entry in standing.winners:
        active = RewardEntitlement.objects.filter(
            rule=rule, participant_id=entry.participant_id
        ).exclude(status=CANCELLED)
        assert active.count() == 1
    assert len(standing.winners) == 2


def test_reason_required_for_repeats():
    run, rule, people = with_players(4)
    draws.draw(rule, admin_id=ADMIN_ID)
    winner = draws.standing(rule).winners[0]
    for action, args in (
        (draws.redraw, (rule, "")),
        (draws.move_up, (rule, winner, "   ")),
        (draws.substitute, (rule, winner, "x" * 201)),
    ):
        refused("reason_missing", action, *args, admin_id=ADMIN_ID)
    assert Draw.objects.count() == 1


def test_draw_rows_never_updated():
    run, rule, people = with_players(6, draw_rule(winners=1, alternates=2))
    draws.draw(rule, admin_id=ADMIN_ID)

    def rows():
        return (
            sorted((str(row.pk), sorted(model_to_dict(row).items())) for row in Draw.objects.all()),
            sorted(
                (str(row.pk), sorted(model_to_dict(row).items())) for row in DrawEntry.objects.all()
            ),
        )

    seen = rows()
    draws.move_up(rule, draws.standing(rule).winners[0], "Nepřevzal", admin_id=ADMIN_ID)
    draws.substitute(rule, draws.standing(rule).winners[0], "Odstoupil", admin_id=ADMIN_ID)
    draws.set_public(rule, True, admin_id=ADMIN_ID)
    draws.redraw(rule, "Znovu", admin_id=ADMIN_ID)
    now = rows()
    for found in (0, 1):
        old = dict(seen[found])
        assert {key: dict(now[found])[key] for key in old} == old
    assert Draw.objects.count() == 4
    rule.refresh_from_db()
    assert rule.winners_public


def test_audit_has_pseudonyms_not_names():
    """AC-12: each draw is audited, with pseudonyms instead of names."""
    run, rule = open_with(draw_rule(winners=1, alternates=1))
    people = [play(run, number, name=f"hrac{number}") for number in range(3)]
    closed(run)
    done = draws.draw(rule, admin_id=ADMIN_ID)
    event = AuditEvent.objects.get(action="draw.draw")
    assert (event.entity_type, event.entity_id, event.actor_id) == ("run", str(run.id), ADMIN_ID)
    text = str(event.details_json) + str(done.audit_json)
    for who in people:
        assert who.display_name not in text and who.email not in text
        assert str(who.id) not in text
    pseudonyms = [entry.pseudonym for entry in draws.standing(rule).winners]
    pseudonyms += [entry.pseudonym for entry in draws.standing(rule).alternates]
    assert done.audit_json["selected"] == pseudonyms
    assert event.details_json["selected"] == pseudonyms
    assert all(len(name) == 64 for name in pseudonyms)


def drawn_with_minimum(count, alternates):
    run, rule = open_with(
        draw_rule(winners=1, alternates=alternates, min_unit="points", min_value="5")
    )
    for number in range(count):
        play(run, number)
    closed(run)
    draws.draw(rule, admin_id=ADMIN_ID)
    return rule, draws.standing(rule)


def no_longer_eligible(entry):
    """As a regrade below the minimum would leave it."""
    Attempt.objects.filter(participant_id=entry.participant_id).update(score=Decimal(0))


def test_move_up_passes_over_alternate_no_longer_eligible():
    rule, standing = drawn_with_minimum(4, alternates=2)
    first, second = standing.alternates
    no_longer_eligible(first)
    moved = draws.move_up(rule, standing.winners[0], "Nepřevzal", admin_id=ADMIN_ID)
    assert moved.eligible_count == 3
    assert [entry.participant_id for entry in draws.standing(rule).winners] == [
        second.participant_id
    ]
    assert [entry.id for entry in draws.standing(rule).alternates] == [first.id]
    assert not moved.entries.filter(participant_id=first.participant_id).exists()


def test_move_up_with_no_alternate_eligible_stores_nothing():
    rule, standing = drawn_with_minimum(3, alternates=2)
    for entry in standing.alternates:
        no_longer_eligible(entry)
    refused("no_alternate", draws.move_up, rule, standing.winners[0], "x", admin_id=ADMIN_ID)
    assert Draw.objects.count() == 1 and DrawEntry.objects.count() == 3
    assert held(rule) == [(str(standing.winners[0].participant_id), GRANTED)]


def test_move_up_passes_over_alternate_without_participant():
    rule, standing = drawn_with_minimum(3, alternates=2)
    first, second = standing.alternates
    DrawEntry.objects.filter(pk=first.pk).update(participant=None)  # as D3 would leave it
    draws.move_up(rule, standing.winners[0], "Nepřevzal", admin_id=ADMIN_ID)
    now = draws.standing(rule)
    assert [entry.participant_id for entry in now.winners] == [second.participant_id]
    assert [entry.id for entry in now.alternates] == [first.id]


def test_refusal_reads_the_checks_of_the_draw(graded_type):
    """What the draw page says before the admin presses the button; nothing is stored."""
    run, rule = open_with(draw_rule())
    play(run, 1)
    assert draws.refusal(rule) == "run_not_closed"
    closed(run)
    assert draws.refusal(rule) is None
    QuizRun.objects.filter(pk=run.pk).update(retention_json={"profile": "none"})
    assert draws.refusal(rule) == "stateless"
    quiz = make_quiz("foto")
    add_graded(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    photo_run, photo_rule = open_with(draw_rule(), quiz=quiz)
    who = participants.find_or_create(photo_run, "f" * 20)
    started = attempts.start(photo_run, participant=who)
    question = attempts.questions_of(started.attempt)[0]["id"]
    attempts.submit(started.attempt.id, started.token, {question: {"image": "a" * 32}}, "key-1")
    closed(photo_run)
    assert draws.refusal(photo_rule) == "grading_pending"
    threshold = rewards.RuleData(kind="participation", texts={})
    other = rewards.save_rule(published_quiz("jiny"), threshold, rule=None, admin_id=ADMIN_ID)
    assert draws.refusal(other) == "not_a_draw_rule"
    assert not Draw.objects.exists()


def test_standing_queries_do_not_grow_with_winners_and_history():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def queries(winners, moves):
        run, rule = open_with(
            draw_rule(winners, moves + 1), quiz=published_quiz(f"q{winners}", questions=10)
        )
        for number in range(winners + moves + 2):
            play(run, winners * 100 + number)
        closed(run)
        draws.draw(rule, admin_id=ADMIN_ID)
        for _ in range(moves):
            draws.move_up(rule, draws.standing(rule).winners[0], "Odstoupil", admin_id=ADMIN_ID)
        with CaptureQueriesContext(connection) as captured:
            current = draws.standing(rule)
            rewards.public_winners(run, "cs")
            for entry in current.winners:
                entry.participant  # noqa: B018
        return len(captured)

    assert queries(1, 1) == queries(4, 3)


def chain_pseudonyms(rows):
    return [entry.pseudonym for entry in rows]


def test_standing_after_a_redraw_comes_only_from_the_redraw():
    run, rule, people = with_players(6, draw_rule(winners=1, alternates=2))
    draws.draw(rule, admin_id=ADMIN_ID)
    draws.move_up(rule, draws.standing(rule).winners[0], "Odstoupil", admin_id=ADMIN_ID)
    again = draws.redraw(rule, "Chyba", admin_id=ADMIN_ID)
    current = draws.standing(rule)
    fresh = list(again.entries.order_by("role", "position"))
    assert sorted(chain_pseudonyms(current.winners + current.alternates)) == sorted(
        chain_pseudonyms(fresh)
    )
    assert len(current.winners) == 1 and len(current.alternates) == 2
    assert current.chain == {again.id}
    assert len(current.history) == 3


def test_substitute_after_a_redraw_excludes_only_the_current_chain():
    # Pinned ruling: someone drawn only in the superseded chain may be drawn as a substitute.
    run, rule, people = with_players(3, draw_rule(winners=1, alternates=0))
    first = draws.draw(rule, admin_id=ADMIN_ID)
    old = first.entries.get().participant_id
    while True:
        again = draws.redraw(rule, "Znovu", admin_id=ADMIN_ID)
        now = again.entries.get().participant_id
        if now != old:
            break
    outside = {who.id for who in people} - {old, now}
    # Only the superseded winner and one never drawn are left for the substitute.
    done = draws.substitute(rule, draws.standing(rule).winners[0], "Odstoupil", admin_id=ADMIN_ID)
    chosen = done.entries.get(role="winner").participant_id
    assert chosen in outside | {old}
    assert chosen != now


def test_draw_works_on_an_archived_run():
    from app.domain import run_schedule

    run, rule, _people = with_players(3, draw_rule(winners=1, alternates=1))
    run_schedule.archive(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.status == QuizRun.Status.ARCHIVED
    assert draws.refusal(rule) is None
    done = draws.draw(rule, admin_id=ADMIN_ID)
    assert Draw.objects.filter(pk=done.pk).exists()


def test_every_draw_action_is_refused_on_a_run_whose_data_were_deleted():
    """AC-12, AC-111: the run is archived but keeps nothing, so no action may add a record."""
    run, rule, _people = with_players(4, draw_rule(winners=1, alternates=2))
    draws.draw(rule, admin_id=ADMIN_ID)
    winner = draws.standing(rule).winners[0]
    never_drawn_run, never_drawn_rule = open_with(draw_rule(), quiz=published_quiz("druhy"))
    play(never_drawn_run, 7)
    closed(never_drawn_run)
    for deleted in (run, never_drawn_run):
        assert retention.purge_run(deleted, trigger="manual", admin_id=ADMIN_ID) is True
    drawn_before = list(Draw.objects.order_by("pk").values_list("pk", flat=True))
    held_before = held(rule)
    assert QuizRun.objects.get(pk=run.pk).status == QuizRun.Status.ARCHIVED

    assert draws.refusal(rule) == "stateless"
    assert draws.refusal(never_drawn_rule) == "stateless"
    refused("stateless", draws.draw, never_drawn_rule, admin_id=ADMIN_ID)
    refused("stateless", draws.draw, rule, admin_id=ADMIN_ID)
    refused("stateless", draws.redraw, rule, "Znovu", admin_id=ADMIN_ID)
    refused("stateless", draws.move_up, rule, winner, "Nepřevzal", admin_id=ADMIN_ID)
    refused("stateless", draws.substitute, rule, winner, "Nepřevzal", admin_id=ADMIN_ID)

    assert list(Draw.objects.order_by("pk").values_list("pk", flat=True)) == drawn_before
    assert held(rule) == held_before


def test_draw_minimum_on_average():
    """ADR-0063: 50 % and 100 % average 75 %, so a 70 % minimum passes; 40 % and 60 % do not."""
    quiz = published_quiz(questions=10)
    rewards.save_rule(
        quiz, draw_rule(min_unit="percent", min_value="70"), rule=None, admin_id=ADMIN_ID
    )
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={OFFICIAL_ATTEMPT: "average"})
    rule = rewards.rules_of(run)[0]
    high = play(run, 1, right=5)
    low = play(run, 2, right=4)
    for number, right in ((1, 10), (2, 6)):
        who = participants.find_or_create(run, f"key-{number:016d}")
        started = attempts.start(run, participant=who)
        questions = attempts.questions_of(started.attempt)
        answers = {
            q["id"]: {"options": [OPTION_A if i < right else OPTION_B]}
            for i, q in enumerate(questions)
        }
        attempts.submit(started.attempt.id, started.token, answers, f"again-{number:010d}")
    closed(run)
    assert draws.preview(rule).participant_ids == [str(high.id)]
    assert str(low.id) not in draws.preview(rule).participant_ids


def test_draw_counts_the_submitted_attempt_while_another_waits():
    run, rule = open_with(draw_rule(min_unit="percent", min_value="50"))
    who = play(run, 1, right=6)
    Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=Attempt.Status.PENDING_GRADING,
        submitted_at=NOW,
        score=Decimal(0),
        max_score=run.current_revision.max_score,
    )
    closed(run)
    assert draws.preview(rule).participant_ids == [str(who.id)]


def test_every_draw_action_refuses_an_archived_quiz():
    run, rule, _ = with_players(3, draw_rule(winners=1, alternates=1))
    first = draws.draw(rule, admin_id=ADMIN_ID)
    winner = first.entries.get(role="winner")
    Quiz.objects.filter(pk=run.quiz_id).update(archived_at=NOW)
    with pytest.raises(authoring.QuizArchived):
        draws.draw(rule, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        draws.redraw(rule, "Důvod", admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        draws.move_up(rule, winner, "Důvod", admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        draws.substitute(rule, winner, "Důvod", admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        draws.set_public(rule, True, admin_id=ADMIN_ID)
    assert Draw.objects.count() == 1
