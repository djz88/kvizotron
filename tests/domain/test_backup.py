"""A daily backup of the database and the media that is verified before it counts (D5)."""

import fcntl
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain import backup

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # 04:00 in Prague: the local date is the 10th
DAY = timedelta(days=1)


@pytest.fixture
def places(settings, tmp_path):
    settings.KVZ_BACKUP_PATH = str(tmp_path / "backups")
    settings.KVZ_MEDIA_PATH = str(tmp_path / "media")
    Path(settings.KVZ_MEDIA_PATH).mkdir()
    return Path(settings.KVZ_BACKUP_PATH), Path(settings.KVZ_MEDIA_PATH)


@pytest.fixture
def source(file_db, places):
    """The live database and one photo, ready to be backed up."""
    file_db.execute("insert into app_setting (key, value_json) values ('probe', '1')")
    (places[1] / "one.webp").write_bytes(b"photo one")
    return file_db


def make(now=NOW, source=None, **kwargs):
    return backup.create(now, database_path=source.path, **kwargs)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("select count(*) from app_setting").fetchone()[0]


def rewrite_manifest(directory: Path, change) -> None:
    manifest = json.loads((directory / "manifest.json").read_text())
    change(manifest)
    (directory / "manifest.json").write_text(json.dumps(manifest))


def test_a_backup_has_a_database_copy_media_and_a_manifest(source, places):
    """AC-134: a backup holds a database copy, the media and a manifest, and verifies."""
    directory = make(source=source)

    assert directory == places[0] / "2026-11-10"
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["created"] == "2026-11-10T04:00:00+01:00"
    assert "domain.0001_initial" in manifest["schema"]
    assert set(manifest["files"]) == {"db.sqlite3", "media/one.webp"}
    for name, entry in manifest["files"].items():
        assert entry == {"size": (directory / name).stat().st_size, "sha256": sha(directory / name)}
    assert (directory / "media" / "one.webp").read_bytes() == b"photo one"
    assert not list(places[0].glob(".tmp-*"))


def test_the_copy_is_a_consistent_database(source, places):
    source.execute("insert into app_setting (key, value_json) values ('two', '2')")
    directory = make(source=source)

    with closing(sqlite3.connect(directory / "db.sqlite3")) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert copy.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    assert count(directory / "db.sqlite3") == count(source.path)
    assert not list(directory.glob("db.sqlite3-*")), "the copy is one self-contained file"


@contextmanager
def writing(source):
    """Another connection committing two rows per transaction, hardly pausing, until the end."""
    stop = threading.Event()
    started = threading.Event()
    failures: list[BaseException] = []

    def writer():
        try:
            with closing(source.connect()) as connection:
                number = 0
                while not stop.is_set():
                    number += 1
                    connection.execute("BEGIN IMMEDIATE")
                    for part in range(2):
                        connection.execute(
                            "insert into app_setting (key, value_json) values (?, '1')",
                            (f"w{number}-{part}",),
                        )
                    connection.execute("COMMIT")
                    started.set()
                    time.sleep(0.002)
        except BaseException as exc:  # noqa: BLE001 - reported below
            failures.append(exc)
            started.set()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert started.wait(5)
        yield
    finally:
        stop.set()
        thread.join(10)
    assert not failures


def test_a_backup_is_taken_while_another_thread_writes(source, places):
    with writing(source):
        directory = make(source=source)

    copied = count(directory / "db.sqlite3")
    assert (copied - 1) % 2 == 0, "a transaction is in the copy whole or not at all"
    assert copied > 1
    assert backup.verify(directory) is None


def test_a_copy_that_a_writer_keeps_restarting_is_given_up(source, places, monkeypatch):
    """AC-134: the database copy has a deadline and a late one is given up."""
    monkeypatch.setattr(backup, "DATABASE_COPY_SECONDS", 0.0)
    monkeypatch.setattr(backup, "PAGES_PER_STEP", 1)  # several steps, so a restart can happen
    started = time.monotonic()
    with writing(source), pytest.raises(backup.BackupError):
        make(source=source)

    assert time.monotonic() - started < 10
    assert [path for path in places[0].iterdir() if path.name != ".lock"] == []
    monkeypatch.undo()
    assert make(source=source).name == "2026-11-10", "the lock was released, the next pass retries"


