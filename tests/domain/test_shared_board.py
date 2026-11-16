"""AC-177: several runs of a quiz share one public scoreboard on the main run (ADR-0065)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache

from app.contracts import (
    ARCHIVED_RESULTS,
    REVISION_MODE,
    SCOREBOARD_LIVE_NAMES,
    SCOREBOARD_VISIBILITY,
)
from app.domain import authoring, results, run_links, run_schedule
from app.domain.models import Attempt, Participant, QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_B, add_question, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def a_run(quiz, **chosen):
    values = {SCOREBOARD_VISIBILITY: "live"} | chosen
    return authoring.open_run(quiz, admin_id=ADMIN_ID, results=values)


def person(run, name="", minute=0):
    found = Participant.objects.create(
        run=run, anonymous_key_hash=f"h-{Participant.objects.count()}", display_name=name
    )
    Participant.objects.filter(pk=found.pk).update(created_at=T0 + timedelta(minutes=minute))
    found.refresh_from_db()
    return found


def played(run, who, score, minute=0, *, status=Attempt.Status.SUBMITTED, revision=None):
    revision = revision or run.current_revision
    attempt = Attempt.objects.create(
        run=run,
        participant=who,
        revision=revision,
        status=status,
        submitted_at=T0 + timedelta(minutes=minute),
        score=Decimal(score),
        max_score=revision.max_score,
    )
    Attempt.objects.filter(pk=attempt.pk).update(started_at=T0 + timedelta(minutes=minute - 1))
    attempt.refresh_from_db()
    return attempt


def public(run, locale="cs"):
    run.refresh_from_db()
    cache.clear()
    return results.board(run, audience="public", locale=locale)


def cached(run, locale="cs"):
    """The public board as a page gets it, without clearing the cache first."""
    return results.board(run, audience="public", locale=locale)


def labels(board, table=0):
    return [row.label for row in board.tables[table].rows]


def close(run):
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()


def republish(quiz, questions_more=0):
    """A new revision; a run still open switches to it."""
    question_id = (
        quiz.revisions.filter(status="PUBLISHED").get().snapshot_json["questions"][0]["id"]
    )
    add_question(quiz, OPTION_B, question_id=question_id)
    for _ in range(questions_more):
        add_question(quiz)
    return authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)


def two_runs(**chosen):
    """Run 1 of 10 points with Ema 8/10 (closed), run 2 of 12 points with Jan 9/12 (open)."""
    quiz = published_quiz(questions=10)
    first = a_run(quiz, **chosen)
    played(first, person(first, "Ema", 0), 8, 1)
    close(first)
    republish(quiz, questions_more=2)
    second = a_run(quiz, **chosen)
    played(second, person(second, "Jan", 2), 9, 3)
    return first, second


def test_shared_board_ranks_all_runs_by_percent():
    """AC-177: the main run shows the runs together, ranked by percent of each own maximum."""
    first, second = two_runs()
    results.share_board(second, [first], admin_id=ADMIN_ID)
    admin = results.board(second, audience="admin", locale="cs")
    for board, names in ((public(second), ("Ema", "Jan")), (admin, ("Běh 1 · Ema", "Běh 2 · Jan"))):
        assert board.hidden is None and len(board.tables) == 1
        table = board.tables[0]
        assert table.revision_no is None and table.max_score is None
        assert [(r.label, r.rank, r.score, r.max_score, r.percent) for r in table.rows] == [
            (names[0], 1, Decimal(8), Decimal(10), 80),
            (names[1], 2, Decimal(9), Decimal(12), 75),
        ]
    assert [run.run_no for run in results.shared_runs(second)] == [1, 2]
    assert results.shared_runs(first) == [first]


def test_shared_runs_of_a_run_without_members_is_itself():
    first, second = two_runs()
    assert results.shared_runs(second) == [second]


def test_member_with_latest_mode_contributes_only_its_current_revision():
    quiz = published_quiz(questions=2)
    first = a_run(quiz, **{REVISION_MODE: "latest"})
    played(first, person(first, "Ema", 0), 2, 1)
    new = republish(quiz)
    first.refresh_from_db()
    assert first.current_revision_id == new.id
    played(first, person(first, "Jan", 1), 1, 2, revision=new)
    close(first)
    second = a_run(quiz)
    played(second, person(second, "Petr", 2), 2, 3)
    results.share_board(second, [first], admin_id=ADMIN_ID)
    assert labels(public(second)) == ["Petr", "Jan"]


def test_each_run_picks_its_counted_attempt_by_its_own_rule():
    quiz = published_quiz(questions=10)
    first = a_run(quiz, official_attempt="first")
    ema = person(first, "Ema", 0)
    played(first, ema, 3, 1)
    played(first, ema, 9, 2)
    close(first)
    second = a_run(quiz, official_attempt="best")
    jan = person(second, "Jan", 3)
    played(second, jan, 2, 4)
    played(second, jan, 5, 5)
    results.share_board(second, [first], admin_id=ADMIN_ID)
    rows = public(second).tables[0].rows
    assert [(r.label, r.score) for r in rows] == [("Jan", Decimal(5)), ("Ema", Decimal(3))]


def test_pending_grading_in_a_member_holds_the_shared_board():
    first, second = two_runs()
    played(first, person(first, "Petr", 5), 0, 6, status=Attempt.Status.PENDING_GRADING)
    assert public(second).hidden is None
    results.share_board(second, [first], admin_id=ADMIN_ID)
    assert public(second).hidden == "pending"
    admin = results.board(second, audience="admin", locale="cs")
    assert admin.hidden is None and labels(admin) == ["Běh 1 · Ema", "Běh 2 · Jan"]
    close(second)
    assert not public(second).final


def test_shared_board_is_final_only_when_every_run_ended():
    quiz = published_quiz()
    first = a_run(quiz)
    close(first)
    second = a_run(quiz)
    results.share_board(first, [second], admin_id=ADMIN_ID)
    assert not public(first).final
    close(second)
    assert public(first).final


def test_live_names_stay_anonymised_while_a_linked_run_is_open():
    quiz = published_quiz()
    first = a_run(quiz, **{SCOREBOARD_LIVE_NAMES: "anonymised"})
    played(first, person(first, "Ema", 0), 1, 1)
    close(first)
    second = a_run(quiz)
    results.share_board(first, [second], admin_id=ADMIN_ID)
    assert labels(public(first)) == ["Běh 1 · Hráč 1"]
    close(second)
    assert labels(public(first)) == ["Ema"]


def test_anonymous_rows_show_the_run_number_when_shared():
    quiz = published_quiz()
    first = a_run(quiz)
    played(first, person(first, "", 0), 1, 1)
    close(first)
    second = a_run(quiz)
    played(second, person(second, "", 2), 1, 3)
    played(second, None, 0, 4)
    assert labels(public(second)) == ["Hráč 1", "Hráč 2"]
    results.share_board(second, [first], admin_id=ADMIN_ID)
    assert labels(public(second)) == ["Běh 1 · Hráč 1", "Běh 2 · Hráč 1", "Běh 2 · Hráč 2"]
    assert labels(public(second, "uk")) == [
        "Запуск 1 · Гравець 1",
        "Запуск 2 · Гравець 1",
        "Запуск 2 · Гравець 2",
    ]


def test_split_restores_the_main_board_at_once():
    first, second = two_runs()
    cache.clear()
    assert labels(cached(second)) == ["Jan"]
    results.share_board(second, [first], admin_id=ADMIN_ID)
    assert labels(cached(second)) == ["Ema", "Jan"]
    results.split_board(second, admin_id=ADMIN_ID)
    assert labels(cached(second)) == ["Jan"]
    first.refresh_from_db()
    assert first.board_main_id is None and results.shared_runs(second) == [second]


def test_dropping_a_member_board_drops_the_main_board():
    first, second = two_runs()
    results.share_board(second, [first], admin_id=ADMIN_ID)
    cache.clear()
    assert labels(cached(second)) == ["Ema", "Jan"]
    played(first, person(first, "Petr", 6), 10, 7)
    first.refresh_from_db()
    results.clear_board_cache(first.id)
    assert labels(cached(second)) == ["Petr", "Ema", "Jan"]


def test_sharing_again_replaces_the_members_and_is_audited():
    quiz = published_quiz()
    runs = []
    for _ in range(3):
        runs.append(a_run(quiz))
        close(runs[-1])
    first, second, third = runs
    results.share_board(third, [first, second], admin_id=ADMIN_ID)
    results.share_board(third, [second], admin_id=ADMIN_ID)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.board_main_id is None and second.board_main_id == third.id
    results.split_board(third, admin_id=ADMIN_ID)
    events = AuditEvent.objects.filter(action__startswith="run.board_").order_by("id")
    assert [(e.action, e.entity_id, e.details_json) for e in events] == [
        ("run.board_combined", str(third.id), {"main": 3, "members": [1, 2]}),
        ("run.board_combined", str(third.id), {"main": 3, "members": [2]}),
        ("run.board_split", str(third.id), {"main": 3, "members": [2]}),
    ]


def _runs_for_refusals():
    quiz = published_quiz()
    runs = []
    for _ in range(3):
        runs.append(a_run(quiz))
        close(runs[-1])
    other = a_run(published_quiz("jiny"))
    link = run_links.create(quiz, quiz.revisions.get(), expires_at=None, admin_id=ADMIN_ID)
    return runs, other, link.run


def _too_few(runs, other, test):
    return runs[2], [runs[2]]


def _other_quiz(runs, other, test):
    return runs[2], [runs[0], other]


def _test_member(runs, other, test):
    return runs[2], [runs[0], test]


def _test_main(runs, other, test):
    return test, [runs[0]]


def _member_elsewhere(runs, other, test):
    results.share_board(runs[1], [runs[0]], admin_id=ADMIN_ID)
    return runs[2], [runs[0]]


def _member_is_a_main(runs, other, test):
    results.share_board(runs[1], [runs[0]], admin_id=ADMIN_ID)
    return runs[2], [runs[1]]


def _main_is_member(runs, other, test):
    results.share_board(runs[1], [runs[0]], admin_id=ADMIN_ID)
    return runs[0], [runs[2]]


@pytest.mark.parametrize(
    ("build", "code"),
    [
        (_too_few, "too_few"),
        (_other_quiz, "other_quiz"),
        (_test_member, "test_run"),
        (_test_main, "test_run"),
        (_member_elsewhere, "already_shared"),
        (_member_is_a_main, "already_shared"),
        (_main_is_member, "main_is_member"),
    ],
)
def test_share_refuses(build, code):
    runs, other, test = _runs_for_refusals()
    main, members = build(runs, other, test)
    before = dict(QuizRun.all_kinds.values_list("pk", "board_main_id"))
    audited = AuditEvent.objects.filter(action="run.board_combined").count()
    with pytest.raises(results.ShareRefused) as refused:
        results.share_board(main, members, admin_id=ADMIN_ID)
    assert refused.value.code == code
    assert dict(QuizRun.all_kinds.values_list("pk", "board_main_id")) == before
    assert AuditEvent.objects.filter(action="run.board_combined").count() == audited


def test_archived_quiz_refuses_sharing():
    quiz = published_quiz()
    first = a_run(quiz)
    close(first)
    second = a_run(quiz)
    results.share_board(second, [first], admin_id=ADMIN_ID)
    close(second)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        results.share_board(second, [first], admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        results.split_board(second, admin_id=ADMIN_ID)
    first.refresh_from_db()
    assert first.board_main_id == second.id


def test_member_keeps_its_own_board():
    first, second = two_runs()
    results.share_board(second, [first], admin_id=ADMIN_ID)
    assert labels(public(first)) == ["Ema"]
    assert labels(results.board(first, audience="admin", locale="cs")) == ["Ema"]


def test_place_of_stays_within_the_own_run():
    first, second = two_runs()
    results.share_board(second, [first], admin_id=ADMIN_ID)
    jan = Attempt.objects.get(participant__display_name="Jan")
    ema = Attempt.objects.get(participant__display_name="Ema")
    assert [r.rank for r in public(second).tables[0].rows] == [1, 2]
    assert results.place_of(jan) == (1, 1)
    assert results.place_of(ema) == (1, 1)


def test_a_member_with_deleted_data_adds_nothing():
    first, second = two_runs()
    results.share_board(second, [first], admin_id=ADMIN_ID)
    Attempt.objects.filter(run=first).delete()
    Participant.objects.filter(run=first).delete()
    QuizRun.objects.filter(pk=first.pk).update(data_deleted_at=T0)
    assert labels(public(second)) == ["Jan"]


def test_admin_board_of_a_main_run_names_the_run_of_every_row():
    """The admin sees which run each named row comes from; anonymous labels stay as they are."""
    first, second = two_runs()
    played(second, person(second, "", 4), 1, 5)
    results.share_board(second, [first], admin_id=ADMIN_ID)
    admin = results.board(second, audience="admin", locale="cs")
    assert labels(admin) == ["Běh 1 · Ema", "Běh 2 · Jan", "Běh 2 · Hráč 2"]
    assert labels(results.board(first, audience="admin", locale="cs")) == ["Ema"]


@pytest.mark.parametrize(
    ("archived_results", "public_names"), [("off", ["Jan"]), ("on", ["Ema", "Jan"])]
)
def test_archived_member_rows_show_publicly_only_when_its_archived_results_are_public(
    archived_results, public_names
):
    """AC-177: an archived member run's rows show publicly only when its archived results are."""
    first, second = two_runs(**{ARCHIVED_RESULTS: archived_results})
    results.share_board(second, [first], admin_id=ADMIN_ID)
    run_schedule.archive(first, admin_id=ADMIN_ID)
    assert labels(public(second)) == public_names
    admin = results.board(second, audience="admin", locale="cs")
    assert labels(admin) == ["Běh 1 · Ema", "Běh 2 · Jan"]
    first.refresh_from_db()
    assert first.board_main_id == second.id


def test_pending_grading_in_a_member_makes_the_main_board_not_public():
    first, second = two_runs()
    results.share_board(second, [first], admin_id=ADMIN_ID)
    second.refresh_from_db()
    assert results.is_public(second)
    assert second in results.public_runs(second.quiz)
    played(first, person(first, "Petr", 5), 0, 6, status=Attempt.Status.PENDING_GRADING)
    assert not results.is_public(second)
    assert second not in results.public_runs(second.quiz)
