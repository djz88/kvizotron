"""AC-119: the hourly pass, its commands and the sweep of photo files nothing refers to."""

import logging
import signal
import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from app.domain import authoring, branding, heartbeat, retention
from app.domain.management.commands import jobs
from app.domain.models import Attempt, AttemptAnswer, QuizRun
from app.kernel import registry
from app.kernel.models import AuditEvent
from app.providers.csv_io.models import ExportJobRecord
from app.providers.media_local.models import MediaAsset
from app.providers.retention.models import RetentionJob
from tests.domain.helpers import ADMIN_ID, published_quiz

SECRET = "jana@example.test"


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def open_run(slug):
    return authoring.open_run(published_quiz(slug, questions=1), admin_id=ADMIN_ID)


def ended_run(slug, *, period="30d", days_ago=31, **fields):
    run = open_run(slug)
    QuizRun.objects.filter(pk=run.pk).update(
        status=QuizRun.Status.CLOSED,
        closed_at=timezone.now() - timedelta(days=days_ago),
        retention_json={"profile": "answers", "period": period},
        **fields,
    )
    run.refresh_from_db()
    return run


def deleted(run):
    run.refresh_from_db()
    return run.data_deleted_at is not None


def asset(path, *, private=True, age=timedelta(hours=2)):
    asset_id = uuid4()
    MediaAsset.objects.create(
        id=asset_id,
        storage_key=f"{asset_id}.webp",
        mime_type="image/webp",
        size=1,
        sha256="0" * 64,
        private=private,
    )
    (path / f"{asset_id}.webp").write_bytes(b"x")
    MediaAsset.objects.filter(pk=asset_id).update(created_at=timezone.now() - age)
    return str(asset_id)


def referenced(asset_id):
    run = open_run(f"s{uuid4().hex[:8]}")
    attempt = Attempt.objects.create(
        run=run, revision=run.current_revision, max_score=run.current_revision.max_score
    )
    AttemptAnswer.objects.create(
        attempt=attempt, question_id="q", answer_json={}, auto_points=0, asset_id=asset_id
    )


def stopped_purge(run, monkeypatch):
    """A purge stopped by an export it could not remove: summary kept, data not marked deleted."""

    def refuse(_run):
        raise OSError("disk")

    with monkeypatch.context() as patch:
        patch.setattr(retention, "_delete_exports", refuse)
        with pytest.raises(OSError):
            retention.purge_run(run, trigger=retention.MANUAL, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.retention_summary_json and run.data_deleted_at is None


@pytest.mark.django_db
def test_the_command_purges_a_due_run_as_automatic():
    """AC-14, AC-119: `manage.py retention` deletes a due run, with no admin behind it."""
    due = ended_run("due")

    call_command("retention")

    assert deleted(due)
    job = RetentionJob.objects.get(run_id=due.pk)
    assert job.trigger == "automatic"
    assert job.admin_id is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields",
    [
        {"period": "30d", "days_ago": 29},
        {"period": "permanent", "days_ago": 4000},
        {"period": "30d", "days_ago": 31, "retention_held_at": timezone.now()},
    ],
    ids=["not yet", "permanent", "held"],
)
def test_a_run_not_due_is_left_alone(fields):
    """AC-14, AC-119: the pass deletes nothing that has not fallen due."""
    run = ended_run("kept", **fields)

    assert retention.run_pass() == 0
    assert not deleted(run)
    assert not RetentionJob.objects.exists()


@pytest.mark.django_db
def test_a_new_run_of_the_quiz_neither_deletes_nor_protects_the_older_one():
    """AC-14: the older run keeps its data until its own period ends, whatever the new run does."""
    old = ended_run("again", days_ago=5)
    attempt = Attempt.objects.create(
        run=old, revision=old.current_revision, max_score=old.current_revision.max_score
    )
    new = authoring.open_run(old.quiz, admin_id=ADMIN_ID)
    assert new.id != old.id

    assert retention.run_pass() == 0
    assert Attempt.objects.filter(pk=attempt.pk).exists()
    assert not deleted(old)

    QuizRun.objects.filter(pk=old.pk).update(closed_at=timezone.now() - timedelta(days=31))
    assert retention.run_pass() == 1
    assert deleted(old)
    assert not Attempt.objects.filter(pk=attempt.pk).exists()
    new.refresh_from_db()
    assert new.status == QuizRun.Status.OPEN
    assert not deleted(new)


