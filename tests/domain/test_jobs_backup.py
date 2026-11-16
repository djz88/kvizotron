"""D5: the daily backup in the `jobs` pass, and the deployment that gives it a place to live."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain import backup
from app.domain.management.commands import jobs
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db(transaction=True)

ROOT = Path(__file__).resolve().parent.parent.parent
NOW = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # 04:00 in Prague: the local date is the 10th
SECRET = "/data/backups/secret-place"


class Calls:
    """Stands in for retention and for the backup, and notes what the pass did in which order."""

    def __init__(self, monkeypatch, *, backup_error=None, retention_error=None, due=True):
        self.order: list[object] = []
        self.created_on: set[str] = set()
        self.due_flag = due

        def run_pass(*_args):
            self.order.append("retention")
            if retention_error:
                raise retention_error

        def is_due(now):
            return self.due_flag and now.date().isoformat() not in self.created_on

        def create(now):
            self.order.append("create")
            if backup_error:
                raise backup_error
            self.created_on.add(now.date().isoformat())

        def prune(now, days):
            self.order.append(("prune", days))
            return backup.PruneResult(removed=[], stayed=[])

        monkeypatch.setattr(jobs.retention, "run_pass", run_pass)
        monkeypatch.setattr(jobs.backup, "due", is_due)
        monkeypatch.setattr(jobs.backup, "create", create)
        monkeypatch.setattr(jobs.backup, "prune", prune)


def test_one_pass_runs_retention_and_a_due_backup(monkeypatch, settings):
    settings.KVZ_BACKUP_RETENTION_DAYS = 30
    freeze(monkeypatch, NOW)
    calls = Calls(monkeypatch)

    jobs.pass_once()

    assert calls.order == ["retention", "create", ("prune", 30)]


def test_a_pass_without_a_due_backup_only_runs_retention(monkeypatch):
    freeze(monkeypatch, NOW)
    calls = Calls(monkeypatch, due=False)

    jobs.pass_once()

    assert calls.order == ["retention"]


def test_no_second_backup_on_the_same_date(monkeypatch):
    freeze(monkeypatch, NOW)
    calls = Calls(monkeypatch)

    jobs.pass_once()
    jobs.pass_once()

    assert calls.order == ["retention", "create", ("prune", 30), "retention"]


def test_a_real_backup_is_made_once_a_day(monkeypatch, settings, file_db, tmp_path):
    """AC-134: The same, against the real `due` and `create` on a real database file."""
    settings.KVZ_BACKUP_PATH = str(tmp_path / "backups")
    settings.KVZ_MEDIA_PATH = str(tmp_path / "media")
    Path(settings.KVZ_MEDIA_PATH).mkdir()
    real_create = backup.create
    monkeypatch.setattr(jobs.retention, "run_pass", lambda *_args: 0)
    monkeypatch.setattr(
        jobs.backup, "create", lambda now: real_create(now, database_path=file_db.path)
    )
    freeze(monkeypatch, NOW)

    jobs.pass_once()
    first = [path.name for path in backup.listing()]
    jobs.pass_once()

    assert first == ["2026-11-10"]
    assert [path.name for path in backup.listing()] == first


def test_a_failing_backup_does_not_stop_the_retention_pass_and_is_logged_by_type(
    monkeypatch, caplog
):
    """AC-137: The anti-goal: a broken backup must never leave data kept beyond its retention."""
    freeze(monkeypatch, NOW)
    calls = Calls(monkeypatch, backup_error=OSError(SECRET))

    with caplog.at_level(logging.ERROR, logger="app.domain.management.commands.jobs"):
        jobs.pass_once()

    assert calls.order[0] == "retention"
    assert "create" in calls.order
    assert "OSError" in caplog.text
    assert SECRET not in caplog.text


def test_a_failed_backup_is_still_followed_by_pruning(monkeypatch):
    """AC-137: a full disk is the likely reason; `prune` keeps the newest valid backup."""
    freeze(monkeypatch, NOW)
    calls = Calls(monkeypatch, backup_error=backup.BackupError("fixed text"))

    jobs.pass_once()

    assert calls.order == ["retention", "create", ("prune", 30)]


def test_a_failing_retention_pass_does_not_stop_the_backup(monkeypatch, caplog):
    """AC-137: a retention pass that fails leaves the day with its backup."""
    freeze(monkeypatch, NOW)
    calls = Calls(monkeypatch, retention_error=RuntimeError(SECRET))

    with caplog.at_level(logging.ERROR, logger="app.domain.management.commands.jobs"):
        jobs.pass_once()

    assert calls.order == ["retention", "create", ("prune", 30)]
    assert "RuntimeError" in caplog.text
    assert SECRET not in caplog.text


def test_a_failing_prune_is_logged_by_type_and_does_not_escape(monkeypatch, caplog):
    freeze(monkeypatch, NOW)
    Calls(monkeypatch)

    def prune(_now, _days):
        raise backup.BackupError("fixed text")

    monkeypatch.setattr(jobs.backup, "prune", prune)

    with caplog.at_level(logging.ERROR, logger="app.domain.management.commands.jobs"):
        jobs.pass_once()

    assert "BackupError" in caplog.text


def test_prune_runs_after_a_successful_backup_with_the_configured_days(monkeypatch, settings):
    settings.KVZ_BACKUP_RETENTION_DAYS = 7
    freeze(monkeypatch, NOW)
    calls = Calls(monkeypatch)

    jobs.pass_once()

    assert calls.order[-1] == ("prune", 7)
    assert calls.order.index("create") < calls.order.index(("prune", 7))


def test_a_due_backup_is_skipped_when_stop_is_set(monkeypatch, settings, file_db, tmp_path):
    """TD-072: a stopping service does not start a backup; the pass is recorded `stopped`."""
    settings.KVZ_BACKUP_PATH = str(tmp_path / "backups")
    settings.KVZ_MEDIA_PATH = str(tmp_path / "media")
    Path(settings.KVZ_MEDIA_PATH).mkdir()
    real_create = backup.create
    monkeypatch.setattr(jobs.retention, "run_pass", lambda *_args: 0)
    monkeypatch.setattr(
        jobs.backup, "create", lambda now: real_create(now, database_path=file_db.path)
    )
    monkeypatch.setattr(jobs.heartbeat, "directory", lambda: tmp_path)
    freeze(monkeypatch, NOW)

    jobs.pass_once(stop=lambda: True)

    assert backup.listing() == []
    assert not (tmp_path / "backups").exists() or not any((tmp_path / "backups").iterdir())
    assert jobs.heartbeat.read_pass(tmp_path).outcome == "stopped"


def test_a_stopped_pass_skips_create_and_prune(monkeypatch):
    freeze(monkeypatch, NOW)
    calls = Calls(monkeypatch)

    jobs.pass_once(stop=lambda: True)

    assert calls.order == ["retention"]


def test_a_failure_before_the_stop_is_still_recorded_as_failed(monkeypatch, tmp_path):
    """A pass that raised and then stopped reports the failure, not the stop."""
    freeze(monkeypatch, NOW)
    monkeypatch.setattr(jobs.heartbeat, "directory", lambda: tmp_path)
    Calls(monkeypatch, retention_error=RuntimeError("boom"))

    jobs.pass_once(stop=lambda: True)

    assert jobs.heartbeat.read_pass(tmp_path).outcome == "failed"


def _stop_grace_period(name: str) -> str | None:
    for line in _service(name).splitlines():
        if line.strip().startswith("stop_grace_period:"):
            return line.split(":", 1)[1].strip()
    return None


def test_compose_gives_app_and_jobs_time_to_stop():
    """Gunicorn's graceful timeout is 30 s plus 5; a backup copies the database and the media."""
    assert _stop_grace_period("app") == "35s"
    assert _stop_grace_period("jobs") == "120s"


