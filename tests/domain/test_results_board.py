"""AC-06, AC-16, AC-81, AC-82: the scoreboard is a projection of submitted, graded attempts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.db import IntegrityError, transaction

from app.contracts import (
    ARCHIVED_RESULTS,
    OFFICIAL_ATTEMPT,
    REVISION_MODE,
    SCOREBOARD_LIVE_NAMES,
    SCOREBOARD_UNNAMED,
    SCOREBOARD_VISIBILITY,
    TIE_BREAK_POLICY,
    AttemptFigures,
)
from app.domain import (
    attempts,
    authoring,
    participants,
    results,
    retention,
    run_links,
    run_schedule,
)
from app.domain.models import Attempt, Participant
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_B, add_question, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def a_run(quiz=None, **chosen):
    values = {SCOREBOARD_VISIBILITY: "live"} | chosen
    return authoring.open_run(quiz or published_quiz(), admin_id=ADMIN_ID, results=values)


def person(run, name="", minute=0):
    found = Participant.objects.create(
        run=run, anonymous_key_hash=f"h-{Participant.objects.count()}", display_name=name
    )
    Participant.objects.filter(pk=found.pk).update(created_at=T0 + timedelta(minutes=minute))
    found.refresh_from_db()
    return found


def played(run, who, score, minute=0, *, status=Attempt.Status.SUBMITTED, revision=None):
    attempt = Attempt.objects.create(
        run=run,
        participant=who,
        revision=revision or run.current_revision,
        status=status,
        submitted_at=T0 + timedelta(minutes=minute),
        score=Decimal(score),
        max_score=(revision or run.current_revision).max_score,
    )
    Attempt.objects.filter(pk=attempt.pk).update(started_at=T0 + timedelta(minutes=minute - 1))
    attempt.refresh_from_db()
    return attempt


def public(run, viewer=None, locale="cs"):
    run.refresh_from_db()
    cache.clear()
    return results.board(run, audience="public", locale=locale, viewer=viewer)


def labels(board, table=0):
    return [row.label for row in board.tables[table].rows]


def close(run):
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()


def test_hidden_live_and_after_end():
    hidden = a_run(published_quiz("a"), **{SCOREBOARD_VISIBILITY: "hidden"})
    assert public(hidden).hidden == "hidden" and public(hidden).tables == []
    live = a_run(published_quiz("b"))
    played(live, person(live, "Ema"), 1)
    assert public(live).hidden is None and labels(public(live)) == ["Ema"]
    later = a_run(published_quiz("c"), **{SCOREBOARD_VISIBILITY: "after_end"})
    played(later, person(later, "Ema"), 1)
    assert public(later).hidden == "after_end"
    close(later)
    assert public(later).hidden is None and public(later).final


def test_one_row_per_participant_best_and_first():
    run = a_run(published_quiz(questions=10))
    who = person(run, "Ema")
    played(run, who, 6, 0)
    first_eight = played(run, who, 8, 5)
    played(run, who, 8, 9)
    rows = public(run).tables[0].rows
    assert len(rows) == 1
    assert rows[0].score == Decimal(8)
    assert rows[0].submitted_at == first_eight.submitted_at
    other = a_run(published_quiz("jiny", questions=10), **{OFFICIAL_ATTEMPT: "first"})
    who = person(other, "Ema")
    played(other, who, 6, 0)
    played(other, who, 9, 5)
    assert public(other).tables[0].rows[0].score == Decimal(6)


def test_switched_abandoned_and_unsent_attempts_never_count():
    run = a_run()
    who = person(run, "Ema")
    for status in (Attempt.Status.SWITCHED, Attempt.Status.ABANDONED, Attempt.Status.IN_PROGRESS):
        played(run, who, 1, status=status)
    assert public(run).tables[0].rows == []


def test_attempt_without_participant_is_its_own_anonymous_row():
    run = a_run()
    played(run, None, 1, 0)
    played(run, None, 1, 1)
    played(run, person(run, "Ema", minute=5), 1, 6)
    assert labels(public(run)) == ["Hráč 1", "Hráč 2", "Ema"]


def test_numbers_stay_when_later_rows_arrive():
    run = a_run(**{SCOREBOARD_LIVE_NAMES: "anonymised"})
    first = person(run, "Ema", 0)
    played(run, first, 0, 1)
    mine = public(run, viewer=first).tables[0].rows[0]
    assert mine.label == "Hráč 1" and mine.mine
    played(run, person(run, "Jan", 5), 1, 6)
    board = public(run, viewer=first)
    assert labels(board) == ["Hráč 2", "Hráč 1"]
    assert [row.mine for row in board.tables[0].rows] == [False, True]


def test_anonymised_while_open_named_after_close():
    run = a_run(**{SCOREBOARD_LIVE_NAMES: "anonymised"})
    played(run, person(run, "Ema"), 1)
    assert labels(public(run)) == ["Hráč 1"]
    assert labels(results.board(run, audience="admin", locale="cs")) == ["Ema"]
    close(run)
    assert labels(public(run)) == ["Ema"]


def test_unnamed_anonymous_or_unlisted_with_gap():
    run = a_run(published_quiz(questions=3))
    played(run, person(run, "Ema", 0), 3, 1)
    nameless = played(run, person(run, "", 1), 2, 2)
    played(run, person(run, "Jan", 2), 1, 3)
    assert labels(public(run)) == ["Ema", "Hráč 2", "Jan"]
    results.set_display(run, {SCOREBOARD_UNNAMED: "unlisted"}, admin_id=ADMIN_ID)
    board = public(run)
    assert labels(board) == ["Ema", "Jan"]
    assert [row.rank for row in board.tables[0].rows] == [1, 3]
    assert results.place_of(nameless) == (2, 3)


def test_pending_grading_hides_public_board_not_admin():
    """AC-16: the public board is hidden until grading finishes; the admin still sees it."""
    run = a_run()
    played(run, person(run, "Ema"), 1)
    played(run, person(run, "Jan", 1), 0, status=Attempt.Status.PENDING_GRADING)
    assert public(run).hidden == "pending"
    admin = results.board(run, audience="admin", locale="cs")
    assert admin.hidden is None and labels(admin) == ["Ema"]
    close(run)
    assert not public(run).final


def test_test_attempts_never_counted():
    quiz = published_quiz()
    link = run_links.create(quiz, quiz.revisions.get(), expires_at=None, admin_id=ADMIN_ID)
    played(link.run, None, 1)
    run = a_run(quiz)
    assert public(run).tables[0].rows == []
    assert not results.is_public(link.run)


def test_each_tie_policy_same_order_on_repeated_builds():
    for policy in ("shared", "earlier", "random"):
        run = a_run(published_quiz(f"t-{policy}"), **{TIE_BREAK_POLICY: policy})
        for index in range(6):
            played(run, person(run, f"P{index}", index), 1, 7)
        first = labels(public(run))
        assert all(labels(public(run)) == first for _ in range(3))


def switch_revision(run, questions_more=0):
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    add_question(run.quiz, OPTION_B, question_id=question_id)
    for _ in range(questions_more):
        add_question(run.quiz)
    revision = authoring.publish(
        run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH
    )
    run.refresh_from_db()
    return revision


def test_separate_tables_newest_first_with_own_max():
    run = a_run(**{REVISION_MODE: "separate"})
    old = run.current_revision
    who = person(run, "Ema")
    played(run, who, 1, 0, revision=old)
    new = switch_revision(run, questions_more=1)
    played(run, who, 2, 5, revision=new)
    board = public(run)
    assert [table.revision_no for table in board.tables] == [new.revision_no, old.revision_no]
    assert [table.max_score for table in board.tables] == [Decimal(2), Decimal(1)]
    assert [labels(board, 0), labels(board, 1)] == [["Ema"], ["Ema"]]


def test_latest_only_current_revision():
    run = a_run(**{REVISION_MODE: "latest"})
    played(run, person(run, "Ema"), 1, 0)
    new = switch_revision(run)
    played(run, person(run, "Jan", 1), 1, 5, revision=new)
    board = public(run)
    assert len(board.tables) == 1 and labels(board) == ["Jan"]


def test_percent_is_the_default_for_a_new_run():
    """AC-06: one table by percent unless the admin chose otherwise."""
    run = a_run()
    assert results.of(run)[REVISION_MODE] == "percent"
    assert results.revision_mode(run) == "percent"


def two_maxima_run(**chosen):
    """Revision A of 10 points with Ema 8/10, revision B of 12 points with Jan 9/12."""
    run = a_run(published_quiz(questions=10), **chosen)
    old = run.current_revision
    played(run, person(run, "Jan", 0), 9, 6, revision=switch_revision(run, questions_more=2))
    played(run, person(run, "Ema", 1), 8, 7, revision=old)
    return run


def test_percent_table_ranks_by_share_of_own_maximum():
    """AC-06: revisions with different maxima share one table ranked by percent."""
    run = two_maxima_run()
    board = results.board(run, audience="admin", locale="cs")
    assert len(board.tables) == 1
    table = board.tables[0]
    assert table.revision_no is None and table.max_score is None
    assert [(r.label, r.rank, r.score, r.max_score, r.percent) for r in table.rows] == [
        ("Ema", 1, Decimal(8), Decimal(10), 80),
        ("Jan", 2, Decimal(9), Decimal(12), 75),
    ]
    jan = Attempt.objects.get(participant__display_name="Jan")
    assert results.place_of(jan) == (2, 2)


def test_percent_table_counts_the_best_share_not_the_most_points():
    run = a_run(published_quiz(questions=10))
    who = person(run, "Ema")
    old = run.current_revision
    played(run, who, 9, 5, revision=switch_revision(run, questions_more=2))
    played(run, who, 8, 6, revision=old)
    rows = public(run).tables[0].rows
    assert [(r.score, r.max_score, r.percent) for r in rows] == [(Decimal(8), Decimal(10), 80)]


def test_percent_ties_follow_the_run_tie_rules():
    """Equal percent of different maxima: the second sort, then the shared place (ADR-0026)."""
    run = a_run(published_quiz(questions=4))
    old = run.current_revision
    new = switch_revision(run, questions_more=4)
    played(run, person(run, "Jan", 0), 4, 6, revision=new)  # 4 / 8
    played(run, person(run, "Ema", 1), 2, 7, revision=old)  # 2 / 4, submitted later
    played(run, person(run, "Petr", 2), 1, 6, revision=old)  # 1 / 4
    rows = public(run).tables[0].rows
    assert [(r.label, r.rank, r.percent) for r in rows] == [
        ("Jan", 1, 50),
        ("Ema", 2, 50),
        ("Petr", 3, 25),
    ]
    same = a_run(published_quiz("stejne", questions=4))
    old = same.current_revision
    new = switch_revision(same, questions_more=4)
    played(same, person(same, "Jan", 0), 4, 6, revision=new)
    played(same, person(same, "Ema", 1), 2, 6, revision=old)
    assert [(r.label, r.rank) for r in public(same).tables[0].rows] == [("Jan", 1), ("Ema", 1)]


def test_percent_average_ranks_by_the_average_share():
    run = a_run(published_quiz(questions=10), **{OFFICIAL_ATTEMPT: "average"})
    who = person(run, "Ema")
    old = run.current_revision
    played(run, who, 10, 5, revision=old)
    played(run, who, 6, 6, revision=switch_revision(run, questions_more=2))
    row = public(run).tables[0].rows[0]
    assert row.percent == 75  # (100 % + 50 %) / 2, not 16 of 22 points


def test_admin_switches_a_run_between_the_three_modes_audited():
    """AC-06: the revision mode is a display setting of the run."""
    run = two_maxima_run()
    results.set_display(run, {REVISION_MODE: "separate"}, admin_id=ADMIN_ID)
    board = public(run)
    assert [table.max_score for table in board.tables] == [Decimal(12), Decimal(10)]
    results.set_display(run, {REVISION_MODE: "latest"}, admin_id=ADMIN_ID)
    assert labels(public(run)) == ["Jan"]
    results.set_display(run, {REVISION_MODE: "percent"}, admin_id=ADMIN_ID)
    assert labels(public(run)) == ["Ema", "Jan"]
    changes = AuditEvent.objects.filter(action="run.scoreboard_changed")
    assert [event.details_json for event in changes.order_by("created_at", "pk")] == [
        {REVISION_MODE: "separate"},
        {REVISION_MODE: "latest"},
        {REVISION_MODE: "percent"},
    ]


def test_merge_is_gone():
    assert not hasattr(results, "merge") and not hasattr(results, "MergeRefused")


def test_archived_needs_switch():
    run = a_run()
    played(run, person(run, "Ema"), 1)
    close(run)
    run_schedule.archive(run, admin_id=ADMIN_ID)
    assert public(run).hidden == "archived"
    results.set_display(run, {ARCHIVED_RESULTS: "on"}, admin_id=ADMIN_ID)
    assert public(run).hidden is None


def test_empty_board_and_max_zero_give_percent_zero():
    run = a_run()
    board = public(run)
    assert len(board.tables) == 1 and board.tables[0].rows == []
    attempt = played(run, person(run, "Ema"), 0)
    from app.domain.models import RunRevision

    RunRevision.objects.filter(run=run).update(max_score=0)
    Attempt.objects.filter(pk=attempt.pk).update(max_score=0)
    assert public(run).tables[0].rows[0].percent == 0


def test_percent_is_rounded():
    run = a_run(published_quiz(questions=3))
    played(run, person(run, "Ema"), 2)
    assert public(run).tables[0].rows[0].percent == 67


def test_label_without_nn_and_html_kept_as_text():
    quiz = published_quiz()
    quiz.anonymous_label = {"cs": "<b>Tým</b>"}
    quiz.save()
    run = a_run(quiz)
    played(run, None, 1)
    assert labels(public(run)) == ["<b>Tým</b> 1"]


def test_columns_follow_settings_and_profile():
    run = a_run(scoreboard_show_time="on", scoreboard_show_percent="off")
    assert public(run).columns == ("score", "time")
    detailed = authoring.open_run(
        published_quiz("d"),
        admin_id=ADMIN_ID,
        data={"profile": "detailed"},
        results={SCOREBOARD_VISIBILITY: "live", "scoreboard_show_duration": "on"},
    )
    assert public(detailed).columns == ("score", "percent", "duration")


def test_place_of_hidden_board_is_none():
    run = a_run(**{SCOREBOARD_VISIBILITY: "hidden"})
    assert results.place_of(played(run, person(run, "Ema"), 1)) is None


def test_public_board_cached_for_seconds():
    run = a_run()
    played(run, person(run, "Ema"), 1)
    cache.clear()
    assert labels(results.board(run, audience="public", locale="cs")) == ["Ema"]
    played(run, person(run, "Jan", 1), 1, 1)
    assert labels(results.board(run, audience="public", locale="cs")) == ["Ema"]
    cache.clear()
    assert labels(results.board(run, audience="public", locale="cs")) == ["Ema", "Jan"]


def test_percent_board_stays_one_table_over_three_revisions():
    run = a_run()
    who = person(run, "Ema")
    played(run, who, 1, 0)
    switch_revision(run)
    bigger = switch_revision(run, questions_more=1)
    played(run, person(run, "Jan", 1), 2, 5, revision=bigger)
    board = public(run)
    assert len(board.tables) == 1
    assert [(r.max_score, r.percent) for r in board.tables[0].rows] == [
        (Decimal(1), 100),
        (Decimal(2), 100),
    ]


def test_closed_hidden_board_keeps_polling_so_turning_it_on_shows():
    run = a_run(**{SCOREBOARD_VISIBILITY: "hidden"})
    close(run)
    assert not public(run).final
    results.set_display(run, {SCOREBOARD_VISIBILITY: "live"}, admin_id=ADMIN_ID)
    assert public(run).final


def test_hiding_the_board_drops_the_cached_rows_at_once():
    run = a_run()
    played(run, person(run, "Ema"), 1)
    cache.clear()
    assert labels(results.board(run, audience="public", locale="cs")) == ["Ema"]
    results.set_display(run, {SCOREBOARD_VISIBILITY: "hidden"}, admin_id=ADMIN_ID)
    assert results.board(run, audience="public", locale="cs").hidden == "hidden"


# Kept score (ADR-0063) ---------------------------------------------------------------------


def kept_run(rule):
    return a_run(published_quiz(slug=f"k-{rule}"), **{OFFICIAL_ATTEMPT: rule})


def with_counts(attempt, correct, max_score=None):
    update = {"correct_count": correct}
    if max_score is not None:
        update["max_score"] = Decimal(max_score)
    Attempt.objects.filter(pk=attempt.pk).update(**update)
    attempt.refresh_from_db()
    return attempt


def test_kept_average_figures():
    """AC-174: the average is the component means of the submitted attempts."""
    run = kept_run("average")
    who = person(run, "Ema")
    first = with_counts(played(run, who, 10, 1), 3, 20)
    last = with_counts(played(run, who, 6, 2), 4, 10)
    kept = results.kept(who)
    assert kept.figures == AttemptFigures(
        score=Decimal(8), max_score=Decimal(15), correct=3, questions=len(attempts.items_of(last))
    )
    assert (kept.attempt, kept.count, kept.rule, kept.waiting) == (last, 2, "average", False)
    assert first.pk != last.pk


def test_kept_correct_is_floor_of_the_mean():
    """AC-174: correct is the floor of the mean."""
    run = kept_run("average")
    who = person(run)
    with_counts(played(run, who, 1, 1), 7)
    with_counts(played(run, who, 1, 2), 8)
    assert results.kept(who).figures.correct == 7


def test_kept_questions_is_the_mean_rounded_half_up():
    run = kept_run("average")
    who = person(run)
    one = played(run, who, 1, 1)
    two = played(run, who, 1, 2)
    selected = {
        one.pk: {"items": [{"id": str(n)} for n in range(3)]},
        two.pk: {"items": [{"id": str(n)} for n in range(4)]},
    }
    for pk, value in selected.items():
        Attempt.objects.filter(pk=pk).update(selection_json=value)
    assert results.kept(who).figures.questions == 4  # 3.5 rounds up


def test_kept_waits_for_grading():
    run = kept_run("average")
    who = person(run)
    played(run, who, 5, 1)
    played(run, who, 5, 2, status=Attempt.Status.PENDING_GRADING)
    kept = results.kept(who)
    assert kept.waiting is True
    assert kept.count == 1  # the waiting one counts for nothing
    assert results.official_attempt(who) == kept.attempt


@pytest.mark.parametrize(
    ("rule", "pending_minute", "waiting"),
    [
        ("first", 1, True),
        ("first", 2, False),
        ("last", 2, True),
        ("last", 1, False),
        ("best", 1, True),
        ("best", 2, True),
    ],
)
def test_kept_waiting_by_rule(rule, pending_minute, waiting):
    run = kept_run(rule)
    who = person(run)
    for minute in (1, 2):
        status = Attempt.Status.PENDING_GRADING if minute == pending_minute else None
        played(run, who, 5, minute, status=status or Attempt.Status.SUBMITTED)
    assert results.kept(who).waiting is waiting


def test_kept_is_none_without_attempts():
    run = kept_run("average")
    assert results.kept(person(run)) is None


def test_board_ranks_by_average_with_the_time_of_the_last_attempt():
    """AC-174: the board ranks by the average."""
    run = kept_run("average")
    ema, jan = person(run, "Ema"), person(run, "Jan")
    played(run, ema, 10, 1)
    played(run, ema, 2, 5)
    played(run, jan, 5, 3)
    rows = public(run).tables[0].rows
    by_label = {row.label: row for row in rows}
    assert by_label["Ema"].score == Decimal(6)
    assert by_label["Ema"].submitted_at == T0 + timedelta(minutes=5)
    assert by_label["Ema"].rank == 1 and by_label["Jan"].rank == 2


def test_last_rule_counts_the_latest_attempt():
    """AC-174: last counts the latest submitted attempt."""
    run = kept_run("last")
    ema = person(run, "Ema")
    played(run, ema, 10, 1)
    played(run, ema, 2, 5)
    assert public(run).tables[0].rows[0].score == Decimal(2)


def test_first_and_best_keep_the_old_official_attempt():
    for rule in ("first", "best"):
        run = kept_run(rule)
        who = person(run)
        played(run, who, 4, 1)
        played(run, who, 9, 2)
        kept = results.kept(who)
        assert kept.attempt == results.official_attempt(who)
        assert kept.attempt.score == (Decimal(4) if rule == "first" else Decimal(9))


def test_kept_is_none_with_only_a_waiting_attempt():
    run = kept_run("best")
    who = person(run)
    played(run, who, 5, 1, status=Attempt.Status.PENDING_GRADING)
    assert results.kept(who) is None
    assert results.official_attempt(who) is None


def test_best_ignores_a_waiting_attempt_but_flags_it():
    run = kept_run("best")
    who = person(run)
    submitted = played(run, who, 6, 1)
    played(run, who, 9, 2, status=Attempt.Status.PENDING_GRADING)
    found = results.kept(who)
    assert (found.attempt, found.waiting) == (submitted, True)
    assert results.official_attempt(who) == submitted


def test_kept_last_with_the_same_time_takes_the_greater_id():
    run = kept_run("last")
    who = person(run)
    one = played(run, who, 3, 1)
    two = played(run, who, 4, 1)
    assert one.submitted_at == two.submitted_at  # the tie this test is about
    assert results.kept(who).attempt == max(one, two, key=lambda a: str(a.id))


def test_kept_average_of_a_mean_that_does_not_end():
    run = kept_run("average")
    who = person(run)
    for minute, score in ((1, 1), (2, 1), (3, 2)):
        played(run, who, score, minute)
    assert results.kept(who).figures.score == Decimal("1.3333")


def test_separate_revisions_rank_the_average_of_each_table():
    run = a_run(published_quiz("sep"), **{OFFICIAL_ATTEMPT: "average", REVISION_MODE: "separate"})
    who = person(run, "Ema")
    played(run, who, 10, 1)
    other = switch_revision(run, questions_more=1)
    played(run, who, 2, 2, revision=other)
    played(run, who, 4, 3, revision=other)
    board = public(run)
    scores = sorted(row.score for table in board.tables for row in table.rows)
    assert scores == [Decimal(3), Decimal(10)]  # per table; kept spans both revisions
    assert results.kept(who).figures.score == Decimal("5.3333")


def joined(run, key, minute):
    """Through the path a browser takes, so the participant gets the number a start gives."""
    found = participants.find_or_create(run, key)
    Participant.objects.filter(pk=found.pk).update(created_at=T0 + timedelta(minutes=minute))
    found.refresh_from_db()
    return found


def test_a_label_number_survives_the_erasure_of_an_earlier_participant():
    run = a_run()
    first, second, third = (joined(run, key, minute) for minute, key in enumerate("abc"))
    for minute, who in enumerate((first, second, third)):
        played(run, who, 3 - minute, minute)
    assert labels(public(run)) == ["Hráč 1", "Hráč 2", "Hráč 3"]

    retention.erase([str(first.pk)], admin_id=ADMIN_ID)

    assert labels(public(run)) == ["Hráč 2", "Hráč 3"]
    assert results.participant_numbers(run) == {str(second.pk): 2, str(third.pk): 3}


def test_a_new_participant_takes_the_next_number_after_an_erasure():
    run = a_run()
    first, second = joined(run, "a", 0), joined(run, "b", 1)
    retention.erase([str(first.pk)], admin_id=ADMIN_ID)
    later = joined(run, "c", 2)
    assert (second.number, later.number) == (2, 3)


def test_erasing_the_highest_number_never_gives_it_again():
    run = a_run()
    joined(run, "a", 0)
    highest = joined(run, "b", 1)
    retention.erase([str(highest.pk)], admin_id=ADMIN_ID)
    assert joined(run, "c", 2).number == 3
    run.refresh_from_db()
    assert run.participant_seq == 3


def test_loose_attempts_follow_the_last_participant_number():
    run = a_run()
    loose = played(run, None, 1, 0)
    who = joined(run, "a", 5)
    played(run, who, 2, 5)
    numbers = results.participant_numbers(run)
    assert numbers[str(who.pk)] == 1
    assert numbers[f"a:{loose.pk}"] == 2


def test_two_browsers_in_one_run_never_hold_the_same_number():
    run = a_run()
    joined(run, "a", 0)
    with pytest.raises(IntegrityError), transaction.atomic():
        Participant.objects.create(run=run, anonymous_key_hash="other", number=1)
    other = a_run(published_quiz("jiny"))
    assert joined(other, "a", 0).number == 1  # numbers count per run