@pytest.mark.django_db
def test_a_failing_run_leaves_the_others_purged_and_logs_only_its_id(monkeypatch, caplog):
    """AC-119: one run failing does not stop the pass, is not counted, and logs no value."""
    bad, good = ended_run("bad"), ended_run("good")
    real = retention.purge_run

    def purge(run, **kwargs):
        if run.pk == bad.pk:
            raise RuntimeError(SECRET)
        return real(run, **kwargs)

    monkeypatch.setattr(retention, "purge_run", purge)

    with caplog.at_level(logging.ERROR, logger="app.domain.retention"):
        assert retention.run_pass() == 1

    assert deleted(good)
    assert not deleted(bad)
    assert str(bad.pk) in caplog.text
    assert "RuntimeError" in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.django_db
def test_two_passes_leave_one_record():
    """AC-119: a second pass finds the run already deleted."""
    due = ended_run("due")

    assert retention.run_pass() == 1
    assert retention.run_pass() == 0

    assert RetentionJob.objects.filter(run_id=due.pk).count() == 1


@pytest.mark.django_db
def test_a_deadline_not_yet_settled_closes_the_run_first():
    """AC-119: the pass settles deadlines, so a run nobody visited still gets its date."""
    run = open_run("late")
    deadline = timezone.now() - timedelta(days=31)
    QuizRun.objects.filter(pk=run.pk).update(
        deadline_at=deadline, retention_json={"profile": "answers", "period": "30d"}
    )

    assert retention.run_pass() == 1

    run.refresh_from_db()
    assert run.closed_at == deadline
    assert run.data_deleted_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields",
    [{"period": "permanent"}, {"retention_held_at": timezone.now()}],
    ids=["permanent", "held"],
)
def test_a_stopped_purge_is_finished_though_the_run_is_not_due(monkeypatch, fields):
    """AC-119: a run left half deleted does not stay so because no date would ever bring it back."""
    run = ended_run("stopped", **fields)
    stopped_purge(run, monkeypatch)

    assert retention.run_pass() == 1

    assert deleted(run)
    assert RetentionJob.objects.get(run_id=run.pk).trigger == "manual"  # as the purge began, TD-072


@pytest.mark.django_db
def test_a_hold_placed_during_the_pass_is_respected(monkeypatch):
    """AC-119: what is due is read again just before the deletion, not from the pass's start."""
    runs = {run.pk: run for run in (ended_run("one"), ended_run("two"))}
    real = retention.purge_run

    def purge(run, **kwargs):
        others = [pk for pk in runs if pk != run.pk]
        QuizRun.objects.filter(pk__in=others).update(retention_held_at=timezone.now())
        return real(run, **kwargs)

    monkeypatch.setattr(retention, "purge_run", purge)

    assert retention.run_pass() == 1
    assert sum(deleted(run) for run in runs.values()) == 1


@pytest.mark.django_db
def test_the_sweep_removes_only_old_private_files_nothing_refers_to(media_path):
    """AC-119: never an admin's image, a photo being submitted or one an answer still uses."""
    orphan = asset(media_path)
    recent = asset(media_path, age=timedelta(minutes=10))
    public = asset(media_path, private=False)
    used = asset(media_path)
    referenced(used)

    assert retention.sweep(timezone.now()) == 1

    left = {str(pk) for pk in MediaAsset.objects.values_list("pk", flat=True)}
    assert left == {recent, public, used}
    assert not (media_path / f"{orphan}.webp").exists()


@pytest.mark.django_db
def test_the_pass_sweeps(media_path):
    """AC-119: the file a purge could not remove goes with a later pass."""
    orphan = asset(media_path)

    retention.run_pass()

    assert not MediaAsset.objects.filter(pk=orphan).exists()


