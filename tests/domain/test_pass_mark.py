"""Pass mark, judged (test add-ons): computed from the run's mark, never stored."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import OFFICIAL_ATTEMPT, PASS_MARK, SCOREBOARD_VISIBILITY
from app.domain import authoring, participants, results, results_export, run_stats, settings
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def a_run(mark="70", slug="kviz", **chosen):
    values = {SCOREBOARD_VISIBILITY: "live", PASS_MARK: mark} | chosen
    return authoring.open_run(published_quiz(slug, questions=10), admin_id=ADMIN_ID, results=values)


def person(run, name=""):
    return Participant.objects.create(
        run=run, anonymous_key_hash=f"h{Participant.objects.count()}", display_name=name
    )


def played(run, who, score, minute=0, status=Attempt.Status.SUBMITTED, max_score=None):
    return Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=status,
        submitted_at=T0 + timedelta(minutes=minute),
        score=Decimal(score),
        max_score=Decimal(max_score) if max_score is not None else run.current_revision.max_score,
    )


def test_attempt_passed_against_run_mark():
    """AC-172: an attempt passes on its own percentage against the run's pass mark."""
    run = a_run("70")
    assert results.pass_mark(run) == Decimal(70)
    who = person(run)
    assert results.attempt_passed(played(run, who, 7)) is True
    assert results.attempt_passed(played(run, who, 6, 1)) is False
    # no rounding before the compare: 69.9 % does not pass 70 %
    assert results.attempt_passed(played(run, who, 699, 2, max_score=1000)) is False


def test_no_mark_means_none():
    run = a_run("0")
    assert results.pass_mark(run) is None
    assert results.attempt_passed(played(run, person(run), 10)) is None


def test_unjudged_attempts_are_none():
    run = a_run()
    who = person(run)
    assert (
        results.attempt_passed(played(run, who, 9, status=Attempt.Status.PENDING_GRADING)) is None
    )
    assert results.attempt_passed(played(run, who, 9, status=Attempt.Status.IN_PROGRESS)) is None
    assert results.attempt_passed(played(run, who, 0, max_score=0)) is None


def test_regrade_changes_mark():
    run = a_run()
    who = person(run)
    waiting = played(run, who, 2, status=Attempt.Status.PENDING_GRADING)
    assert results.attempt_passed(waiting) is None
    assert results.kept_passed(results.kept(who), run) is None
    Attempt.objects.filter(pk=waiting.pk).update(status=Attempt.Status.SUBMITTED, score=8)
    waiting.refresh_from_db()
    assert results.attempt_passed(waiting) is True
    assert results.kept_passed(results.kept(who), run) is True


def test_mark_survives_quiz_change():
    run = a_run("70")
    attempt = played(run, person(run), 8)
    settings.set_override(PASS_MARK, run.quiz, "90", admin_id=ADMIN_ID)
    attempt.refresh_from_db()
    assert results.attempt_passed(attempt) is True  # the run kept 70


def test_kept_passed_follows_the_rule():
    """AC-172: a participant passes on the kept score."""
    run = a_run("70", **{OFFICIAL_ATTEMPT: "best"})
    who = person(run)
    played(run, who, 4, 0)
    played(run, who, 8, 1)
    played(run, who, 5, 2)
    assert results.kept_passed(results.kept(who), run) is True
    last = a_run("70", slug="last", **{OFFICIAL_ATTEMPT: "last"})
    other = person(last)
    played(last, other, 8, 0)
    played(last, other, 5, 1)
    assert results.kept_passed(results.kept(other), last) is False


def test_kept_passed_none_without_kept_or_mark():
    run = a_run()
    assert results.kept_passed(None, run) is None
    none_run = a_run("0", slug="none")
    who = person(none_run)
    played(none_run, who, 9)
    assert results.kept_passed(results.kept(who), none_run) is None


def test_board_row_passed():
    run = a_run()
    played(run, person(run, "Ema"), 8, 0)
    played(run, person(run, "Petr"), 5, 1)
    rows = results.board(run, audience="admin", locale="cs").tables[0].rows
    assert {row.label: row.passed for row in rows} == {"Ema": True, "Petr": False}
    plain = a_run("0", slug="plain")
    played(plain, person(plain, "Ema"), 8)
    assert results.board(plain, audience="admin", locale="cs").tables[0].rows[0].passed is None


def test_attempt_rows_carry_the_verdict():
    run = a_run()
    who = person(run)
    played(run, who, 8, 0)
    played(run, who, 3, 1)
    assert [row.passed for row in participants.attempt_rows(run)] == [True, False]


def test_stats_share():
    """AC-172: the statistics count the share of participants who passed."""
    run = a_run(**{OFFICIAL_ATTEMPT: "best"})
    ema, petr, wait = person(run), person(run), person(run)
    played(run, ema, 3, 0)
    played(run, ema, 8, 1)
    played(run, petr, 5, 2)
    played(run, wait, 9, 3, status=Attempt.Status.PENDING_GRADING)
    stats = run_stats.of_run(run)
    assert (stats.passed, stats.judged) == (1, 2)
    again = run_stats.freeze(stats)
    assert (again["passed"], again["judged"]) == (1, 2)


def test_stats_verdicts_do_not_query_once_per_attempt():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def queries(attempt_count):
        run = a_run(slug=f"kviz{attempt_count}")
        who = person(run)
        for minute in range(attempt_count):
            played(run, who, 8, minute)
        found = list(Attempt.objects.filter(run=run))  # as the statistics load them
        with CaptureQueriesContext(connection) as captured:
            run_stats._verdicts(run, found)
        return len(captured)

    assert queries(4) == queries(2)  # one person: the same work however many attempts


def test_stats_without_mark():
    run = a_run("0")
    played(run, person(run), 8)
    stats = run_stats.of_run(run)
    assert (stats.passed, stats.judged) == (None, 0)


def table(run, name):
    found = results_export.tables([run], ["attempts", "participants"], "en", photos=False)
    return next(t for t in found if t.name == name).rows


def test_export_columns():
    """AC-172: the exports carry the verdict columns."""
    run = a_run(**{OFFICIAL_ATTEMPT: "best"})
    who = person(run)
    played(run, who, 3, 0)
    played(run, who, 8, 1)
    attempts_rows = table(run, "attempts")
    assert "passed" in attempts_rows[0]
    assert [r["passed"] for r in attempts_rows] == ["no", "yes"]
    people = table(run, "participants")
    assert (people[0]["kept_percent"], people[0]["passed"]) == ("80", "yes")
    plain = a_run("0", slug="plain")
    played(plain, person(plain), 8)
    assert table(plain, "attempts")[0]["passed"] == ""
    assert "kept_percent" in results_export._NUMERIC


def test_kept_waiting_is_unjudged_but_own_attempt_is_judged():
    run = a_run("70", **{OFFICIAL_ATTEMPT: "best"})
    who = person(run)
    submitted = played(run, who, 8, 0)
    played(run, who, 2, 1, status=Attempt.Status.PENDING_GRADING)
    found = results.kept(who)
    assert found is not None and found.waiting is True
    assert results.kept_passed(found, run) is None
    assert results.attempt_passed(submitted) is True


def test_stats_leave_out_people_whose_kept_waits():
    run = a_run(**{OFFICIAL_ATTEMPT: "best"})
    ema, waiting = person(run), person(run)
    played(run, ema, 8, 0)
    played(run, waiting, 8, 1)
    played(run, waiting, 2, 2, status=Attempt.Status.PENDING_GRADING)
    stats = run_stats.of_run(run)
    assert (stats.passed, stats.judged) == (1, 1)
