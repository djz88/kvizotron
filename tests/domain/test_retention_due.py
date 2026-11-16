"""AC-110: when a run's data fall due. AC-118: when the date starts to warn."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import data_policy, settings
from app.domain.models import QuizRun

CLOSED = datetime(2026, 1, 1, 12, tzinfo=UTC)
DUE = CLOSED + timedelta(days=90)
SECOND = timedelta(seconds=1)


def run(period="90d", **fields):
    fields.setdefault("closed_at", CLOSED)
    fields.setdefault("status", QuizRun.Status.CLOSED)
    return QuizRun(retention_json={"period": period}, **fields)


def test_due_exactly_when_the_period_ends():
    """AC-110: due at closed_at + 90 days, not a second sooner."""
    assert data_policy.deletion_at(run()) == DUE
    assert data_policy.is_due(run(), DUE)
    assert data_policy.is_due(run(), DUE + SECOND)
    assert not data_policy.is_due(run(), DUE - SECOND)


@pytest.mark.parametrize(
    ("label", "subject"),
    [
        ("permanent", run("permanent")),
        ("never closed", run(closed_at=None, status=QuizRun.Status.OPEN)),
        ("deleted", run(data_deleted_at=DUE)),
        ("test run", run(kind=QuizRun.Kind.TEST)),
    ],
)
def test_no_deletion_date(label, subject):
    """AC-110: permanent, never closed, deleted and test runs have no date and are not due."""
    assert data_policy.deletion_at(subject) is None, label
    assert not data_policy.is_due(subject, DUE + timedelta(days=9999)), label
    assert data_policy.days_left(subject, DUE) is None, label
    assert not data_policy.deletion_soon(subject, DUE), label


def test_a_held_run_keeps_its_date_but_is_not_due():
    """AC-110: the job leaves a held run alone, however long ago it fell due."""
    held = run(retention_held_at=DUE)
    assert data_policy.deletion_at(held) == DUE
    assert not data_policy.is_due(held, DUE + timedelta(days=9999))


@pytest.mark.parametrize(
    ("period", "days"),
    [("30d", 30), ("90d", 90), ("180d", 180), ("1y", 365), ("3y", 1095)],
)
def test_period_lengths(period, days):
    """AC-110: `1y` is 365 days, and every period counts from the close."""
    assert data_policy.deletion_at(run(period)) == CLOSED + timedelta(days=days)


def test_every_period_but_permanent_has_days():
    assert set(data_policy.PERIOD_DAYS) == {period.value for period in settings.RetentionPeriod} - {
        settings.RetentionPeriod.PERMANENT.value
    }


def test_a_run_without_a_stored_period_uses_the_default():
    assert data_policy.deletion_at(QuizRun(closed_at=CLOSED)) == DUE


def test_warning_starts_at_fourteen_days():
    """AC-118: 14 days left warns, 15 does not."""
    assert data_policy.WARNING_DAYS == 14
    assert data_policy.days_left(run(), DUE - timedelta(days=14)) == 14
    assert data_policy.deletion_soon(run(), DUE - timedelta(days=14))
    assert data_policy.days_left(run(), DUE - timedelta(days=15)) == 15
    assert not data_policy.deletion_soon(run(), DUE - timedelta(days=15))


def test_part_of_a_day_counts_as_a_day():
    """The whole ninth day reads "in 9 days", and 14 days and a second is not within 14."""
    assert data_policy.days_left(run(), DUE - timedelta(days=9) + SECOND) == 9
    assert data_policy.days_left(run(), DUE - timedelta(days=14) - SECOND) == 15
    assert not data_policy.deletion_soon(run(), DUE - timedelta(days=14) - SECOND)


def test_days_left_stops_at_zero():
    assert data_policy.days_left(run(), DUE + timedelta(days=3)) == 0