@pytest.mark.django_db
def test_a_file_that_cannot_be_deleted_does_not_stop_the_sweep(media_path, monkeypatch, caplog):
    """AC-119: the next pass tries again, and the log has no path or value in it."""
    bad, good = asset(media_path), asset(media_path)
    storage = branding.media()
    real = storage.delete_image

    def delete(asset_id):
        if asset_id == bad:
            raise OSError(SECRET)
        real(asset_id)

    monkeypatch.setattr(storage, "delete_image", delete)

    with caplog.at_level(logging.ERROR, logger="app.domain.retention"):
        assert retention.sweep(timezone.now()) == 1

    assert not MediaAsset.objects.filter(pk=good).exists()
    assert bad in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.django_db
def test_the_sweep_without_a_media_module_does_nothing(monkeypatch):
    """AC-119: no module means no files, which is not a failed pass."""

    def missing():
        raise LookupError("media_storage")

    monkeypatch.setattr(branding, "media", missing)

    assert retention.sweep(timezone.now()) == 0


@pytest.fixture
def connections(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "close_old_connections", lambda: calls.append("close"))
    return calls


def stopping(stop, waits):
    def wait(seconds):
        waits.append(seconds)
        stop.set()
        return True

    return wait


def test_the_loop_makes_a_pass_and_stops_when_told(connections):
    """AC-119: one pass at the start, then the hour's wait ends with the stop."""
    stop = threading.Event()
    passes, waits = [], []

    jobs.run_loop(stop, stopping(stop, waits), lambda: passes.append(1))

    assert passes == [1]
    assert waits == [3600]


def test_a_stopped_loop_makes_no_pass(connections):
    """AC-119: a SIGTERM that came first means no new pass."""
    stop = threading.Event()
    stop.set()
    passes = []

    jobs.run_loop(stop, lambda _seconds: True, lambda: passes.append(1))

    assert passes == []


def test_a_failed_pass_is_logged_by_type_and_the_loop_goes_on(connections, caplog):
    """AC-119: an exception costs one pass, not the service, and its message is not logged."""
    stop = threading.Event()
    outcomes = iter([RuntimeError(SECRET), None])
    passes = []

    def one_pass():
        passes.append(1)
        outcome = next(outcomes)
        if outcome:
            raise outcome

    def wait(_seconds):
        if len(passes) == 2:
            stop.set()
        return stop.is_set()

    with caplog.at_level(logging.ERROR, logger="app.domain.management.commands.jobs"):
        jobs.run_loop(stop, wait, one_pass)

    assert len(passes) == 2
    assert "RuntimeError" in caplog.text
    assert SECRET not in caplog.text


def test_connections_are_closed_around_each_pass(connections):
    """AC-119: a pass an hour after the last does not use a connection that went stale."""
    stop = threading.Event()

    def one_pass():
        connections.append("pass")

    jobs.run_loop(stop, stopping(stop, []), one_pass)

    assert connections == ["close", "pass", "close"]


def test_the_jobs_command_stops_on_sigterm(monkeypatch):
    """AC-119: the service makes retention passes and ends when the container is stopped."""
    handlers = {}
    seen = {}
    monkeypatch.setattr(jobs.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))
    monkeypatch.setattr(
        jobs, "run_loop", lambda stop, wait, one_pass: seen.update(stop=stop, one_pass=one_pass)
    )

    call_command("jobs")

    assert seen["one_pass"].func is jobs.pass_once
    assert seen["one_pass"].keywords == {"stop": seen["stop"].is_set}
    assert not seen["stop"].is_set()
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert seen["stop"].is_set()


@pytest.mark.django_db
def test_released_runs_go_on_the_next_pass_and_the_audit_holds_ids_and_count_only():
    """AC-114: confirming the list ends the hold; ids and a count are all the audit keeps."""
    run = ended_run("drzeny", retention_held_at=timezone.now())
    assert retention.run_pass() == 0

    assert retention.release_held([str(run.pk)], admin_id=ADMIN_ID) == 1

    event = AuditEvent.objects.get(action="retention.held_released")
    assert event.details_json == {"run_ids": [str(run.pk)], "count": 1}
    assert event.actor_id == ADMIN_ID
    assert retention.run_pass() == 1
    assert deleted(run)


