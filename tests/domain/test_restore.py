"""A manual restore that verifies the backup first and keeps the data it replaces (D5)."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from app.domain import backup, heartbeat

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=5)
DAY = timedelta(days=1)


@pytest.fixture
def places(settings, tmp_path):
    settings.KVZ_BACKUP_PATH = str(tmp_path / "backups")
    settings.KVZ_MEDIA_PATH = str(tmp_path / "media")
    Path(settings.KVZ_MEDIA_PATH).mkdir()
    return Path(settings.KVZ_BACKUP_PATH), Path(settings.KVZ_MEDIA_PATH)


@pytest.fixture
def source(file_db, places):
    """The live database and one photo."""
    file_db.execute("insert into app_setting (key, value_json) values ('probe', '1')")
    (places[1] / "one.webp").write_bytes(b"photo one")
    return file_db


def make(source, now=NOW):
    return backup.create(now, database_path=source.path)


def keys(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as connection:
        return {row[0] for row in connection.execute("select key from app_setting")}


def tree(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drift(source, places):
    """Change the live data after the backup: a row more, a photo gone, another one added."""
    source.execute("insert into app_setting (key, value_json) values ('later', '2')")
    (places[1] / "one.webp").unlink()
    (places[1] / "two.webp").write_bytes(b"photo two")


def restore(source, directory, now=LATER):
    return backup.restore(directory, now, database_path=source.path)


def pre_restore_directories(places):
    return sorted(places[0].glob("pre-restore*"))


def test_restore_brings_back_the_rows_and_media_of_the_backup(source, places):
    """AC-15, AC-135: a restore from a backup is verified: its rows and photos are back, intact."""
    rows_then = keys(source.path)
    directory = make(source)
    drift(source, places)

    report = restore(source, directory)

    assert keys(source.path) == rows_then
    assert tree(places[1]) == {"one.webp": b"photo one"}
    assert report.database_bytes == source.path.stat().st_size
    assert report.media_files == 1
    with closing(source.connect()) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        connection.execute("insert into app_setting (key, value_json) values ('after', '3')")
    assert {path.name for path in source.path.parent.glob("live*")} <= {
        "live.sqlite3",
        "live.sqlite3-wal",
        "live.sqlite3-shm",
    }, "no staging file is left next to the database"


def test_restore_keeps_the_previous_data_in_pre_restore(source, places):
    """AC-135: the data a restore replaces is kept in pre-restore."""
    directory = make(source)
    drift(source, places)

    report = restore(source, directory)

    assert report.previous.parent == places[0]
    assert report.previous.name == "pre-restore-20261110T080000Z"
    assert pre_restore_directories(places) == [report.previous]
    assert {"later", "probe"} <= keys(report.previous / "live.sqlite3")
    assert tree(report.previous / "media") == {"two.webp": b"photo two"}


def test_the_stash_copies_the_files_beside_the_database_too(source, places):
    """A restore never gets here with a log beside the database (it refuses first), so the stash
    is tried directly: whatever lies beside the database file is kept."""
    places[0].mkdir()
    for suffix in ("-wal", "-shm"):
        source.path.with_name(source.path.name + suffix).write_bytes(b"side" + suffix.encode())

    previous = backup._stash(source.path, places[1], NOW)

    assert (previous / "live.sqlite3-wal").read_bytes() == b"side-wal"
    assert (previous / "live.sqlite3-shm").read_bytes() == b"side-shm"
    assert (previous / "live.sqlite3").read_bytes() == source.path.read_bytes()
    assert tree(previous / "media") == tree(places[1])


def test_restore_refuses_while_another_connection_is_open(source, places):
    """AC-135: in write-ahead mode an idle reader neither blocks nor is blocked by the exclusive
    lock; what gives it away is the log and the shared-memory file that stay until the last one
    closes."""
    directory = make(source)
    drift(source, places)
    rows_now, media_now = keys(source.path), tree(places[1])
    idle = source.connect()
    idle.execute("select count(*) from app_setting").fetchall()
    try:
        with pytest.raises(backup.BackupError, match="in use") as raised:
            restore(source, directory)
    finally:
        idle.close()

    message = str(raised.value)
    assert "deployment.md" in message and "app and jobs" in message
    assert "sqlite3" not in message, "the image has no sqlite3 program"
    assert str(places[0]) not in message
    assert keys(source.path) == rows_now
    assert tree(places[1]) == media_now
    assert pre_restore_directories(places) == []
    assert restore(source, directory).media_files == 1, "after a clean stop it goes through"


def test_the_log_a_crash_left_is_folded_in_and_kept(source, places, tmp_path):
    """A process that died leaves its log; the first connection recovers it, so the restore sees
    the rows and keeps them in pre-restore, and nothing is left beside the new database."""
    directory = make(source)
    crashed = tmp_path / "crashed"
    crashed.mkdir()
    with closing(source.connect()) as holder:
        holder.execute("insert into app_setting (key, value_json) values ('unsaved', '1')")
        holder.execute("select count(*) from app_setting").fetchall()
        for suffix in ("", "-wal"):  # what a killed process would have left on disk
            shutil.copyfile(
                source.path.with_name(source.path.name + suffix),
                crashed / f"live.sqlite3{suffix}",
            )

    report = backup.restore(directory, LATER, database_path=crashed / "live.sqlite3")

    assert "unsaved" in keys(report.previous / "live.sqlite3")
    assert "unsaved" not in keys(crashed / "live.sqlite3")
    assert sorted(path.name for path in crashed.iterdir()) == ["live.sqlite3"]


def test_restore_refuses_a_corrupted_backup_and_changes_nothing(source, places):
    """AC-135: a damaged backup is refused and nothing changes."""
    directory = make(source)
    drift(source, places)
    rows_now, media_now = keys(source.path), tree(places[1])
    photo = directory / "media" / "one.webp"
    photo.unlink()
    photo.write_bytes(b"not the photo")

    with pytest.raises(backup.BackupError):
        restore(source, directory)

    assert keys(source.path) == rows_now
    assert tree(places[1]) == media_now
    assert pre_restore_directories(places) == []


def test_restore_refuses_while_the_database_is_locked(source, places, monkeypatch):
    monkeypatch.setattr(backup, "LOCK_PROBE_SECONDS", 0.1)
    directory = make(source)
    drift(source, places)
    rows_now, media_now = keys(source.path), tree(places[1])
    other = source.connect()
    other.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(backup.BackupError, match="in use"):
            restore(source, directory)
    finally:
        other.execute("ROLLBACK")
        other.close()

    assert keys(source.path) == rows_now
    assert tree(places[1]) == media_now
    assert pre_restore_directories(places) == []


def test_restore_refuses_a_backup_from_an_older_schema(source, places):
    """AC-135: a backup of an older schema is refused and nothing changes."""
    source.execute("delete from django_migrations where app = 'domain' and name like '0019%'")
    directory = make(source)
    assert backup.verify(directory) is None, "an older schema is a sound backup, only not here"
    drift(source, places)
    rows_now, media_now = keys(source.path), tree(places[1])

    with pytest.raises(backup.BackupError, match="older version"):
        restore(source, directory)

    assert keys(source.path) == rows_now
    assert tree(places[1]) == media_now
    assert pre_restore_directories(places) == []


def test_a_failure_halfway_puts_the_previous_data_back(source, places, monkeypatch):
    """AC-135: a restore that fails halfway puts the previous data back."""
    (places[1] / "sub").mkdir()
    (places[1] / "sub" / "deep.webp").write_bytes(b"deep")
    directory = make(source)
    drift(source, places)
    rows_now, media_now = keys(source.path), tree(places[1])
    original = backup._copy_file
    copied = []

    def failing(src, destination):
        if Path(src).is_relative_to(directory) and Path(src).name != backup.DATABASE:
            copied.append(Path(src).name)
            if len(copied) == 2:
                raise RuntimeError(f"disk trouble at {src}")
        original(src, destination)

    monkeypatch.setattr(backup, "_copy_file", failing)

    with pytest.raises(backup.BackupError) as raised:
        restore(source, directory)

    assert len(copied) == 2, "the failure came after the database and one photo were replaced"
    assert str(raised.value) == "The restore failed and the previous data was put back"
    assert "RuntimeError" not in str(raised.value) and "disk trouble" not in str(raised.value)
    assert keys(source.path) == rows_now
    assert tree(places[1]) == media_now
    assert len(pre_restore_directories(places)) == 1, "the copy stays for the operator"


def test_root_puts_the_previous_media_back_with_the_owner_of_the_media_directory(
    source, places, monkeypatch
):
    (places[1] / "sub").mkdir()
    (places[1] / "sub" / "deep.webp").write_bytes(b"deep")
    directory = make(source)
    owners: dict[Path, tuple[int, int]] = {}
    monkeypatch.setattr(backup, "_is_root", lambda: True)
    monkeypatch.setattr(
        backup, "_chown", lambda path, uid, gid: owners.update({Path(path): (uid, gid)})
    )
    original = backup._copy_file
    seen = []

    def failing(src, destination):
        if Path(src).is_relative_to(directory) and Path(src).name != backup.DATABASE:
            seen.append(src)
            if len(seen) == 2:
                raise RuntimeError
        original(src, destination)

    monkeypatch.setattr(backup, "_copy_file", failing)
    owners.clear()

    with pytest.raises(backup.BackupError, match="put back"):
        restore(source, directory)

    mine = (os.getuid(), os.getgid())
    assert owners[places[1] / "sub"] == mine
    assert owners[places[1] / "sub" / "deep.webp"] == mine


def test_a_failed_put_back_says_where_the_previous_data_is(source, places, monkeypatch):
    directory = make(source)
    drift(source, places)
    original = backup._copy_file

    def failing(src, destination):
        if Path(src).is_relative_to(directory) and Path(src).name != backup.DATABASE:
            raise RuntimeError("first")
        if Path(src).is_relative_to(places[0] / "pre-restore-20261110T080000Z"):
            raise RuntimeError("second")
        original(src, destination)

    monkeypatch.setattr(backup, "_copy_file", failing)

    with pytest.raises(backup.BackupError, match="pre-restore directory"):
        restore(source, directory)

    assert (places[0] / "pre-restore-20261110T080000Z" / "media" / "two.webp").read_bytes() == (
        b"photo two"
    )


def test_restored_files_are_owned_by_the_data_owner(source, places):
    """AC-135: restored files belong to the owner of the data directory."""
    directory = make(source)

    report = restore(source, directory)

    for path, folder in ((source.path, source.path.parent), (places[1] / "one.webp", places[1])):
        assert path.stat().st_uid == folder.stat().st_uid
        assert path.stat().st_gid == folder.stat().st_gid
    assert report.warning == ""


def test_root_gives_the_restored_files_to_uid_1000(source, places, monkeypatch):
    (places[1] / "sub").mkdir()
    (places[1] / "sub" / "deep.webp").write_bytes(b"deep")
    directory = make(source)
    owners: dict[Path, tuple[int, int]] = {}
    monkeypatch.setattr(backup, "_is_root", lambda: True)
    monkeypatch.setattr(
        backup, "_chown", lambda path, uid, gid: owners.update({Path(path): (uid, gid)})
    )

    report = restore(source, directory)

    assert owners[source.path] == (1000, 1000)
    assert owners[places[1] / "one.webp"] == (1000, 1000)
    assert owners[places[1] / "sub" / "deep.webp"] == (1000, 1000)
    assert owners[places[1] / "sub"] == (1000, 1000)
    assert places[1] not in owners and source.path.parent not in owners, "never the volume roots"
    assert report.warning == ""


def test_a_refused_chown_is_not_a_failure_and_a_foreign_owner_is_a_warning(
    source, places, monkeypatch
):
    directory = make(source)
    monkeypatch.setattr(backup, "_is_root", lambda: True)

    def refused(path, uid, gid):
        raise PermissionError

    monkeypatch.setattr(backup, "_chown", refused)
    monkeypatch.setattr(backup, "DATA_OWNER", (os.getuid() + 1, os.getgid() + 1))

    quiet = restore(source, directory)
    assert quiet.warning == "", "owned by the owner of the data directory: nothing to warn about"

    uid = backup._uid
    monkeypatch.setattr(
        backup, "_uid", lambda path: 4242 if path.name == "live.sqlite3" else uid(path)
    )
    report = restore(source, directory, LATER + DAY)

    assert "owned by uid" in report.warning
    assert keys(source.path)


def test_restore_never_hard_links_media_out_of_a_backup(source, places):
    """AC-135: restored media are copies, never links into a backup."""
    first = make(source, NOW - DAY)
    second = make(source)  # links the photo of the first
    shared = second / "media" / "one.webp"
    assert shared.stat().st_ino == (first / "media" / "one.webp").stat().st_ino
    before = {directory: sha(directory / "media" / "one.webp") for directory in (first, second)}

    restore(source, second)
    restored = places[1] / "one.webp"
    assert restored.stat().st_ino != shared.stat().st_ino
    assert restored.stat().st_nlink == 1
    with restored.open("r+b") as stream:
        stream.write(b"CHANGED!!")

    for directory in (first, second):
        assert sha(directory / "media" / "one.webp") == before[directory]
        assert backup.verify(directory) is None


def test_restore_fsyncs_what_it_writes(source, places, monkeypatch):
    (places[1] / "sub").mkdir()
    (places[1] / "sub" / "deep.webp").write_bytes(b"deep")
    directory = make(source)
    synced: list[Path] = []
    original = backup._sync

    def recording(path):
        synced.append(Path(path))
        original(path)

    monkeypatch.setattr(backup, "_sync", recording)

    report = restore(source, directory)

    assert {
        source.path,
        source.path.parent,
        places[1] / "one.webp",
        places[1] / "sub" / "deep.webp",
        places[1] / "sub",
        places[1],
    } <= set(synced)
    assert report.previous in synced


def test_restore_waits_for_no_backup(source, places):
    directory = make(source)
    drift(source, places)
    rows_now, media_now = keys(source.path), tree(places[1])
    with (places[0] / ".lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(backup.BackupError) as raised:
            restore(source, directory)

    assert str(raised.value) == "Another backup is running"
    assert keys(source.path) == rows_now
    assert tree(places[1]) == media_now
    assert pre_restore_directories(places) == []


def test_restore_does_not_hold_the_lock_afterwards(source, places):
    directory = make(source)
    restore(source, directory)
    make(source, LATER)  # would be refused while the lock was still held


def test_latest_picks_the_newest_complete_backup(source, places):
    """AC-135: latest names the newest complete backup."""
    oldest = make(source, NOW - 2 * DAY)
    middle = make(source, NOW - DAY)
    newest = make(source)
    (places[0] / ".tmp-2026-11-11").mkdir()
    (places[0] / "2026-11-12").mkdir()  # no manifest: not complete
    (places[0] / "pre-restore-20261111T000000Z").mkdir()

    assert backup.resolve("latest") == newest
    assert backup.resolve("2026-11-09") == middle
    assert backup.resolve("2026-11-08") == oldest


@pytest.mark.parametrize("choice", ["2000-01-01", "../2026-11-10", "tomorrow", "2026-13-40", ""])
def test_unknown_date_is_a_clear_error(source, places, choice):
    make(source)

    with pytest.raises(backup.BackupError, match="no complete backup"):
        backup.resolve(choice)


def test_latest_without_any_backup_is_a_clear_error(places):
    with pytest.raises(backup.BackupError, match="no complete backup"):
        backup.resolve("latest")


def test_the_command_names_the_date_and_the_previous_directory(source, places):
    from tests.support.run import run_manage

    make(source)
    drift(source, places)

    result = run_manage(
        "restore",
        "latest",
        db=source.path,
        env={"KVZ_BACKUP_PATH": str(places[0]), "KVZ_MEDIA_PATH": str(places[1])},
    )

    text = result.stdout
    assert result.returncode == 0, result.stderr[-500:]
    assert "2026-11-10" in text and "pre-restore-" in text and "1 media files" in text
    assert str(places[0]) not in text
    assert tree(places[1]) == {"one.webp": b"photo one"}


def test_the_command_reports_a_refusal_as_a_command_error(source, places):
    with pytest.raises(CommandError, match="no complete backup"):
        call_command("restore", "2000-01-01")


def test_a_damaged_backup_hints_at_an_older_date(source, places):
    make(source, NOW - DAY)
    newest = make(source)
    photo = newest / "media" / "one.webp"
    photo.unlink()
    photo.write_bytes(b"not the photo")

    with pytest.raises(CommandError, match=r"restore YYYY-MM-DD") as raised:
        call_command("restore", "latest")

    assert "differs from the manifest" in str(raised.value)
    assert str(places[0]) not in str(raised.value)


def test_one_file_that_cannot_be_given_away_does_not_stop_the_others(source, places, monkeypatch):
    (places[1] / "sub").mkdir()
    (places[1] / "sub" / "deep.webp").write_bytes(b"deep")
    directory = make(source)
    owners: dict[Path, tuple[int, int]] = {}
    monkeypatch.setattr(backup, "_is_root", lambda: True)

    def chown(path, uid, gid):
        if Path(path).name == "one.webp":
            raise OSError(22, "Invalid argument")
        if Path(path).name == "deep.webp":
            raise PermissionError
        owners[Path(path)] = (uid, gid)

    monkeypatch.setattr(backup, "_chown", chown)

    report = restore(source, directory)

    assert owners[source.path] == (1000, 1000)
    assert owners[places[1] / "sub"] == (1000, 1000), "it went on after the first two refusals"
    assert report.media_files == 2
    assert tree(places[1]) == {"one.webp": b"photo one", "sub/deep.webp": b"deep"}


def test_the_ownership_warning_covers_the_folders_too(source, places, monkeypatch):
    (places[1] / "sub").mkdir()
    (places[1] / "sub" / "deep.webp").write_bytes(b"deep")
    directory = make(source)
    uid = backup._uid
    monkeypatch.setattr(backup, "_uid", lambda path: 4242 if path.name == "sub" else uid(path))

    report = restore(source, directory)

    assert "owned by uid" in report.warning


def test_the_new_database_is_staged_before_the_old_log_goes(source, places, monkeypatch):
    directory = make(source)
    order: list[str] = []
    unlink = Path.unlink
    replace = os.replace
    copy = backup._copy_file

    def watching_unlink(self, *args, **kwargs):
        if self.name.endswith(("-wal", "-shm")):
            order.append("unlink side file")
        return unlink(self, *args, **kwargs)

    def watching_copy(src, destination):
        if str(destination).endswith(".restoring"):
            order.append("staged")
        copy(src, destination)

    def watching_replace(src, destination):
        order.append("replaced")
        replace(src, destination)

    monkeypatch.setattr(Path, "unlink", watching_unlink)
    monkeypatch.setattr(backup, "_copy_file", watching_copy)
    monkeypatch.setattr(os, "replace", watching_replace)

    restore(source, directory)

    assert order.index("staged") < order.index("unlink side file") < order.index("replaced")


def test_the_backup_is_read_without_opening_it_for_writing(tmp_path):
    missing = tmp_path / "missing.sqlite3"

    with pytest.raises(sqlite3.OperationalError):
        backup._applied(missing)

    assert not missing.exists(), "a read-only open does not create a file"


def test_the_put_back_writes_what_it_restores_to_disk(source, places, monkeypatch):
    (places[1] / "sub").mkdir()
    (places[1] / "sub" / "deep.webp").write_bytes(b"deep")
    directory = make(source)
    drift(source, places)
    original = backup._copy_file
    synced: list[Path] = []
    real_sync = backup._sync
    copied = []

    def failing(src, destination):
        if Path(src).is_relative_to(directory) and Path(src).name != backup.DATABASE:
            copied.append(src)
            if len(copied) == 2:
                synced.clear()  # only what the put-back flushes is of interest
                raise RuntimeError
        original(src, destination)

    def recording(path):
        synced.append(Path(path))
        real_sync(path)

    monkeypatch.setattr(backup, "_copy_file", failing)
    monkeypatch.setattr(backup, "_sync", recording)

    with pytest.raises(backup.BackupError, match="put back"):
        restore(source, directory)

    assert source.path in synced, "the database file itself, not only its directory"
    assert places[1] / "two.webp" in synced


def test_the_command_run_as_a_process_does_not_count_its_own_connection_as_use(source, places):
    """`manage.py` runs the system checks first and they open a connection that leaves `-wal`.

    A restore that took its own start-up for a second user would refuse every time on a real
    deployment; `call_command` skips the checks, so only a process shows it.
    """
    from tests.support.run import run_manage

    make(source)
    drift(source, places)

    result = run_manage(
        "restore",
        "latest",
        db=source.path,
        env={"KVZ_BACKUP_PATH": str(places[0]), "KVZ_MEDIA_PATH": str(places[1])},
    )

    assert result.returncode == 0, result.stderr[-500:]
    assert tree(places[1]) == {"one.webp": b"photo one"}


def lay_transient_files(media):
    (media / "exports" / "job").mkdir(parents=True)
    (media / "exports" / "job" / "results.zip").write_bytes(b"e-mails and photos")
    (media / "imports").mkdir()
    (media / "imports" / "y.csv").write_bytes(b"a;b")
    return tree(media / "exports"), tree(media / "imports")


def test_a_restore_leaves_the_export_and_import_files_where_they_are(source, places):
    """AC-135: transient files are neither in a backup nor replaced, stashed or put back."""
    directory = make(source)
    exports, imports = lay_transient_files(places[1])
    drift(source, places)

    report = restore(source, directory)

    assert tree(places[1] / "exports") == exports
    assert tree(places[1] / "imports") == imports
    assert tree(places[1]) == {"one.webp": b"photo one"} | {
        f"exports/{name}": data for name, data in exports.items()
    } | {f"imports/{name}": data for name, data in imports.items()}
    assert tree(report.previous / "media") == {"two.webp": b"photo two"}


def test_a_restore_ignores_transient_files_that_an_older_backup_holds(source, places):
    directory = make(source)
    manifest = json.loads((directory / "manifest.json").read_text())
    stale = directory / "media" / "exports" / "old" / "results.zip"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"from before the fix")
    manifest["files"]["media/exports/old/results.zip"] = {
        "size": stale.stat().st_size,
        "sha256": sha(stale),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    exports, _ = lay_transient_files(places[1])

    restore(source, directory)

    assert tree(places[1] / "exports") == exports


def test_a_failed_restore_puts_back_everything_but_leaves_transient_files(
    source, places, monkeypatch
):
    directory = make(source)
    exports, imports = lay_transient_files(places[1])
    drift(source, places)
    original = backup._copy_file

    def failing(src, destination):
        if Path(src).is_relative_to(directory) and Path(src).name != backup.DATABASE:
            raise RuntimeError
        original(src, destination)

    monkeypatch.setattr(backup, "_copy_file", failing)
    with pytest.raises(backup.BackupError, match="put back"):
        restore(source, directory)

    assert (places[1] / "two.webp").read_bytes() == b"photo two"
    assert not (places[1] / "one.webp").exists()
    assert tree(places[1] / "exports") == exports
    assert tree(places[1] / "imports") == imports


def age_heartbeat(source, name, seconds):
    heartbeat.beat(name, source.path.parent)
    path = source.path.parent / f".kvz-heartbeat-{name}"
    stamp = path.stat().st_mtime - seconds
    os.utime(path, (stamp, stamp))


@pytest.mark.parametrize("name", ["app", "jobs"])
def test_restore_refuses_beside_a_live_service(source, places, name):
    """AC-143: an idle `app` or `jobs` leaves no log file, but its heartbeat gives it away."""
    directory = make(source)
    drift(source, places)
    rows_now, media_now = keys(source.path), tree(places[1])
    age_heartbeat(source, name, 5)

    with pytest.raises(backup.BackupError, match="counts as stopped") as raised:
        restore(source, directory)

    message = str(raised.value)
    assert f"The {name} service" in message
    seconds = int(re.search(r"in (\d+) s", message).group(1))
    assert 50 <= seconds <= 56
    assert str(source.path.parent) not in message and str(places[0]) not in message
    assert keys(source.path) == rows_now
    assert tree(places[1]) == media_now
    assert pre_restore_directories(places) == []


def test_restore_accepts_a_heartbeat_older_than_a_minute(source, places):
    directory = make(source)
    drift(source, places)
    age_heartbeat(source, "app", heartbeat.STALE_SECONDS + 1)
    age_heartbeat(source, "jobs", 3600)
    assert restore(source, directory).media_files == 1


def test_restore_accepts_no_heartbeat_at_all(source, places):
    directory = make(source)
    assert restore(source, directory).media_files == 1


def test_the_heartbeat_is_looked_for_beside_the_restored_file_not_in_the_settings(
    source, places, tmp_path
):
    """A restore of any database path looks beside that file."""
    directory = make(source)
    other = tmp_path / "elsewhere"
    other.mkdir()
    heartbeat.beat("app", other)
    assert restore(source, directory).media_files == 1


class Died(BaseException):
    """What a kill, a shutdown or a Ctrl-C is to the code: not an `Exception`."""


MARKED = "pre-restore-20261110T080000Z"


def marker_of(places):
    return places[0] / MARKED / backup.MARKER


def interrupt_install(monkeypatch, *, put_back):
    """The install dies halfway; `put_back` is what the put-back does afterwards."""

    def dying(*args, **kwargs):
        raise Died

    monkeypatch.setattr(backup, "_install", dying)
    monkeypatch.setattr(backup, "_put_back", put_back)


def died_put_back(*args):
    raise Died


def test_the_marker_is_written_after_the_stash_and_before_the_install(source, places, monkeypatch):
    """AC-143: the marker names the backup and is on disk before anything live is replaced."""
    directory = make(source)
    seen = {}
    synced: list[Path] = []
    original_install, original_sync = backup._install, backup._sync

    def watching_install(*args, **kwargs):
        seen["marker"] = marker_of(places).read_text()
        seen["synced"] = list(synced)
        return original_install(*args, **kwargs)

    def recording(path):
        synced.append(Path(path))
        original_sync(path)

    monkeypatch.setattr(backup, "_install", watching_install)
    monkeypatch.setattr(backup, "_sync", recording)

    restore(source, directory)

    assert seen["marker"].strip() == directory.name
    assert marker_of(places) in seen["synced"] and places[0] / MARKED in seen["synced"]
    assert synced.index(marker_of(places)) > synced.index(places[0]), "after the stash was synced"


def test_a_successful_restore_leaves_no_marker(source, places):
    directory = make(source)
    drift(source, places)

    restore(source, directory)

    assert pre_restore_directories(places) == [places[0] / MARKED]
    assert not marker_of(places).exists()
    assert backup._marked() == []


def test_a_failed_restore_that_put_the_data_back_leaves_no_marker(source, places, monkeypatch):
    directory = make(source)
    drift(source, places)
    original = backup._copy_file

    def failing(src, destination):
        if Path(src).is_relative_to(directory) and Path(src).name != backup.DATABASE:
            raise RuntimeError("disk trouble")
        original(src, destination)

    monkeypatch.setattr(backup, "_copy_file", failing)

    with pytest.raises(backup.BackupError, match="was put back"):
        restore(source, directory)

    assert (places[0] / MARKED).is_dir()
    assert not marker_of(places).exists()


def test_a_failed_put_back_keeps_the_marker(source, places, monkeypatch):
    directory = make(source)
    drift(source, places)

    def failing(*args, **kwargs):
        raise OSError("disk trouble")

    monkeypatch.setattr(backup, "_install", failing)
    monkeypatch.setattr(backup, "_put_back", lambda *args: False)

    with pytest.raises(backup.BackupError, match="could not be put back"):
        restore(source, directory)

    assert marker_of(places).read_text().strip() == directory.name


@pytest.mark.parametrize("put_back", [died_put_back, lambda *args: False])
def test_a_process_that_dies_keeps_the_marker_and_the_next_restore_refuses(
    source, places, monkeypatch, put_back
):
    """AC-143: after a killed restore the next one refuses instead of stashing half-way data."""
    directory = make(source)
    drift(source, places)
    interrupt_install(monkeypatch, put_back=put_back)

    with pytest.raises(Died):
        restore(source, directory)

    assert marker_of(places).is_file()
    monkeypatch.undo()
    rows_now, media_now = keys(source.path), tree(places[1])

    with pytest.raises(backup.BackupError) as raised:
        restore(source, directory, now=LATER + timedelta(hours=1))

    message = str(raised.value)
    assert MARKED in message and "docs/deployment.md" in message and "Restore" in message
    assert "only remove the marker" in message and "otherwise put that data back" in message
    assert str(places[0]) not in message and str(source.path.parent) not in message
    assert keys(source.path) == rows_now
    assert tree(places[1]) == media_now
    assert pre_restore_directories(places) == [places[0] / MARKED], "no second stash"


def test_the_refusal_names_every_marked_directory_and_no_path(source, places, monkeypatch):
    directory = make(source)
    interrupt_install(monkeypatch, put_back=died_put_back)
    with pytest.raises(Died):
        restore(source, directory)
    monkeypatch.undo()
    second = places[0] / "pre-restore-20261110T090000Z"
    second.mkdir()
    (second / backup.MARKER).write_text("x\n")

    with pytest.raises(backup.BackupError) as raised:
        restore(source, directory)

    message = str(raised.value)
    assert MARKED in message and second.name in message
    assert str(places[0]) not in message and str(source.path.parent) not in message


def test_the_refusal_comes_before_the_backup_is_even_checked(source, places, monkeypatch):
    directory = make(source)
    interrupt_install(monkeypatch, put_back=died_put_back)
    with pytest.raises(Died):
        restore(source, directory)
    monkeypatch.undo()

    with pytest.raises(backup.BackupError, match=MARKED):
        restore(source, places[0] / "2000-01-01")


def test_a_marker_blocks_however_old_it_is(source, places, monkeypatch):
    directory = make(source)
    interrupt_install(monkeypatch, put_back=died_put_back)
    with pytest.raises(Died):
        restore(source, directory)
    monkeypatch.undo()
    stamp = (LATER - 400 * DAY).timestamp()
    os.utime(places[0] / MARKED, (stamp, stamp))
    os.utime(marker_of(places), (stamp, stamp))

    with pytest.raises(backup.BackupError, match=MARKED):
        restore(source, directory)


def test_removing_the_marker_lets_the_next_restore_run(source, places, monkeypatch):
    directory = make(source)
    interrupt_install(monkeypatch, put_back=died_put_back)
    with pytest.raises(Died):
        restore(source, directory)
    monkeypatch.undo()
    marker_of(places).unlink()

    assert restore(source, directory, now=LATER + timedelta(hours=1)).media_files == 1


def test_a_crash_inside_the_stash_leaves_no_marker_and_no_directory(source, places, monkeypatch):
    directory = make(source)
    drift(source, places)
    original = backup._copy_file

    def failing(src, destination):
        if Path(src).is_relative_to(places[1]):
            raise Died
        original(src, destination)

    monkeypatch.setattr(backup, "_copy_file", failing)

    with pytest.raises(Died):
        restore(source, directory)

    assert pre_restore_directories(places) == []
    assert backup._marked() == []
    monkeypatch.undo()
    assert restore(source, directory).media_files == 1, "nothing blocks the next restore"


def test_a_marker_that_cannot_be_written_leaves_the_live_data_alone(source, places, monkeypatch):
    directory = make(source)
    drift(source, places)
    rows_now, media_now = keys(source.path), tree(places[1])

    def failing(*args):
        raise Died

    monkeypatch.setattr(backup, "_install", failing)
    monkeypatch.setattr(backup, "_mark", failing)

    with pytest.raises(Died):
        restore(source, directory)

    assert keys(source.path) == rows_now and tree(places[1]) == media_now
    assert not marker_of(places).exists()
