"""The `jobs` service records each pass and beats while it runs."""

import signal
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from app.domain import backup, heartbeat
from app.domain.management.commands import jobs

pytestmark = pytest.mark.django_db(transaction=True)

START = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)


@pytest.fixture
def folder(monkeypatch, tmp_path):
    monkeypatch.setattr(heartbeat, "directory", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def ticking(monkeypatch):
    """A clock that moves one minute on each reading."""
    moments = iter(START + timedelta(minutes=minute) for minute in range(100))
    monkeypatch.setattr(timezone, "now", lambda: next(moments))


def parts(monkeypatch, *, retention=None, create=None, prune=None, due=True):
    def run_pass(*_args):
        if retention:
            retention()

    def make(*_args):
        if create:
            create()

    def clean(*_args):
        if prune:
            prune()
        return backup.PruneResult(removed=[], stayed=[])

    monkeypatch.setattr(jobs.retention, "run_pass", run_pass)
    monkeypatch.setattr(jobs.backup, "due", lambda _now: due)
    monkeypatch.setattr(jobs.backup, "create", make)
    monkeypatch.setattr(jobs.backup, "prune", clean)


def boom():
    raise RuntimeError("secret")


def test_a_successful_pass_leaves_a_finished_ok_record(monkeypatch, folder, ticking):
    """AC-144: the record the healthcheck and the history page read."""
    parts(monkeypatch)

    jobs.pass_once()

    record = heartbeat.read_pass(folder)
    assert record is not None and record.outcome == "ok" and record.started == START
    assert record.finished is not None and record.finished > record.started


def test_a_pass_with_no_backup_due_is_ok(monkeypatch, folder, ticking):
    parts(monkeypatch, due=False)

    jobs.pass_once()

    record = heartbeat.read_pass(folder)
    assert record is not None and record.outcome == "ok" and record.finished is not None


@pytest.mark.parametrize("which", ["retention", "create", "prune"])
def test_a_step_that_raised_makes_the_pass_failed(monkeypatch, folder, ticking, which):
    """AC-144: any of the retention pass, the backup and the prune failing means `failed`."""
    parts(monkeypatch, **{which: boom})

    jobs.pass_once()

    record = heartbeat.read_pass(folder)
    assert record is not None and record.outcome == "failed" and record.finished is not None


def test_a_failing_due_check_makes_the_pass_failed(monkeypatch, folder, ticking):
    parts(monkeypatch)

    def due(_now):
        raise backup.BackupError("fixed")

    monkeypatch.setattr(jobs.backup, "due", due)

    jobs.pass_once()

    record = heartbeat.read_pass(folder)
    assert record is not None and record.outcome == "failed"


def test_a_pass_in_progress_keeps_the_previous_finish_and_outcome(monkeypatch, folder, ticking):
    parts(monkeypatch)
    jobs.pass_once()
    first = heartbeat.read_pass(folder)
    seen = {}

    def reading():
        seen["record"] = heartbeat.read_pass(folder)

    parts(monkeypatch, retention=reading)

    jobs.pass_once()

    during = seen["record"]
    assert first is not None and during is not None
    assert during.started is not None and during.started > first.started
    assert during.finished == first.finished
    assert during.outcome == first.outcome == "ok"
    last = heartbeat.read_pass(folder)
    assert last is not None and last.finished is not None and last.finished > first.finished


def test_the_first_pass_in_progress_has_no_finish(monkeypatch, folder, ticking):
    seen = {}
    parts(monkeypatch, retention=lambda: seen.update(record=heartbeat.read_pass(folder)))

    jobs.pass_once()

    record = seen["record"]
    assert record is not None and record.started is not None
    assert record.finished is None and record.outcome is None


def test_the_command_beats_before_the_first_pass_and_clears_on_the_way_out(monkeypatch, folder):
    seen = {}
    monkeypatch.setattr(jobs.signal, "signal", lambda *_args: None)

    def run_loop(stop, wait, one_pass):
        seen["age"] = heartbeat.age("jobs", folder)

    monkeypatch.setattr(jobs, "run_loop", run_loop)

    call_command("jobs")

    assert seen["age"] is not None and seen["age"] < 5
    assert heartbeat.age("jobs", folder) is None


def test_the_command_clears_the_beat_after_a_sigterm_stop(monkeypatch, folder):
    handlers = {}
    monkeypatch.setattr(jobs.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))

    def run_loop(stop, wait, one_pass):
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        assert stop.is_set()

    monkeypatch.setattr(jobs, "run_loop", run_loop)

    call_command("jobs")

    assert heartbeat.age("jobs", folder) is None


def test_the_beat_is_kept_up_while_the_loop_runs(monkeypatch, folder):
    monkeypatch.setattr(jobs.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(heartbeat, "JOBS_INTERVAL", 0.05)
    ages = []

    def run_loop(stop, wait, one_pass):
        time.sleep(0.4)
        ages.append(heartbeat.age("jobs", folder))

    monkeypatch.setattr(jobs, "run_loop", run_loop)

    call_command("jobs")

    assert ages[0] is not None and ages[0] < 0.3


def test_the_beating_thread_ends_with_the_command(monkeypatch, folder):
    monkeypatch.setattr(jobs.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(jobs, "run_loop", lambda *_args: None)

    call_command("jobs")

    assert "jobs-heartbeat" not in [thread.name for thread in threading.enumerate()]