@pytest.mark.django_db
def test_releasing_with_nothing_held_records_nothing():
    run = ended_run("volny", retention_held_at=timezone.now())
    assert retention.release_held([], admin_id=ADMIN_ID) == 0
    run.refresh_from_db()
    assert run.retention_held_at is not None
    assert not AuditEvent.objects.filter(action="retention.held_released").exists()


@pytest.mark.django_db
def test_a_run_held_after_the_page_was_shown_stays_held():
    """AC-114: only the runs the admin saw are released."""
    seen = ended_run("videny", retention_held_at=timezone.now())
    later = ended_run("pozdejsi", retention_held_at=timezone.now())
    free = ended_run("volny")

    assert retention.release_held([str(seen.pk), str(free.pk)], admin_id=ADMIN_ID) == 1

    for run in (seen, later, free):
        run.refresh_from_db()
    assert seen.retention_held_at is None
    assert later.retention_held_at is not None
    event = AuditEvent.objects.get(action="retention.held_released")
    assert event.details_json == {"run_ids": [str(seen.pk)], "count": 1}


@pytest.mark.django_db
def test_a_failing_settle_does_not_stop_the_purge_or_the_sweep(monkeypatch, caplog):
    """AC-119: the pass goes on after a failure in the settling, and logs the type only."""
    run = ended_run("due")
    swept = []

    def settle(now):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(retention.run_schedule, "settle", settle)
    monkeypatch.setattr(retention, "sweep", lambda now: swept.append(now) or 0)

    with caplog.at_level(logging.ERROR, logger="app.domain.retention"):
        assert retention.run_pass() == 1

    assert deleted(run)
    assert swept
    assert "RuntimeError" in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.django_db
def test_a_failing_sweep_is_logged_and_the_pass_still_counts(monkeypatch, caplog):
    """AC-119: a failure in the sweep does not lose the count of what was purged."""
    run = ended_run("due")

    def sweep(now):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(retention, "sweep", sweep)

    with caplog.at_level(logging.ERROR, logger="app.domain.retention"):
        assert retention.run_pass() == 1

    assert deleted(run)
    assert "RuntimeError" in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.django_db
def test_a_manual_purge_resumed_by_a_pass_is_recorded_as_manual(monkeypatch):
    """AC-111: the trigger is kept in the summary, so a pass that finishes it does not rename it."""
    run = ended_run("stopped")
    stopped_purge(run, monkeypatch)

    assert retention.run_pass() == 1

    job = RetentionJob.objects.get(run_id=run.pk)
    assert job.trigger == "manual"
    assert job.admin_id == ADMIN_ID
    assert AuditEvent.objects.get(action="run.data_deleted").actor_id == ADMIN_ID


@pytest.mark.django_db
def test_a_summary_written_before_the_trigger_was_kept_falls_back_to_the_pass(monkeypatch):
    """AC-111: a half-finished purge of an older version has no trigger in its summary."""
    run = ended_run("old")
    stopped_purge(run, monkeypatch)
    summary = {key: value for key, value in run.retention_summary_json.items()}
    for key in ("trigger", "admin_id"):
        summary.pop(key, None)
    QuizRun.objects.filter(pk=run.pk).update(retention_summary_json=summary)

    assert retention.run_pass() == 1

    assert RetentionJob.objects.get(run_id=run.pk).trigger == "automatic"


@pytest.mark.django_db
def test_the_missing_exporter_is_warned_about_once_per_pass(monkeypatch, caplog):
    """AC-111: three runs, the late retry and the purges all find none, and the log says so once."""
    runs = [ended_run(f"due{number}") for number in range(3)]
    real = registry.get

    def no_exporter(port, key, **kwargs):
        if port == "results_exporter":
            raise LookupError(port)
        return real(port, key, **kwargs)

    monkeypatch.setattr(registry, "get", no_exporter)

    with caplog.at_level(logging.WARNING, logger="app.domain.retention"):
        assert retention.run_pass() == 3

    assert all(deleted(run) for run in runs)
    assert caplog.text.count("no results exporter") == 1


