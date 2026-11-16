"""AC-114: runs already past their period when D3 arrives wait for an admin."""

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0018_quiz_created_by")]
AFTER = [("domain", "0019_retention")]


@pytest.fixture(autouse=True)
def back_to_latest():
    """The next transactional test needs every migration, not the one this file stops at."""
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def add_run():
    old = migrate(BEFORE)
    quiz = old.get_model("domain", "Quiz").objects.create(
        slug="kviz", title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    revision = old.get_model("domain", "QuizRevision").objects.create(quiz=quiz, revision_no=1)
    numbers = iter(range(1, 100))

    def add(age_days=None, retention=None, status="CLOSED", kind="normal", **fields):
        closed_at = None if age_days is None else timezone.now() - timedelta(days=age_days)
        fields.setdefault("closed_at", closed_at)
        return old.get_model("domain", "QuizRun").objects.create(
            quiz=quiz,
            current_revision=revision,
            kind=kind,
            run_no=next(numbers) if kind == "normal" else None,
            status=status,
            retention_json={} if retention is None else {"period": retention},
            **fields,
        )

    return add


def held(run) -> bool:
    model = migrate(AFTER).get_model("domain", "QuizRun")
    return model.objects.get(pk=run.pk).retention_held_at is not None


def test_a_run_past_its_period_is_held(add_run):
    """AC-114: due at migration means held."""
    assert held(add_run(age_days=91, retention="90d"))


def test_a_run_within_its_period_is_not_held(add_run):
    """AC-114: a run that falls due later is deleted in the normal way."""
    assert not held(add_run(age_days=89, retention="90d"))


def test_a_permanent_run_is_not_held(add_run):
    """AC-114: permanent never falls due."""
    assert not held(add_run(age_days=5000, retention="permanent"))


def test_an_open_run_is_not_held(add_run):
    """AC-114: the period starts at the close."""
    assert not held(add_run(retention="30d", status="OPEN"))


def past(days):
    return timezone.now() - timedelta(days=days)


@pytest.mark.parametrize("status", ["OPEN", "SCHEDULED"])
def test_an_unsettled_run_past_its_deadline_is_held(add_run, status):
    """AC-114: settling would close it in the past, so the deadline counts as its close."""
    assert held(add_run(retention="90d", status=status, deadline_at=past(91)))


def test_an_unsettled_run_within_its_period_is_not_held(add_run):
    """AC-114: the deadline is 89 days old, so the period has not ended."""
    assert not held(add_run(retention="90d", status="OPEN", deadline_at=past(89)))


def test_an_open_run_without_a_deadline_is_not_held(add_run):
    """AC-114: nothing will close it on its own."""
    assert not held(add_run(retention="30d", status="OPEN", deadline_at=None))


def test_the_hold_survives_settling(add_run):
    """AC-114: closing the run afterwards leaves the hold in place."""
    run = add_run(retention="90d", status="OPEN", deadline_at=past(91))
    migrate(AFTER)
    # The live code below reads today's schema; later migrations keep the hold too.
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    from app.domain import data_policy, run_schedule
    from app.domain.models import QuizRun

    run_schedule.settle()
    settled = QuizRun.objects.get(pk=run.pk)
    assert settled.status == QuizRun.Status.CLOSED
    assert settled.retention_held_at is not None
    assert not data_policy.is_due(settled, timezone.now())


@pytest.mark.parametrize(
    ("period", "days"),
    [("30d", 30), ("90d", 90), ("180d", 180), ("1y", 365), ("3y", 1095)],
)
def test_the_migrations_day_table(add_run, period, days):
    """AC-114: held exactly when the period ends, not a second sooner."""
    now = datetime(2026, 11, 9, 12, tzinfo=UTC)
    end = now - timedelta(days=days)
    exactly = add_run(retention=period, closed_at=end)
    just_short = add_run(retention=period, closed_at=end + timedelta(seconds=1))
    with mock.patch("django.utils.timezone.now", return_value=now):
        model = migrate(AFTER).get_model("domain", "QuizRun")
    assert model.objects.get(pk=exactly.pk).retention_held_at == now
    assert model.objects.get(pk=just_short.pk).retention_held_at is None


def test_a_missing_period_counts_as_ninety_days(add_run):
    old_enough, recent = add_run(age_days=91), add_run(age_days=89)
    assert held(old_enough)
    assert not held(recent)


def test_a_test_run_is_not_held(add_run):
    assert not held(add_run(age_days=5000, retention="30d", kind="test"))


def test_new_fields_start_empty(add_run):
    run = add_run(age_days=1, retention="90d")
    model = migrate(AFTER).get_model("domain", "QuizRun")
    row = model.objects.get(pk=run.pk)
    assert row.data_deleted_at is None
    assert row.retention_summary_json == {}