def test_unchanged_media_are_hard_linked_and_changed_ones_copied(source, places):
    media = places[1]
    (media / "two.webp").write_bytes(b"photo two")
    first = make(NOW - DAY, source)

    (media / "two.webp").write_bytes(b"the same key, other content")
    (media / "three.webp").write_bytes(b"new photo")
    second = make(NOW, source)

    def inode(directory, name):
        return (directory / "media" / name).stat().st_ino

    assert inode(first, "one.webp") == inode(second, "one.webp")
    assert inode(first, "two.webp") != inode(second, "two.webp")
    assert (first / "media" / "two.webp").read_bytes() == b"photo two"
    assert (second / "media" / "two.webp").read_bytes() == b"the same key, other content"
    assert (second / "media" / "three.webp").read_bytes() == b"new photo"
    assert backup.verify(first) is None
    assert backup.verify(second) is None


def test_a_failing_link_falls_back_to_a_copy(source, places, monkeypatch):
    first = make(NOW - DAY, source)

    def refused(*_args, **_kwargs):
        raise OSError("cross-device link")

    monkeypatch.setattr(backup.os, "link", refused)
    second = make(NOW, source)

    assert (second / "media" / "one.webp").stat().st_ino != (
        first / "media" / "one.webp"
    ).stat().st_ino
    assert (second / "media" / "one.webp").read_bytes() == b"photo one"


def test_a_file_that_vanishes_during_the_backup_is_left_out(source, places, monkeypatch):
    (places[1] / "gone.webp").write_bytes(b"deleted meanwhile")
    real = shutil.copy2

    def vanishing(path, destination):
        if Path(path).name == "gone.webp":
            Path(path).unlink()
        return real(path, destination)

    monkeypatch.setattr(backup.shutil, "copy2", vanishing)
    directory = make(source=source)

    manifest = json.loads((directory / "manifest.json").read_text())
    assert set(manifest["files"]) == {"db.sqlite3", "media/one.webp"}
    assert not (directory / "media" / "gone.webp").exists()


def test_the_temporary_file_of_an_upload_is_not_backed_up(source, places):
    (places[1] / "tmpab12cd34").write_bytes(b"half an upload")

    directory = make(source=source)

    assert set(json.loads((directory / "manifest.json").read_text())["files"]) == {
        "db.sqlite3",
        "media/one.webp",
    }


def test_the_manifest_describes_the_file_as_written(source, places):
    directory = make(source=source)

    manifest = json.loads((directory / "manifest.json").read_text())
    photo = directory / "media" / "one.webp"
    assert manifest["files"]["media/one.webp"] == {
        "size": photo.stat().st_size,
        "sha256": sha(photo),
    }


def test_a_failure_leaves_no_complete_directory(source, places, monkeypatch):
    """AC-134: a backup that fails leaves no directory that looks complete."""
    earlier = make(NOW - DAY, source)

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(backup, "_copy_database", broken)
    with pytest.raises(backup.BackupError):
        make(NOW, source)

    assert sorted(path.name for path in places[0].iterdir() if path.is_dir()) == [earlier.name]
    assert backup.verify(earlier) is None
    assert backup.due(NOW) is True


def test_a_killed_backup_is_ignored(source, places):
    complete = make(NOW - DAY, source)
    (places[0] / ".tmp-2026-11-10").mkdir()
    (places[0] / ".tmp-2026-11-10" / "db.sqlite3").write_bytes(b"half")
    (places[0] / "pre-restore").mkdir()
    (places[0] / "2026-11-09-notes").mkdir()

    assert backup.listing() == [complete]
    assert backup.due(NOW) is True
    assert make(NOW, source) == places[0] / "2026-11-10", "the next run starts over"
    assert not (places[0] / ".tmp-2026-11-10").exists()


def test_a_second_backup_on_one_date_replaces_the_first(source, places):
    make(NOW, source)
    source.execute("insert into app_setting (key, value_json) values ('later', '3')")

    directory = make(NOW + timedelta(hours=1), source)

    assert count(directory / "db.sqlite3") == 2
    assert [path.name for path in places[0].iterdir() if path.is_dir()] == ["2026-11-10"]