@pytest.mark.django_db
def test_a_purge_outside_a_pass_still_warns_each_time(monkeypatch, caplog):
    """AC-111: only a pass is quiet after the first warning; "delete now" has no pass around it."""
    first, second = ended_run("one"), ended_run("two")
    real = registry.get

    def no_exporter(port, key, **kwargs):
        if port == "results_exporter":
            raise LookupError(port)
        return real(port, key, **kwargs)

    monkeypatch.setattr(registry, "get", no_exporter)

    with caplog.at_level(logging.WARNING, logger="app.domain.retention"):
        retention.purge_run(first, trigger=retention.MANUAL, admin_id=ADMIN_ID)
        retention.purge_run(second, trigger=retention.MANUAL, admin_id=ADMIN_ID)

    assert caplog.text.count("no results exporter") == 4  # before and after the commit, twice


def late_export(media_path, run):
    now = timezone.now()
    job = ExportJobRecord.objects.create(
        admin_id="a",
        kind="results",
        status="done",
        choices_json={"quiz": str(run.quiz_id), "runs": [str(run.id)], "all_runs": False},
        report_json={"files": ["x.csv"], "error": None},
        boot="x",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    directory = media_path / "exports" / str(job.pk)
    directory.mkdir(parents=True)
    (directory / "x.csv").write_text("x")
    return job, directory


def purge_with_a_failing_late_removal(media_path, monkeypatch, run):
    """The export arrives while the purge finishes, and the removal after the commit fails."""
    exporter = registry.get("results_exporter", "csv")
    real_delete = type(exporter).delete_for_runs
    real_finish = retention._finish
    made, calls = [], []

    def arrives(*args):
        made.append(late_export(media_path, run))
        return real_finish(*args)

    def fails_the_second_time(self, quiz_id, run_ids):
        calls.append(run_ids)
        if len(calls) == 2:
            raise OSError("disk")
        real_delete(self, quiz_id, run_ids)

    with monkeypatch.context() as patch:
        patch.setattr(retention, "_finish", arrives)
        patch.setattr(type(exporter), "delete_for_runs", fails_the_second_time)
        assert retention.purge_run(run, trigger=retention.AUTOMATIC, admin_id=None) is True
    ((job, directory),) = made
    assert directory.exists()
    return job, directory, calls


@pytest.mark.django_db
def test_a_late_export_removal_that_failed_is_retried_by_the_next_pass_for_a_day(
    media_path, monkeypatch
):
    """AC-111: the retry step of the pass, for a run deleted within the last 24 hours."""
    run = ended_run("late")
    job, directory, _calls = purge_with_a_failing_late_removal(media_path, monkeypatch, run)

    assert QuizRun.objects.get(pk=run.pk).retention_summary_json["late_exports_pending"] is True

    assert retention.run_pass() == 0

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()
    assert "late_exports_pending" not in QuizRun.objects.get(pk=run.pk).retention_summary_json


@pytest.mark.django_db
def test_a_run_deleted_more_than_a_day_ago_is_not_retried(media_path, monkeypatch):
    """AC-111: the tidy of old exports takes over after 24 hours, the pass does not look again."""
    run = ended_run("old")
    job, directory, _calls = purge_with_a_failing_late_removal(media_path, monkeypatch, run)
    QuizRun.objects.filter(pk=run.pk).update(data_deleted_at=timezone.now() - timedelta(hours=25))
    exporter = registry.get("results_exporter", "csv")
    asked = []
    monkeypatch.setattr(
        type(exporter), "delete_for_runs", lambda self, quiz_id, run_ids: asked.append(run_ids)
    )

    retention.run_pass()

    assert asked == []
    assert directory.exists()


@pytest.mark.django_db
def test_a_pass_stops_between_runs_when_told_to(monkeypatch):
    """AC-111: the stop flag is read before each run; nothing runs after it, not even the sweep."""
    runs = [ended_run(f"due{number}") for number in range(3)]
    swept = []
    monkeypatch.setattr(retention, "sweep", lambda now: swept.append(now) or 0)

    def stop():
        return sum(deleted(run) for run in runs) >= 1

    assert retention.run_pass(stop=stop) == 1

    assert sum(deleted(run) for run in runs) == 1
    assert swept == []
    assert retention.run_pass() == 2  # the next pass takes the rest


@pytest.mark.django_db
def test_a_pass_with_a_stop_that_never_says_so_purges_everything():
    runs = [ended_run(f"due{number}") for number in range(2)]

    assert retention.run_pass(stop=lambda: False) == 2

    assert all(deleted(run) for run in runs)


def test_a_pass_hands_the_stop_flag_to_the_retention_pass(monkeypatch, tmp_path):
    """AC-111: `jobs` gives `retention.run_pass` the callable that tells it SIGTERM came."""
    monkeypatch.setattr(heartbeat, "directory", lambda: tmp_path)
    monkeypatch.setattr(jobs.backup, "due", lambda _now: False)
    stop = threading.Event()
    seen = []
    # Positional: the stand-ins of the other `jobs` tests take `*args`.
    monkeypatch.setattr(jobs.retention, "run_pass", lambda *args: seen.append(args[1]))

    jobs.pass_once(stop=stop.is_set)

    (given,) = seen
    assert given() is False
    stop.set()
    assert given() is True


def test_the_jobs_command_binds_its_stop_event_to_each_pass(monkeypatch, tmp_path):
    """AC-111: a SIGTERM during a pass reaches `retention.run_pass` through the loop's callable."""
    monkeypatch.setattr(heartbeat, "directory", lambda: tmp_path)
    monkeypatch.setattr(jobs.backup, "due", lambda _now: False)
    handlers, seen = {}, []
    monkeypatch.setattr(jobs.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))
    monkeypatch.setattr(jobs.retention, "run_pass", lambda *args: seen.append(args[1]))

    def run_loop(stop, wait, one_pass):
        one_pass()

    monkeypatch.setattr(jobs, "run_loop", run_loop)

    call_command("jobs")

    (given,) = seen
    assert given() is False
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert given() is True


