"""AC-143, AC-144: heartbeat files and the pass record that the jobs healthcheck reads."""

import os
import stat
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain import heartbeat

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def database(monkeypatch, settings, name) -> None:
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", name)


def test_constants():
    limits = (heartbeat.STALE_SECONDS, heartbeat.JOBS_INTERVAL, heartbeat.APP_INTERVAL)
    assert limits == (60, 15, 10)


def test_beat_then_age_is_fresh(tmp_path):
    heartbeat.beat("app", tmp_path)
    age = heartbeat.age("app", tmp_path)
    assert age is not None and 0 <= age < 1


def test_age_of_missing_name_is_none(tmp_path):
    assert heartbeat.age("jobs", tmp_path) is None


def test_names_are_independent(tmp_path):
    heartbeat.beat("app", tmp_path)
    assert heartbeat.age("jobs", tmp_path) is None


def test_age_follows_the_given_time(tmp_path):
    heartbeat.beat("jobs", tmp_path)
    later = heartbeat.age("jobs", tmp_path, now=time.time() + 90)
    assert later is not None and 89 < later < 91


def test_beat_touches_an_existing_file(tmp_path):
    heartbeat.beat("app", tmp_path)
    (old,) = [p for p in tmp_path.iterdir()]
    os.utime(old, (1, 1))
    assert heartbeat.age("app", tmp_path) > 1000
    heartbeat.beat("app", tmp_path)
    assert heartbeat.age("app", tmp_path) < 1


def test_clear_removes_and_second_clear_is_silent(tmp_path):
    heartbeat.beat("app", tmp_path)
    heartbeat.clear("app", tmp_path)
    assert heartbeat.age("app", tmp_path) is None
    heartbeat.clear("app", tmp_path)


def test_beat_into_missing_directory_does_not_raise(tmp_path):
    heartbeat.beat("app", tmp_path / "missing")
    heartbeat.clear("app", tmp_path / "missing")
    assert heartbeat.age("app", tmp_path / "missing") is None


def test_beat_into_read_only_directory_does_not_raise(tmp_path):
    folder = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        heartbeat.beat("app", folder)
        heartbeat.write_pass(NOW, None, None, folder)
    finally:
        folder.chmod(stat.S_IRWXU)
    assert heartbeat.age("app", folder) is None


def test_directory_is_none_for_in_memory_database(settings, monkeypatch):
    database(monkeypatch, settings, ":memory:")
    assert heartbeat.directory() is None
    database(monkeypatch, settings, "file:memdb1?mode=memory&cache=shared")
    assert heartbeat.directory() is None


def test_directory_is_none_for_unusable_name(settings, monkeypatch):
    database(monkeypatch, settings, "")
    assert heartbeat.directory() is None
    monkeypatch.delitem(settings.DATABASES["default"], "NAME")
    assert heartbeat.directory() is None


def test_directory_is_the_parent_of_the_database_file(settings, monkeypatch, tmp_path):
    database(monkeypatch, settings, str(tmp_path / "db.sqlite3"))
    assert heartbeat.directory() == tmp_path
    database(monkeypatch, settings, tmp_path / "db.sqlite3")
    assert heartbeat.directory() == tmp_path


def test_default_directory_is_used_when_none_given(settings, monkeypatch, tmp_path):
    database(monkeypatch, settings, str(tmp_path / "db.sqlite3"))
    heartbeat.beat("app")
    assert heartbeat.age("app", tmp_path) is not None
    heartbeat.clear("app")
    assert heartbeat.age("app", tmp_path) is None


def test_pass_record_round_trips(tmp_path):
    started, finished = NOW - timedelta(minutes=3), NOW
    heartbeat.write_pass(started, finished, "ok", tmp_path)
    assert heartbeat.read_pass(tmp_path) == heartbeat.PassRecord(started, finished, "ok")


def test_unfinished_pass_record_keeps_finished_none(tmp_path):
    heartbeat.write_pass(NOW, None, None, tmp_path)
    record = heartbeat.read_pass(tmp_path)
    assert record == heartbeat.PassRecord(NOW, None, None)
    assert record is not None and record.finished is None


def test_pass_record_is_replaced_atomically_without_leftovers(tmp_path):
    heartbeat.write_pass(NOW, None, None, tmp_path)
    heartbeat.write_pass(NOW, NOW, "failed", tmp_path)
    assert heartbeat.read_pass(tmp_path) == heartbeat.PassRecord(NOW, NOW, "failed")
    assert len(list(tmp_path.iterdir())) == 1


def test_read_pass_is_none_without_or_with_broken_file(tmp_path):
    assert heartbeat.read_pass(tmp_path) is None
    heartbeat.write_pass(NOW, NOW, "ok", tmp_path)
    (record_file,) = list(tmp_path.iterdir())
    record_file.write_text("{not json")
    assert heartbeat.read_pass(tmp_path) is None
    record_file.write_text('{"started": "yesterday"}')
    assert heartbeat.read_pass(tmp_path) is None
    assert heartbeat.read_pass(tmp_path / "missing") is None


def finished_ago(tmp_path: Path, seconds: float) -> None:
    finished = NOW - timedelta(seconds=seconds)
    heartbeat.write_pass(finished - timedelta(seconds=60), finished, "ok", tmp_path)