def test_two_backups_at_once_are_refused(source, places):
    places[0].mkdir(exist_ok=True)
    with (places[0] / ".lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        (places[0] / ".tmp-2026-11-10").mkdir()
        with pytest.raises(backup.BackupError):
            make(source=source)
        assert (places[0] / ".tmp-2026-11-10").exists(), "what the other run builds is not touched"


def test_verify_refuses_a_changed_file(source, places):
    """AC-134: a file that differs from the manifest fails the verification."""
    directory = make(source=source)
    photo = directory / "media" / "one.webp"
    photo.unlink()  # not written in place: the file may be shared with another backup
    photo.write_bytes(b"photo 1")

    with pytest.raises(backup.BackupError):
        backup.verify(directory)


def test_verify_refuses_a_missing_manifest_or_file(source, places):
    directory = make(source=source)
    (directory / "media" / "one.webp").unlink()
    with pytest.raises(backup.BackupError):
        backup.verify(directory)
    (directory / "manifest.json").unlink()
    with pytest.raises(backup.BackupError):
        backup.verify(directory)


def test_verify_refuses_a_damaged_database(source, places):
    directory = make(source=source)
    database = directory / "db.sqlite3"
    data = bytearray(database.read_bytes())
    data[4096 * 3 : 4096 * 3 + 64] = os.urandom(64)  # a page inside the file
    database.write_bytes(bytes(data))
    rewrite_manifest(
        directory,
        lambda manifest: manifest["files"]["db.sqlite3"].update(sha256=sha(database)),
    )

    with pytest.raises(backup.BackupError):
        backup.verify(directory)


def test_verify_refuses_unknown_migrations(source, places):
    source.execute(
        "insert into django_migrations (app, name, applied)"
        " values ('domain', '9999_from_the_future', '2026-01-01')"
    )
    with pytest.raises(backup.BackupError):
        make(source=source)
    assert backup.listing() == []


def test_verify_accepts_a_copy_with_fewer_migrations(source, places):
    source.execute("delete from django_migrations where name like '0019%'")
    assert backup.verify(make(source=source)) is None


def test_prune_deletes_old_ones_by_days(source, places):
    """AC-136: a backup older than the retention days is deleted, a newer one is kept."""
    old = make(NOW - 40 * DAY, source)
    edge = make(NOW - 30 * DAY, source)
    recent = make(NOW - 5 * DAY, source)
    newest = make(NOW, source)
    stale = places[0] / "pre-restore-2026-09-01"
    fresh = places[0] / "pre-restore"
    for directory, age in ((stale, 45), (fresh, 1)):
        directory.mkdir()
        stamp = (NOW - age * DAY).timestamp()
        os.utime(directory, (stamp, stamp))

    removed = backup.prune(NOW, 30).removed

    assert set(removed) == {old, stale}
    assert not old.exists() and not stale.exists()
    assert edge.exists() and recent.exists() and newest.exists() and fresh.exists()
    assert backup.listing() == [newest, recent, edge]


def test_prune_keeps_a_marked_pre_restore_whatever_its_age(source, places):
    """AC-143: the data of an interrupted restore is never pruned; an unmarked copy still is."""
    make(NOW, source)
    marked = places[0] / "pre-restore-20250101T000000Z"
    plain = places[0] / "pre-restore-20250102T000000Z"
    for directory in (marked, plain):
        directory.mkdir()
    (marked / backup.MARKER).write_text("2026-11-10")
    stamp = (NOW - 400 * DAY).timestamp()
    for directory in (marked, plain):
        os.utime(directory, (stamp, stamp))

    removed = backup.prune(NOW, 30).removed

    assert removed == [plain]
    assert marked.is_dir() and (marked / backup.MARKER).is_file() and not plain.exists()


def test_prune_keeps_the_newest_valid_backup_whatever_the_clock(source, places):
    """AC-136: the newest backup that verifies is never pruned."""
    older = make(NOW - DAY, source)
    newest = make(NOW, source)

    removed = backup.prune(NOW + 400 * DAY, 30).removed

    assert removed == [older]
    assert backup.listing() == [newest]
    assert backup.prune(NOW + 800 * DAY, 30).removed == []
    assert backup.verify(newest) is None


def test_prune_keeps_the_newest_valid_one_when_a_newer_one_is_damaged(source, places):
    """AC-136: a damaged newer backup does not cost the last good one."""
    good = make(NOW - 60 * DAY, source)
    damaged = make(NOW - 50 * DAY, source)
    (damaged / "db.sqlite3").unlink()

    assert backup.prune(NOW, 30).removed == [damaged]
    assert backup.listing() == [good]


def test_prune_sweeps_what_a_killed_backup_left(source, places):
    make(NOW, source)
    stray = places[0] / ".tmp-2026-10-01"
    stray.mkdir()
    stamp = (NOW - 3 * DAY).timestamp()
    os.utime(stray, (stamp, stamp))
    running = places[0] / ".tmp-2026-11-10"
    running.mkdir()
    os.utime(running, (NOW.timestamp(), NOW.timestamp()))

    assert backup.prune(NOW, 30).removed == [stray]
    assert running.exists()


def test_due_is_true_once_per_local_date(source, places):
    assert backup.due(NOW) is True

    make(NOW, source)

    assert backup.due(NOW) is False
    assert backup.due(NOW + timedelta(hours=18)) is False  # 22:00 on the 10th in Prague
    assert backup.due(NOW + timedelta(hours=21)) is True  # 01:00 on the 11th in Prague
    assert backup.due(NOW + DAY) is True


def test_the_directory_is_named_by_the_local_date(source, places):
    late = datetime(2026, 11, 10, 23, 30, tzinfo=UTC)  # already the 11th in Prague

    assert make(late, source).name == "2026-11-11"


def test_errors_are_logged_by_type_only(source, places, monkeypatch, caplog, tmp_path):
    def broken(*_args, **_kwargs):
        raise PermissionError(f"{tmp_path}/secret-place with value 4711")

    monkeypatch.setattr(backup, "_copy_database", broken)
    with caplog.at_level(logging.INFO), pytest.raises(backup.BackupError) as raised:
        make(source=source)

    assert "PermissionError" in caplog.text
    for text in (caplog.text, str(raised.value)):
        assert str(tmp_path) not in text
        assert "secret-place" not in text
        assert "4711" not in text


def test_a_memory_database_cannot_be_backed_up(places):
    with pytest.raises(backup.BackupError):
        backup.create(NOW)
    assert not list(places[0].glob(".tmp-*"))


def test_the_settings_have_defaults(tmp_path):
    """Read in a fresh process without any KVZ_* variable, so the environment cannot change them."""
    from tests.support.run import run_python

    result = run_python(
        "from django.conf import settings\n"
        "print(settings.KVZ_BACKUP_PATH, settings.KVZ_BACKUP_RETENTION_DAYS)\n",
        db=tmp_path / "db.sqlite3",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["/data/backups", "30"]


def test_a_damaged_file_in_the_newest_backup_is_copied_not_linked(source, places):
    """The manifest of the newest backup still matches the live file; the file in it does not."""
    (places[1] / "two.webp").write_bytes(b"photo two")
    first = make(NOW - DAY, source)
    damaged = first / "media" / "one.webp"
    damaged.unlink()  # not written in place: the inode may be shared with other backups
    damaged.write_bytes(b"bit rot")
    damaged_inode = damaged.stat().st_ino

    second = make(NOW, source)

    assert backup.verify(second) is None
    assert (second / "media" / "one.webp").read_bytes() == b"photo one"
    assert (second / "media" / "one.webp").stat().st_ino != damaged_inode
    assert (second / "media" / "two.webp").stat().st_ino == (
        first / "media" / "two.webp"
    ).stat().st_ino, "what is sound is still linked"
    with pytest.raises(backup.BackupError):
        backup.verify(first)


def test_a_missing_file_in_the_newest_backup_is_copied_too(source, places):
    first = make(NOW - DAY, source)
    (first / "media" / "one.webp").unlink()

    second = make(NOW, source)

    assert backup.verify(second) is None
    assert (second / "media" / "one.webp").read_bytes() == b"photo one"


def test_transient_export_and_import_files_are_not_backed_up(source, places):
    """AC-134: privacy.md bounds a downloaded export by 24 hours; a backup must not keep it."""
    media = places[1]
    (media / "exports" / "job").mkdir(parents=True)
    (media / "exports" / "job" / "results.zip").write_bytes(b"e-mails and photos")
    (media / "imports").mkdir()
    (media / "imports" / "y.csv").write_bytes(b"a;b")
    (media / "sub").mkdir()
    (media / "sub" / "exports").write_bytes(b"a photo whose name happens to be exports")

    directory = make(source=source)

    manifest = json.loads((directory / "manifest.json").read_text())
    assert set(manifest["files"]) == {
        "db.sqlite3",
        "media/one.webp",
        "media/sub/exports",
    }
    assert not (directory / "media" / "exports").exists()
    assert not (directory / "media" / "imports").exists()


def test_the_command_makes_a_backup_and_prunes(source, places, monkeypatch, capsys):
    from django.core.management import call_command

    old = make(NOW - 90 * DAY, source)
    real = backup.create
    monkeypatch.setattr(backup, "create", lambda now: real(now, database_path=source.path))
    call_command("backup")

    out = capsys.readouterr().out
    assert "2 files" in out
    assert not old.exists()
    assert len(backup.listing()) == 1


def test_the_command_reports_a_failed_backup(places, monkeypatch):
    from django.core.management import CommandError, call_command

    def refused(now):
        raise backup.BackupError("no")

    monkeypatch.setattr(backup, "create", refused)
    with pytest.raises(CommandError):
        call_command("backup")


def test_everything_is_on_disk_before_the_directory_gets_its_name(source, places, monkeypatch):
    """AC-134: a power cut cannot leave a dated directory that is only partly on disk."""
    (places[1] / "sub").mkdir()
    (places[1] / "sub" / "two.webp").write_bytes(b"photo two")
    events: list[tuple] = []
    real_sync, real_rename = backup._sync, os.rename

    def sync(path):
        events.append(("sync", Path(path)))
        real_sync(path)

    def rename(origin, destination):
        events.append(("rename", Path(origin), Path(destination)))
        real_rename(origin, destination)

    monkeypatch.setattr(backup, "_sync", sync)
    monkeypatch.setattr(backup.os, "rename", rename)
    directory = make(source=source)

    temporary = places[0] / ".tmp-2026-11-10"
    published = events.index(("rename", temporary, directory))
    before = {event[1].relative_to(temporary).as_posix() for event in events[:published]}
    assert before == {
        ".",
        "db.sqlite3",
        "manifest.json",
        "media",
        "media/one.webp",
        "media/sub",
        "media/sub/two.webp",
    }
    assert ("sync", places[0]) in events[published + 1 :], "the new name is on disk too"


def test_a_manifest_that_does_not_parse_does_not_count(source, places):
    torn = places[0] / "2026-11-10"
    torn.mkdir(parents=True)
    (torn / "manifest.json").write_text('{"created": "2026-11')

    assert backup.listing() == []
    assert backup.due(NOW) is True


SECRET = "/srv/secret-place-7f3a"


def failing(*_args, **_kwargs):
    raise PermissionError(SECRET)


def assert_only_the_type_is_reported(caplog, raised=None):
    assert "PermissionError" in caplog.text
    assert SECRET not in caplog.text
    if raised is not None:
        assert SECRET not in str(raised.value)


def test_a_failure_to_create_the_directory_is_a_backup_error(source, places, monkeypatch, caplog):
    real = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if self == places[0]:
            failing()
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    with pytest.raises(backup.BackupError) as raised:
        make(source=source)

    assert_only_the_type_is_reported(caplog, raised)


def test_a_failure_to_open_the_lock_is_a_backup_error(source, places, monkeypatch, caplog):
    places[0].mkdir()
    real = Path.open

    def opening(self, *args, **kwargs):
        if self.name == ".lock":
            failing()
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(backup.BackupError) as raised:
        make(source=source)
    assert_only_the_type_is_reported(caplog, raised)
    caplog.clear()
    with pytest.raises(backup.BackupError) as raised:
        backup.prune(NOW, 30)
    assert_only_the_type_is_reported(caplog, raised)


def test_a_refused_second_backup_is_logged(source, places, caplog):
    places[0].mkdir()
    with (places[0] / ".lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(backup.BackupError):
            make(source=source)
        with pytest.raises(backup.BackupError):
            backup.prune(NOW, 30)

    assert caplog.text.count("Another backup is running") == 2


def test_a_directory_that_cannot_be_deleted_is_logged_and_the_rest_goes_on(
    source, places, monkeypatch, caplog
):
    first = make(NOW - 60 * DAY, source)
    second = make(NOW - 50 * DAY, source)
    newest = make(NOW, source)
    calls = []

    def refusing(path, *args, **kwargs):
        calls.append(path)
        failing()

    monkeypatch.setattr(backup.shutil, "rmtree", refusing)
    result = backup.prune(NOW, 30)

    assert result.removed == []
    assert sorted(result.stayed) == [first, second]
    assert sorted(calls) == [first, second]
    assert first.exists() and second.exists() and newest.exists()
    assert_only_the_type_is_reported(caplog)


def test_prune_says_what_stayed_and_what_it_removed(source, places, monkeypatch):
    """AC-145: one directory that cannot be deleted is in `stayed`, the others in `removed`."""
    stuck = make(NOW - 60 * DAY, source)
    gone = make(NOW - 50 * DAY, source)
    newest = make(NOW, source)
    real = shutil.rmtree

    def selective(path, *args, **kwargs):
        if Path(path) == stuck:
            failing()
        return real(path, *args, **kwargs)

    monkeypatch.setattr(backup.shutil, "rmtree", selective)
    result = backup.prune(NOW, 30)

    assert result.removed == [gone]
    assert result.stayed == [stuck]
    assert stuck.exists() and not gone.exists() and newest.exists()


def test_the_command_fails_after_the_backup_when_old_ones_stayed(
    source, places, monkeypatch, capsys
):
    """AC-145: `backup` prints the backup, warns with the count only and exits non-zero."""
    from django.core.management import CommandError, call_command

    old = make(NOW - 90 * DAY, source)
    real = backup.create
    monkeypatch.setattr(backup, "create", lambda now: real(now, database_path=source.path))

    real_remove = shutil.rmtree

    def refusing(path, *args, **kwargs):
        if Path(path) == old:
            failing()
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(backup.shutil, "rmtree", refusing)
    with pytest.raises(CommandError) as raised:
        call_command("backup")

    captured = capsys.readouterr()
    assert "Backup made" in captured.out
    assert captured.err.count("\n") == 1
    assert "1" in captured.err
    assert old.name not in captured.err + str(raised.value)
    assert str(places[0]) not in captured.err + str(raised.value)
    assert old.exists(), "the backup that was made stays valid"


def test_the_command_reports_a_failed_prune(source, places, monkeypatch):
    from django.core.management import CommandError, call_command

    real = backup.create
    monkeypatch.setattr(backup, "create", lambda now: real(now, database_path=source.path))

    def refused(now, days):
        raise backup.BackupError("no")

    monkeypatch.setattr(backup, "prune", refused)
    with pytest.raises(CommandError):
        call_command("backup")


def test_an_interrupted_replacement_is_undone(source, places):
    first = make(NOW, source)
    first.rename(places[0] / ".replaced-2026-11-10")  # killed between the two renames
    assert backup.listing() == []

    later = make(NOW + DAY, source)

    assert backup.listing() == [later, first], "the old backup of the 10th is back under its name"
    assert backup.verify(first) is None


def test_an_interrupted_replacement_is_undone_before_the_same_date_is_made_again(source, places):
    (places[0] / ".replaced-2026-11-10").mkdir(parents=True)  # nothing that verifies
    assert make(NOW, source).name == "2026-11-10"


def test_prune_never_deletes_the_newest_backup_when_none_verifies(source, places):
    """AC-136: when none verifies, the newest by date stays."""
    older = make(NOW - 60 * DAY, source)
    newest = make(NOW - 50 * DAY, source)
    for directory in (older, newest):
        (directory / "db.sqlite3").unlink()

    assert backup.prune(NOW, 30).removed == [older]
    assert backup.listing() == [newest]