@pytest.mark.django_db
def test_an_all_runs_export_made_after_a_purge_that_removed_its_exports_survives_the_next_pass(
    media_path,
):
    """AC-111: the retry is only for a removal that failed, `delete_for_runs` also takes
    every "all runs" export of the quiz."""
    run = ended_run("done")
    assert retention.purge_run(run, trigger=retention.AUTOMATIC, admin_id=None) is True
    assert "late_exports_pending" not in QuizRun.objects.get(pk=run.pk).retention_summary_json
    job, directory = late_export(media_path, run)
    ExportJobRecord.objects.filter(pk=job.pk).update(
        choices_json={"quiz": str(run.quiz_id), "runs": [], "all_runs": True}
    )

    assert retention.run_pass() == 0

    assert ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert directory.exists()


@pytest.mark.django_db
def test_a_late_removal_that_failed_again_stays_pending_for_the_pass_after(media_path, monkeypatch):
    """AC-111: the flag is cleared only by a removal that worked."""
    run = ended_run("again")
    job, directory, _calls = purge_with_a_failing_late_removal(media_path, monkeypatch, run)
    exporter = registry.get("results_exporter", "csv")
    real = type(exporter).delete_for_runs
    attempts = []

    def fails_once_more(self, quiz_id, run_ids):
        attempts.append(run_ids)
        if len(attempts) == 1:
            raise OSError("disk")
        real(self, quiz_id, run_ids)

    monkeypatch.setattr(type(exporter), "delete_for_runs", fails_once_more)

    retention.run_pass()
    assert directory.exists()
    assert QuizRun.objects.get(pk=run.pk).retention_summary_json["late_exports_pending"] is True

    retention.run_pass()
    assert not directory.exists()
    assert "late_exports_pending" not in QuizRun.objects.get(pk=run.pk).retention_summary_json
    assert len(attempts) == 2

    retention.run_pass()
    assert len(attempts) == 2  # nothing is pending, so no third call