def test_jobs_healthy_by_last_finish(tmp_path):
    finished_ago(tmp_path, 7199)
    assert heartbeat.jobs_healthy(NOW, tmp_path)
    finished_ago(tmp_path, 7201)
    assert not heartbeat.jobs_healthy(NOW, tmp_path)


def test_jobs_healthy_by_start_without_finish(tmp_path):
    heartbeat.write_pass(NOW - timedelta(seconds=3599), None, None, tmp_path)
    assert heartbeat.jobs_healthy(NOW, tmp_path)
    heartbeat.write_pass(NOW - timedelta(seconds=3601), None, None, tmp_path)
    assert not heartbeat.jobs_healthy(NOW, tmp_path)


def test_a_first_pass_after_a_long_stop_is_judged_by_its_start(tmp_path):
    """AC-144: a long backup after days of downtime must not trip the healthcheck."""
    old_finish = NOW - timedelta(days=3)
    heartbeat.write_pass(NOW - timedelta(seconds=60), old_finish, "ok", tmp_path)
    assert heartbeat.jobs_healthy(NOW, tmp_path)
    heartbeat.write_pass(NOW - timedelta(seconds=3599), old_finish, "ok", tmp_path)
    assert heartbeat.jobs_healthy(NOW, tmp_path)
    heartbeat.write_pass(NOW - timedelta(seconds=3601), old_finish, "ok", tmp_path)
    assert not heartbeat.jobs_healthy(NOW, tmp_path)


def test_an_old_finish_without_a_pass_in_progress_is_unhealthy(tmp_path):
    finished_ago(tmp_path, 7201)
    assert not heartbeat.jobs_healthy(NOW, tmp_path)
    finished_ago(tmp_path, 60)
    assert heartbeat.jobs_healthy(NOW, tmp_path)


def test_jobs_healthy_with_no_record_or_nothing_readable(tmp_path):
    assert heartbeat.jobs_healthy(NOW, tmp_path)
    assert heartbeat.jobs_healthy(NOW, tmp_path / "missing")
    assert heartbeat.jobs_healthy(NOW, None)


def test_jobs_healthy_ignores_naive_record_time(tmp_path):
    heartbeat.write_pass(datetime(2020, 1, 1), datetime(2020, 1, 1), "ok", tmp_path)
    assert heartbeat.jobs_healthy(NOW, tmp_path)


def test_check_exit_codes(settings, tmp_path, monkeypatch):
    database(monkeypatch, settings, str(tmp_path / "db.sqlite3"))
    assert heartbeat.main(["check"]) == 0
    heartbeat.write_pass(NOW - timedelta(days=1), NOW - timedelta(days=1), "ok", tmp_path)
    assert heartbeat.main(["check"]) == 1
    assert heartbeat.main([]) == 2


def run_check(folder):
    import subprocess
    import sys

    root = Path(heartbeat.__file__).resolve().parents[2]
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "app.settings",
        "KVZ_SECRET_KEY": "x" * 50,
        "KVZ_DB_PATH": str(folder / "db.sqlite3"),
    }
    command = [sys.executable, "-m", "app.domain.heartbeat", "check"]
    return subprocess.run(command, cwd=root, env=env, capture_output=True)


def test_check_runs_as_a_module_without_database(tmp_path):
    done = run_check(tmp_path)
    assert done.returncode == 0, done.stderr


def test_check_as_a_module_fails_on_a_stale_record_and_passes_on_a_fresh_one(tmp_path):
    """AC-144: the command the healthcheck runs reads the record beside the database file."""
    now = datetime.now(UTC)
    stale = now - timedelta(seconds=heartbeat.FINISH_LIMIT_SECONDS + 600)
    heartbeat.write_pass(stale - timedelta(seconds=5), stale, "ok", tmp_path)
    failing = run_check(tmp_path)
    assert failing.returncode == 1, failing.stderr

    fresh = now - timedelta(minutes=5)
    heartbeat.write_pass(fresh - timedelta(seconds=5), fresh, "ok", tmp_path)
    passing = run_check(tmp_path)
    assert passing.returncode == 0, passing.stderr


def set_jobs_heartbeat_age(tmp_path: Path, seconds: float) -> None:
    heartbeat.beat("jobs", tmp_path)
    moment = NOW.timestamp() - seconds
    os.utime(tmp_path / ".kvz-heartbeat-jobs", (moment, moment))


def test_a_stale_jobs_heartbeat_is_unhealthy(tmp_path):
    """A stuck loop stops beating even when the last pass record still looks fine."""
    finished_ago(tmp_path, 60)
    set_jobs_heartbeat_age(tmp_path, 3 * heartbeat.JOBS_INTERVAL - 1)
    assert heartbeat.jobs_healthy(NOW, tmp_path)
    set_jobs_heartbeat_age(tmp_path, 3 * heartbeat.JOBS_INTERVAL + 1)
    assert not heartbeat.jobs_healthy(NOW, tmp_path)


def test_a_missing_jobs_heartbeat_with_a_fresh_record_is_healthy(tmp_path):
    """First start: the record exists but the first beat has not been written yet."""
    finished_ago(tmp_path, 60)
    assert not (tmp_path / ".kvz-heartbeat-jobs").exists()
    assert heartbeat.jobs_healthy(NOW, tmp_path)
