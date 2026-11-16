"""AC-113, AC-114: changing a run's period, before and after its data were deleted."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import authoring, data_policy, retention, run_schedule
from app.domain.models import QuizRun
from app.kernel.models import AuditEvent
from app.providers.retention.models import RetentionJob
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def at_noon(monkeypatch):
    freeze(monkeypatch, NOW)


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def ended_run(*, period="1y", closed=timedelta(days=100), **fields):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(
        status=QuizRun.Status.CLOSED,
        closed_at=NOW - closed,
        retention_json={"profile": "answers", "period": period},
        **fields,
    )
    run.refresh_from_db()
    return run


def period_of(run):
    run.refresh_from_db()
    return data_policy.of(run)[data_policy.PERIOD]


def changes(run):
    return AuditEvent.objects.filter(action="run.period_changed", entity_id=str(run.id)).count()


def change(run, period, **options):
    run_schedule.set_period(run, period, admin_id=ADMIN_ID, **options)


def held_run(period="30d", closed=timedelta(days=100)):
    return ended_run(period=period, closed=closed, retention_held_at=NOW - timedelta(days=1))


def test_shortening_into_the_past_needs_a_confirmation():
    """AC-114: without one nothing changes and nothing is audited."""
    run = ended_run()

    with pytest.raises(run_schedule.PeriodNeedsConfirmation):
        change(run, "30d")

    assert period_of(run) == "1y"
    assert changes(run) == 0
    assert retention.run_pass(NOW) == 0


def test_with_a_confirmation_the_next_pass_deletes():
    """AC-114."""
    run = ended_run()

    change(run, "30d", confirmed=True)

    assert period_of(run) == "30d"
    assert run.data_deleted_at is None
    assert retention.run_pass(NOW) == 1
    run.refresh_from_db()
    assert run.data_deleted_at is not None


def test_a_period_ending_exactly_now_is_due_at_once():
    """AC-114: the same boundary as `is_due`."""
    run = ended_run(closed=timedelta(days=30))

    with pytest.raises(run_schedule.PeriodNeedsConfirmation):
        change(run, "30d")


def test_a_period_ending_a_second_from_now_needs_no_confirmation():
    """AC-114."""
    run = ended_run(closed=timedelta(days=30) - timedelta(seconds=1))

    change(run, "30d")

    assert period_of(run) == "30d"


def test_shortening_that_stays_in_the_future_needs_no_confirmation():
    """AC-114."""
    run = ended_run(closed=timedelta(days=10))

    change(run, "30d")

    assert period_of(run) == "30d"


def test_lengthening_needs_no_confirmation():
    """AC-114."""
    run = ended_run(period="30d", closed=timedelta(days=10))

    change(run, "3y")

    assert period_of(run) == "3y"
    assert changes(run) == 1


def test_a_run_already_due_needs_no_confirmation():
    """AC-114: the change does not make it due, it already was."""
    run = ended_run(period="30d", closed=timedelta(days=200))

    change(run, "90d")

    assert period_of(run) == "90d"


def test_a_run_that_never_closed_needs_no_confirmation():
    """AC-114: a period counts from the close, so there is nothing to be due yet."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)

    change(run, "30d")

    assert period_of(run) == "30d"


@pytest.mark.parametrize("longer", ["1y", "permanent"])
def test_extending_a_held_run_past_now_clears_the_hold(longer):
    """AC-114: it is an ordinary run again, and `permanent` has no end to wait for."""
    run = held_run()

    change(run, longer)

    run.refresh_from_db()
    assert run.retention_held_at is None
    assert period_of(run) == longer
    assert retention.run_pass(NOW) == 0
    run.refresh_from_db()
    assert run.data_deleted_at is None


def test_a_held_run_still_in_the_past_stays_held():
    """AC-114: only the admin's confirmation of the list lets a held run go."""
    run = held_run()

    change(run, "90d")

    run.refresh_from_db()
    assert run.retention_held_at is not None
    assert period_of(run) == "90d"
    assert retention.run_pass(NOW) == 0


def test_a_held_run_stays_held_with_a_confirmation_too():
    """AC-114: confirming a period is not confirming the list of held runs."""
    run = held_run(period="1y", closed=timedelta(days=400))

    change(run, "30d", confirmed=True)

    run.refresh_from_db()
    assert run.retention_held_at is not None
    assert retention.run_pass(NOW) == 0


def deleted_run():
    run = ended_run(period="30d", closed=timedelta(days=100))
    retention.purge_run(run, trigger=retention.AUTOMATIC, admin_id=None)
    return run


@pytest.mark.parametrize("confirmed", [False, True])
def test_a_deleted_run_refuses_a_period_change(confirmed):
    """AC-113."""
    run = deleted_run()

    with pytest.raises(run_schedule.ScheduleRefused) as refused:
        change(run, "3y", confirmed=confirmed)

    assert refused.value.code == "data_deleted"
    assert period_of(run) == "30d"
    assert changes(run) == 0


def test_a_restored_run_stays_without_data_and_the_pass_skips_it():
    """AC-113."""
    run = deleted_run()
    deleted_at = run.data_deleted_at

    run_schedule.restore(run, admin_id=ADMIN_ID)

    run.refresh_from_db()
    assert run.status == QuizRun.Status.CLOSED
    assert run.data_deleted_at == deleted_at
    assert data_policy.of(run)[data_policy.PROFILE] == "none"
    assert retention.run_pass(NOW + timedelta(days=1)) == 0
    assert RetentionJob.objects.filter(run_id=str(run.id)).count() == 1
