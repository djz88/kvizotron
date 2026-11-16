"""The daily backup of the database and the media (D5).

A backup is a directory `<KVZ_BACKUP_PATH>/YYYY-MM-DD` (local date) with the database copy
`db.sqlite3`, the media files under `media/` and `manifest.json` (creation time, applied
migrations, size and sha256 of every file). It is built as `.tmp-<date>`, verified and only then
renamed, so a directory with a date for a name is always complete and a killed run leaves a
`.tmp-*` that nothing lists. The database is copied with SQLite's online backup API in small page
steps, never as a file, so a writer is neither stopped nor starved. Media files that the previous
backup already holds unchanged, and still sound there, are hard-linked, so every backup is complete
on its own and costs only what changed. The directories `exports` and `imports` under the media
root hold files that the application removes within a day (a results export with e-mails and
photos, an uploaded import): they are neither backed up nor touched by a restore.

`restore` puts a backup back: it verifies the backup, refuses while the database is in use or the
backup is of an older schema, copies the current data into `pre-restore-<time>` next to the backups,
replaces the contents of the database file and the media directory (never the directories, which
may be mount points) with copies from the backup (never links: media files are shared between
backups) and puts the previous data back when anything fails on the way. Once the copy of the
previous data is complete and before anything live is replaced, the file `.restoring` goes into
`pre-restore-<time>`; it is removed when the restore ends or the previous data are back. While one
exists (a killed or failed restore) another restore refuses and `prune` keeps that directory.

Logs carry the exception type only: a message can hold a path or a value.
"""

import fcntl
import hashlib
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.migrations.loader import MigrationLoader

from app.domain import clock, heartbeat

logger = logging.getLogger(__name__)

