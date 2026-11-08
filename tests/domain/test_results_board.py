"""AC-06, AC-16, AC-81, AC-82: the scoreboard is a projection of submitted, graded attempts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache

from app.contracts import (
    ARCHIVED_RESULTS,
    OFFICIAL_ATTEMPT,
    REVISION_MODE,
    SCOREBOARD_LIVE_NAMES,
    SCOREBOARD_UNNAMED,
    SCOREBOARD_VISIBILITY,
    TIE_BREAK_POLICY,
)
from app.domain import authoring, results, run_links, run_schedule
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
    run = a_run()
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


def test_merge_refused_with_different_max_and_with_one_revision():
    run = a_run()
    with pytest.raises(results.MergeRefused) as error:
        results.merge(run, admin_id=ADMIN_ID)
    assert error.value.code == "one_revision"
    switch_revision(run, questions_more=1)
    with pytest.raises(results.MergeRefused) as error:
        results.merge(run, admin_id=ADMIN_ID)
    assert error.value.code == "max_differs"
    assert results.revision_mode(run) == "separate"


def test_merge_and_unmerge_audited():
    run = a_run()
    who = person(run, "Ema")
    played(run, who, 0, 0)
    new = switch_revision(run)
    played(run, who, 1, 5, revision=new)
    results.merge(run, admin_id=ADMIN_ID)
    board = public(run)
    assert len(board.tables) == 1 and board.tables[0].rows[0].score == Decimal(1)
    results.unmerge(run, admin_id=ADMIN_ID)
    assert len(public(run).tables) == 2
    assert [e.action for e in AuditEvent.objects.filter(action__startswith="run.revisions_")] == [
        "run.revisions_merged",
        "run.revisions_unmerged",
    ]


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


def test_merged_board_separates_again_when_a_later_revision_has_another_max():
    run = a_run()
    who = person(run, "Ema")
    played(run, who, 1, 0)
    switch_revision(run)
    results.merge(run, admin_id=ADMIN_ID)
    bigger = switch_revision(run, questions_more=1)
    played(run, person(run, "Jan", 1), 2, 5, revision=bigger)
    board = public(run)
    assert len(board.tables) == 3
    assert board.tables[0].max_score == Decimal(2)


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