def _service(name: str) -> str:
    """The text of one service block of `deploy/compose.yaml`."""
    lines = (ROOT / "deploy" / "compose.yaml").read_text().splitlines()
    start = lines.index(f"  {name}:")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith("    ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_compose_mounts_backups_in_jobs_only():
    text = (ROOT / "deploy" / "compose.yaml").read_text()
    assert "      - backups:/data/backups" in _service("jobs")
    for name in ("app", "migrate", "caddy"):
        assert "backups" not in _service(name)
    anchor = text.split("services:")[0]
    assert "backups" not in anchor
    assert text.count("backups:/data/backups") == 1
    assert "\n  backups:\n" in text.split("\nvolumes:\n")[-1]


def test_dockerfile_creates_the_backup_directory():
    text = (ROOT / "Dockerfile").read_text()
    assert "/data/backups" in text
    assert "chown -R kvizotron:kvizotron /data" in text


def test_a_prune_that_left_directories_is_logged_by_count_and_the_pass_stays_ok(
    monkeypatch, caplog, tmp_path
):
    """AC-145: the log line names how many stayed, never where; the pass outcome is `ok`."""
    freeze(monkeypatch, NOW)
    monkeypatch.setattr(jobs.heartbeat, "directory", lambda: tmp_path)
    Calls(monkeypatch)
    left = [Path(SECRET) / "2026-09-01", Path(SECRET) / "2026-09-02"]
    monkeypatch.setattr(
        jobs.backup, "prune", lambda _now, _days: backup.PruneResult(removed=[], stayed=left)
    )

    with caplog.at_level(logging.WARNING, logger="app.domain.management.commands.jobs"):
        jobs.pass_once()

    assert "2 backup directories" in caplog.text
    assert "secret-place" not in caplog.text and "2026-09" not in caplog.text
    assert jobs.heartbeat.read_pass(tmp_path).outcome == "ok"


def test_a_pass_deletes_expired_admin_sessions(monkeypatch):
    """Nothing else removes them, and `end_sessions` must not read them forever (AC-169)."""
    from datetime import timedelta
    from importlib import import_module

    from django.conf import settings as django_settings
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    Calls(monkeypatch, due=False)
    store = import_module(django_settings.SESSION_ENGINE).SessionStore()
    store["x"] = 1
    store.create()
    Session.objects.update(expire_date=timezone.now() - timedelta(minutes=1))

    jobs.pass_once()

    assert not Session.objects.exists()