DATABASE = "db.sqlite3"
MEDIA = "media"
MANIFEST = "manifest.json"
PAGES_PER_STEP = 100
DATABASE_COPY_SECONDS = 300  # a copy that restarts for longer than this is given up and retried
STRAY_AGE = timedelta(days=1)  # a `.tmp-*` older than this belongs to a run that was killed
LOCK_PROBE_SECONDS = 2.0  # how long a restore waits for the database before it calls it in use
DATA_OWNER = (1000, 1000)  # uid and gid of the user that the application runs as
_SIDE_FILES = ("", "-wal", "-shm")  # the database file and the files SQLite keeps beside it
MARKER = ".restoring"  # in a `pre-restore-*` directory: a restore that did not finish
TRANSIENT = ("exports", "imports")  # directly under the media root: files that live for hours
_IN_USE = (
    "The database is in use: stop caddy, app and jobs before a restore. If they are all stopped"
    " and the -wal and -shm files remain beside the database, open and close the database once"
    " with the python one-liner in docs/deployment.md (section Restore) and run the restore again"
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

Files = dict[str, dict[str, Any]]


class BackupError(Exception):
    """A backup that cannot be made or does not verify. The message never holds a path or value."""


@dataclass
class RestoreReport:
    database_bytes: int
    media_files: int
    previous: Path  # where the replaced data went
    warning: str = ""  # something the operator should know, such as files that are not owned right


def root() -> Path:
    return Path(settings.KVZ_BACKUP_PATH)


def _date_of(directory: Path) -> date | None:
    if not _DATE.fullmatch(directory.name):
        return None
    try:
        return date.fromisoformat(directory.name)
    except ValueError:
        return None


def listing() -> list[Path]:
    """Complete backups, newest first.

    A directory gets a date for a name only after it verified and was written to disk; a manifest
    that does not parse (a torn write) does not count. `verify` is the real check.
    """
    if not root().is_dir():
        return []
    found = [
        path
        for path in root().iterdir()
        if path.is_dir() and _date_of(path) and _has_manifest(path)
    ]
    return sorted(found, key=lambda path: path.name, reverse=True)


def _has_manifest(directory: Path) -> bool:
    try:
        _read_manifest(directory)
    except BackupError:
        return False
    return True


def due(now: datetime) -> bool:
    """True when no complete backup exists for the local date of `now`."""
    return clock.local_date(now).isoformat() not in {path.name for path in listing()}


def create(now: datetime, database_path: Path | None = None) -> Path:
    """Make today's backup and return its directory; raise `BackupError` and leave nothing behind.

    `database_path` names the SQLite file; by default it is the configured database, which must be
    a file. A second backup on the same date replaces the first once it has verified. Every
    failure, whatever raised it, is a `BackupError` with a fixed message and is logged by type.
    """
    with _reported("backup"):
        source = _database_file(database_path)
        root().mkdir(mode=0o750, parents=True, exist_ok=True)
        name = clock.local_date(now).isoformat()
        with _exclusive():
            _recover_replaced()
            temporary = root() / f".tmp-{name}"
            shutil.rmtree(temporary, ignore_errors=True)
            try:
                previous = _previous()
                temporary.mkdir(mode=0o750)
                _copy_database(source, temporary / DATABASE)
                files: Files = {DATABASE: _describe(temporary / DATABASE)}
                files.update(_copy_media(temporary, previous))
                manifest = {
                    "created": clock.iso(now),
                    "schema": [
                        f"{app}.{migration}" for app, migration in _applied(temporary / DATABASE)
                    ],
                    "files": files,
                }
                (temporary / MANIFEST).write_text(json.dumps(manifest, indent=2))
                verify(temporary)
                _sync_tree(temporary)
                final = _publish(temporary, root() / name)
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
    logger.info("Backup %s made: %d files", name, len(files))
    return final


@contextmanager
def _reported(task: str) -> Iterator[None]:
    """Whatever fails becomes a `BackupError` with a fixed message; the log gets the type only."""
    try:
        yield
    except BackupError as exc:
        logger.error("The %s failed: %s", task, exc)
        raise
    except Exception as exc:
        logger.error("The %s failed: %s", task, type(exc).__name__)
        raise BackupError(f"The {task} failed ({type(exc).__name__})") from None


def verify(directory: Path) -> None:
    """Raise `BackupError` unless the manifest, every checksum and the database copy are sound."""
    files = _read_manifest(directory)
    for name, entry in files.items():
        parts = Path(name).parts
        if Path(name).is_absolute() or ".." in parts:
            raise BackupError("The manifest names a file outside the backup")
        path = directory / name
        try:
            matches = (
                path.is_file()
                and path.stat().st_size == entry["size"]
                and _sha256(path) == entry["sha256"]
            )
        except OSError, KeyError, TypeError:
            matches = False
        if not matches:
            raise BackupError("A file is missing or differs from the manifest")
    if DATABASE not in files:
        raise BackupError("The manifest has no database")
    _check_database(directory / DATABASE)


def resolve(choice: str) -> Path:
    """The complete backup that `YYYY-MM-DD` or `latest` names; `BackupError` when there is none."""
    found = listing()
    if choice == "latest" and found:
        return found[0]
    for path in found:
        if _DATE.fullmatch(choice) and path.name == choice:
            return path
    raise BackupError(
        "There is no complete backup for that date; the dated ones are in the backups"
    )


def file_count(directory: Path) -> int:
    return len(_read_manifest(directory))


@dataclass
class PruneResult:
    """What `prune` deleted and what it meant to delete but could not."""

    removed: list[Path] = field(default_factory=list)
    stayed: list[Path] = field(default_factory=list)


def prune(now: datetime, days: int) -> PruneResult:
    """Delete what is older than `days`, except the newest backup that still verifies.

    Dated backups age by their date, `pre-restore*` directories and the leftovers of killed runs by
    their modification time. However far ahead the clock is, the newest valid backup stays; when
    none verifies, the newest by date stays. It takes the lock of `create`, so they never race. A
    directory that cannot be deleted is logged by type, listed in `stayed`, and the rest goes on.
    """
    result = PruneResult()
    if not root().is_dir():
        return result
    with _reported("backup pruning"), _exclusive():
        complete = listing()
        keep = next((path for path in complete if _verifies(path)), None)
        if keep is None and complete:
            keep = complete[0]
        today = clock.local_date(now)
        for path in complete:
            taken = _date_of(path)
            if path != keep and taken is not None and (today - taken).days > days:
                _remove(path, result)
        for path in sorted(root().iterdir()):
            pre_restore = path.name.startswith("pre-restore")
            if not path.is_dir() or not (
                pre_restore or path.name.startswith((".tmp-", ".replaced-"))
            ):
                continue
            if pre_restore and (path / MARKER).exists():  # an interrupted restore: never by age
                continue
            if _older(path, now, timedelta(days=days) if pre_restore else STRAY_AGE):
                _remove(path, result)
        return result


def _older(path: Path, now: datetime, limit: timedelta) -> bool:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC) < now - limit


def _remove(path: Path, result: PruneResult) -> None:
    try:
        shutil.rmtree(path)
    except OSError as exc:
        logger.error("A backup directory could not be deleted: %s", type(exc).__name__)
        result.stayed.append(path)
    else:
        result.removed.append(path)


def _verifies(directory: Path) -> bool:
    try:
        verify(directory)
    except BackupError:
        return False
    return True


def _database_file(database_path: Path | None) -> Path:
    chosen = str(database_path or settings.DATABASES["default"]["NAME"])
    path = Path(chosen)
    if chosen.startswith(":memory:") or not path.is_file():
        raise BackupError("The database is not a file that can be backed up")
    return path


@contextmanager
def _exclusive() -> Iterator[None]:
    """One backup at a time, whichever process starts it (the `jobs` loop or a command)."""
    with (root() / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError("Another backup is running") from None
        yield


def _copy_database(source: Path, target: Path) -> None:
    """A consistent copy through the backup API; the copy is one file, without a journal."""
    deadline = time.monotonic() + DATABASE_COPY_SECONDS

    def give_up_when_late(_status: int, _remaining: int, _total: int) -> None:
        # A writer that commits between two steps restarts the copy; this bounds the restarts.
        if time.monotonic() >= deadline:
            raise BackupError("The database copy took too long")

    with closing(sqlite3.connect(source, timeout=20)) as live:
        with closing(sqlite3.connect(target)) as copy:
            live.backup(copy, pages=PAGES_PER_STEP, progress=give_up_when_late)
            copy.execute("PRAGMA journal_mode=DELETE")
    os.chmod(target, 0o640)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _describe(path: Path) -> dict[str, Any]:
    return {"size": path.stat().st_size, "sha256": _sha256(path)}


def _previous() -> tuple[Path | None, Files]:
    """The newest backup and what its manifest lists; nothing when it cannot be read."""
    for path in listing()[:1]:
        try:
            return path, _read_manifest(path)
        except BackupError:
            break
    return None, {}


def _transient(relative: Path) -> bool:
    """True for what lies in `exports/` or `imports/` directly under the media root."""
    return len(relative.parts) > 1 and relative.parts[0] in TRANSIENT


def _sound(existing: Path, entry: dict[str, Any]) -> bool:
    """The file in an earlier backup is what its manifest says: a link must never carry damage."""
    try:
        return _describe(existing) == entry
    except OSError:
        return False


def _copy_media(target: Path, previous: tuple[Path | None, Files]) -> Files:
    """Link what the previous backup holds unchanged (path, size, checksum), copy the rest.

    The manifest describes the file as it was written into the backup, not as it was before. A
    temporary file of an upload in progress is skipped: it is not a photo yet, and so are the
    export and import files (`TRANSIENT`). The manifest is not trusted for a link: the file in the
    earlier backup is checked against it, and a damaged or missing one is copied from the live file.
    """
    held, listed = previous
    media = Path(settings.KVZ_MEDIA_PATH)
    files: Files = {}
    if not media.is_dir():
        return files
    for path in sorted(media.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.name.startswith(tempfile.template):
            continue
        if _transient(path.relative_to(media)):
            continue
        name = f"{MEDIA}/{path.relative_to(media).as_posix()}"
        destination = target / name
        try:
            destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            before = listed.get(name)
            if held is not None and before is not None and before == _describe(path):
                if _sound(held / name, before) and _linked(held / name, destination):
                    files[name] = before
                    continue
            shutil.copy2(path, destination)
            files[name] = _describe(destination)
        except FileNotFoundError:  # deleted while the backup ran: it is not part of it
            destination.unlink(missing_ok=True)
    return files


def _linked(existing: Path, destination: Path) -> bool:
    """Hard-link `existing` as `destination`; False when that is not possible, then it is copied."""
    try:
        os.link(existing, destination)
    except OSError:
        return False
    return True


def _sync(path: Path) -> None:
    """Flush a file or a directory entry list to disk."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_tree(directory: Path) -> None:
    """Write every file and every directory of the backup to disk before it gets its name."""
    for folder, subfolders, names in os.walk(directory):
        for name in names + subfolders:
            if not (Path(folder) / name).is_symlink():
                _sync(Path(folder) / name)
    _sync(directory)


def _recover_replaced() -> None:
    """Undo a crash between the two renames of a replacement: the old backup is the date's again."""
    for path in sorted(root().glob(".replaced-*")):
        final = root() / path.name.removeprefix(".replaced-")
        if path.is_dir() and not final.exists() and _verifies(path):
            os.rename(path, final)


def _publish(temporary: Path, final: Path) -> Path:
    """Rename the verified, synced directory into place; an older backup of the date is replaced."""
    replaced = final.with_name(f".replaced-{final.name}")
    if final.exists():
        shutil.rmtree(replaced, ignore_errors=True)
        os.rename(final, replaced)
    try:
        os.rename(temporary, final)
    except OSError:
        if replaced.exists():
            os.rename(replaced, final)
        raise
    _sync(final.parent)
    shutil.rmtree(replaced, ignore_errors=True)
    return final


def _read_manifest(directory: Path) -> Files:
    try:
        files = json.loads((directory / MANIFEST).read_text())["files"]
    except OSError, ValueError, KeyError, TypeError:
        raise BackupError("The manifest is missing or unreadable") from None
    if not isinstance(files, dict):
        raise BackupError("The manifest is missing or unreadable")
    return files


def _applied(database: Path) -> list[tuple[str, str]]:
    with closing(
        sqlite3.connect(f"{database.absolute().as_uri()}?mode=ro", uri=True)
    ) as connection:
        rows = connection.execute("select app, name from django_migrations order by id").fetchall()
    return [(app, name) for app, name in rows]


def _check_database(database: Path) -> None:
    """Integrity of the copy, and no migration that the installed code does not have."""
    try:
        with closing(
            sqlite3.connect(f"{database.absolute().as_uri()}?mode=ro", uri=True)
        ) as connection:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise BackupError("The database copy fails its integrity check")
            applied = connection.execute("select app, name from django_migrations").fetchall()
    except sqlite3.Error:
        raise BackupError("The database copy cannot be read") from None
    known = set(MigrationLoader(None, ignore_no_migrations=True).disk_migrations)
    if set(applied) - known:
        raise BackupError("The database copy has migrations this version does not know")


def restore(directory: Path, now: datetime, database_path: Path | None = None) -> RestoreReport:
    """Put the backup `directory` in the place of the live database and media.

    Nothing changes unless the backup verifies, is not of an older schema and the database is not in
    use. The data it replaces is copied to `pre-restore-<time>` first; when anything fails after
    that, the previous data is put back and a `BackupError` with a fixed message is raised. It holds
    the lock of `create` and `prune`, so it never runs beside a backup. `database_path` names the
    live SQLite file; by default it is the configured database.
    """
    with _reported("restore"):
        live = _live_database(database_path)
        media = Path(settings.KVZ_MEDIA_PATH)
        with _exclusive():
            _refuse_while_marked()
            try:
                verify(directory)
            except BackupError as exc:
                raise BackupError(
                    f"{exc}; this backup cannot be restored, try an older one with"
                    " restore YYYY-MM-DD"
                ) from None
            _require_current_schema(directory / DATABASE)
            _require_unused(live)
            files = _read_manifest(directory)
            previous = _stash(live, media, now)
            _mark(previous, directory)  # only now: before this nothing live has been touched
            try:
                report = _install(directory, files, live, media, previous)
            except BaseException as exc:
                logger.error("The restore failed: %s", type(exc).__name__)
                if _put_back(previous, live, media):
                    _unmark(previous)
                    message = "The restore failed and the previous data was put back"
                else:
                    message = (
                        "The restore failed and the previous data could not be put back;"
                        " it is in the newest pre-restore directory of the backups"
                    )
                if isinstance(exc, Exception):
                    raise BackupError(message) from None
                raise
            if not _unmark(previous):
                report.warning = " ".join(
                    part
                    for part in (
                        report.warning,
                        f"The file {MARKER} in {previous.name} could not be removed;"
                        " remove it before the next restore",
                    )
                    if part
                )
    logger.info("Restore of %s done: %d media files", directory.name, report.media_files)
    return report


def _marked() -> list[Path]:
    """The `pre-restore*` directories that hold the marker of a restore that did not finish."""
    if not root().is_dir():
        return []
    return [
        path
        for path in sorted(root().iterdir())
        if path.name.startswith("pre-restore") and (path / MARKER).is_file()
    ]


def _refuse_while_marked() -> None:
    marked = _marked()
    if marked:
        names = ", ".join(path.name for path in marked)
        raise BackupError(
            f"An earlier restore did not finish: the data it replaced is in {names}."
            " If that restore printed 'Restored' or warned that the marker could not be removed,"
            " only remove the marker; otherwise put that data back."
            " See the Restore section of docs/deployment.md, then run the restore again"
        )


def _mark(previous: Path, backup_directory: Path) -> None:
    """Write the marker into the stash and flush it and the directory entry to disk."""
    marker = previous / MARKER
    try:
        marker.write_text(f"{backup_directory.name}\n")
        _sync(marker)
        _sync(previous)
    except BaseException:
        marker.unlink(missing_ok=True)
        raise


def _unmark(previous: Path) -> bool:
    """Take the marker away once the live data are whole again. False when it stays."""
    try:
        (previous / MARKER).unlink(missing_ok=True)
        _sync(previous)
    except OSError as exc:
        logger.error("The restore marker could not be removed: %s", type(exc).__name__)
        return False
    return True


def _live_database(database_path: Path | None) -> Path:
    chosen = str(database_path or settings.DATABASES["default"]["NAME"])
    if chosen.startswith(":memory:"):
        raise BackupError("The database is not a file that can be restored")
    return Path(chosen)


def _require_current_schema(database: Path) -> None:
    """A backup that lacks a migration of the installed code is never half-applied."""
    applied = set(_applied(database))
    if set(MigrationLoader(None, ignore_no_migrations=True).disk_migrations) - applied:
        raise BackupError(
            "The backup is from an older version: restore it with the matching version of the"
            " application, or migrate it deliberately"
        )


def _require_no_live_service(folder: Path) -> None:
    """Refuse while `app` or `jobs` wrote its heartbeat less than `STALE_SECONDS` ago.

    The message names the service and the whole seconds left, and never a path.
    """
    for name in ("app", "jobs"):
        seen = heartbeat.age(name, folder)
        if seen is not None and seen < heartbeat.STALE_SECONDS:
            left = max(1, math.ceil(heartbeat.STALE_SECONDS - seen))
            raise BackupError(
                f"The {name} service is still running: its heartbeat counts as stopped in"
                f" {left} s. Stop caddy, app and jobs before a restore, then run it again"
            )


def _require_unused(live: Path) -> None:
    """Refuse while `app` or `jobs` is alive, or while a connection is open right now.

    In write-ahead mode the exclusive lock only stops writers: an idle reader neither blocks it nor
    is blocked by it. So after our own connection is closed, a log (`-wal`) or shared-memory file
    (`-shm`) that is still there belongs to a connection that is open now, because SQLite removes
    both when the last one closes.

    The heartbeat files beside the database cover a running but idle `app` or `jobs`: they close
    their connections after every request or pass (`CONN_MAX_AGE` 0) and leave no log file, but
    each keeps its heartbeat younger than a minute (ADR-0061). The open-connection check sees only a
    request or a pass in flight. Stopping `caddy`, `app` and `jobs` before the restore is still the
    operator's job; a service that was killed leaves a heartbeat that counts as stopped after a
    minute.
    """
    _require_no_live_service(live.parent)
    if not live.exists():
        return
    try:
        with closing(sqlite3.connect(live, timeout=LOCK_PROBE_SECONDS, isolation_level=None)) as db:
            db.execute("BEGIN EXCLUSIVE")
            db.execute("ROLLBACK")
    except sqlite3.Error:
        raise BackupError(_IN_USE) from None
    if any(live.with_name(live.name + suffix).exists() for suffix in _SIDE_FILES[1:]):
        raise BackupError(_IN_USE)


def _stash(live: Path, media: Path, now: datetime) -> Path:
    """Copy the current database files and media into `pre-restore-<time>`; the originals stay."""
    previous = root() / f"pre-restore-{now.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    previous.mkdir(mode=0o750)
    try:
        for suffix in _SIDE_FILES:
            path = live.with_name(live.name + suffix)
            if path.exists():
                _copy_file(path, previous / path.name)
        if media.is_dir():
            shutil.copytree(
                media,
                previous / MEDIA,
                symlinks=True,
                copy_function=_copy_file,
                ignore=_ignore_transient(media),
            )
        _sync_tree(previous)
        _sync(root())
    except BaseException:
        shutil.rmtree(previous, ignore_errors=True)
        raise
    return previous


def _ignore_transient(media: Path) -> Callable[[str, list[str]], set[str]]:
    """For `copytree`: leave out `exports` and `imports` directly under the media root."""

    def ignore(directory: str, names: list[str]) -> set[str]:
        return set(names) & set(TRANSIENT) if Path(directory) == media else set()

    return ignore


def _install(
    directory: Path, files: Files, live: Path, media: Path, previous: Path
) -> RestoreReport:
    """Replace the contents of the live database file and media directory, then check them."""
    _place(directory / DATABASE, live)
    media.mkdir(parents=True, exist_ok=True)
    _clear(media)
    folders: set[Path] = set()
    restored: list[Path] = []
    for name in sorted(name for name in files if name.startswith(f"{MEDIA}/")):
        if _transient(Path(name).relative_to(MEDIA)):  # a backup of before they were left out
            continue
        destination = media / Path(name).relative_to(MEDIA)
        for folder in destination.relative_to(media).parents:
            if folder != Path("."):
                folders.add(media / folder)
        destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        _copy_file(directory / name, destination)
        restored.append(destination)
    for path in [*restored, *folders]:
        _sync(path)
    _sync(media)
    _own_data([live, *restored, *sorted(folders)])
    _check_database(live)
    for name, destination in [(DATABASE, live)] + [
        (f"{MEDIA}/{path.relative_to(media).as_posix()}", path) for path in restored
    ]:
        if _sha256(destination) != files[name]["sha256"]:
            raise BackupError("A restored file differs from the backup")
    return RestoreReport(
        database_bytes=live.stat().st_size,
        media_files=len(restored),
        previous=previous,
        warning=_ownership_warning([live, *restored, *sorted(folders)]),
    )


def _place(source: Path, live: Path) -> None:
    """Make `live` a fresh copy of `source`: staged first, then the side files go, then the swap.

    A kill between two steps never leaves the live database without its log while the new file is
    not yet written; the old log goes only when the new file is ready to take the place.
    """
    staged = live.with_name(live.name + ".restoring")
    try:
        _copy_file(source, staged)
        _sync(staged)
        for suffix in _SIDE_FILES[1:]:
            live.with_name(live.name + suffix).unlink(missing_ok=True)
        os.replace(staged, live)
        _sync(live)
    finally:
        staged.unlink(missing_ok=True)
    _sync(live.parent)


def _clear(directory: Path) -> None:
    """Empty a directory without removing it: it may be a mount point. `TRANSIENT` stays."""
    for entry in directory.iterdir():
        if entry.name in TRANSIENT and entry.is_dir() and not entry.is_symlink():
            continue
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            shutil.rmtree(entry)


def _copy_file(source: str | Path, destination: str | Path) -> None:
    """A copy that is its own file: never a link, and never written through an existing one."""
    Path(destination).unlink(missing_ok=True)
    shutil.copyfile(source, destination)
    shutil.copystat(source, destination)
    if _is_root():  # keep the owner of what is copied; a file system that refuses keeps the copy
        info = os.stat(source)
        try:
            _chown(Path(destination), info.st_uid, info.st_gid)
        except OSError:
            pass


def _put_back(previous: Path, live: Path, media: Path) -> bool:
    """Best effort: the data that `_stash` copied goes back. True when it all did."""
    done = True
    try:
        for suffix in _SIDE_FILES:
            live.with_name(live.name + suffix).unlink(missing_ok=True)
        for suffix in _SIDE_FILES:
            kept = previous / (live.name + suffix)
            if kept.exists():
                _copy_file(kept, live.with_name(live.name + suffix))
                _sync(live.with_name(live.name + suffix))
        _sync(live.parent)
    except Exception as exc:
        logger.error("Putting the database back failed: %s", type(exc).__name__)
        done = False
    try:
        media.mkdir(parents=True, exist_ok=True)
        _clear(media)
        kept_media = previous / MEDIA
        for entry in kept_media.iterdir() if kept_media.is_dir() else ():
            destination = media / entry.name
            if entry.is_dir() and not entry.is_symlink():
                shutil.copytree(entry, destination, symlinks=True, copy_function=_copy_file)
            else:
                shutil.copy2(entry, destination, follow_symlinks=False)
        if _is_root():
            owner = media.stat()
            for entry in media.iterdir():
                _chown_tree(entry, owner.st_uid, owner.st_gid)
        _sync_tree(media)
    except Exception as exc:
        logger.error("Putting the media back failed: %s", type(exc).__name__)
        done = False
    return done


def _is_root() -> bool:
    return os.geteuid() == 0


def _chown(path: Path, uid: int, gid: int) -> None:
    os.chown(path, uid, gid, follow_symlinks=False)


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    _chown(path, uid, gid)
    if path.is_dir() and not path.is_symlink():
        for folder, subfolders, names in os.walk(path):
            for name in names + subfolders:
                _chown(Path(folder) / name, uid, gid)


def _own_data(paths: Iterable[Path]) -> None:
    """Give the restored files to the application's user when this process may; else leave them.

    A file that refuses (not permitted, or a file system without owners) does not stop the others;
    the log names the count and the last type, and `_ownership_warning` tells the operator.
    """
    if not _is_root():
        return
    failed, last = 0, ""
    for path in paths:
        try:
            _chown(path, *DATA_OWNER)
        except OSError as exc:
            failed, last = failed + 1, type(exc).__name__
    if failed:
        logger.error("%d restored files could not be given to their owner: %s", failed, last)


def _uid(path: Path) -> int:
    return path.stat().st_uid


def _ownership_warning(paths: list[Path]) -> str:
    """Files that are neither the application's nor the data directory's are worth a word."""
    for path in paths:
        if _uid(path) not in {DATA_OWNER[0], _uid(path.parent)}:
            return (
                f"The restored files are not owned by uid {DATA_OWNER[0]} or by the owner of the"
                " data directory; the application may not be able to write them"
            )
    return ""
