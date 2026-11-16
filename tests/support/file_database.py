"""A real SQLite file with the production schema and options, next to the in-memory test database.

The suite runs on `KVZ_DB_PATH=":memory:"`, which has no file to back up, no WAL and no busy
timeout. A test that needs those asks for the `file_db` fixture (`tests/conftest.py`), a
`FileDatabase` whose `path` is a fresh file that `manage.py migrate` filled in a separate process
with the production options (WAL, `IMMEDIATE` transactions, timeout 20). Nothing about how other
tests get their database changes, and the Django test isolation is not involved: use `sqlite3`
(threads included) or code that takes a database path, such as
`backup.create(now, database_path=...)`.

    def test_something(file_db):
        file_db.execute("insert into app_setting (key, value_json) values ('a', '1')")
        backup.create(now, database_path=file_db.path)

The first use per process migrates a template (a few seconds); each test gets a copy of it.
"""

import atexit
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from tests.support.run import run_manage


@dataclass(frozen=True)
class FileDatabase:
    path: Path

    def connect(self) -> sqlite3.Connection:
        """A connection with the production busy timeout, in autocommit; the caller closes it."""
        return sqlite3.connect(self.path, timeout=20, isolation_level=None)

    def execute(self, sql: str, *parameters: object) -> list[tuple[Any, ...]]:
        """Run one statement on a connection of its own and return its rows."""
        with closing(self.connect()) as connection:
            return connection.execute(sql, parameters).fetchall()


@cache
def _template() -> Path:
    """The migrated database as one closed file, made once per process."""
    directory = Path(TemporaryDirectory(prefix="kvz-file-db-", delete=False).name)
    atexit.register(shutil.rmtree, directory, ignore_errors=True)  # one directory per process
    path = directory / "template.sqlite3"
    result = run_manage("migrate", "--noinput", db=path)
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as connection:  # fold the WAL into the file
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=WAL")
    for leftover in directory.glob("template.sqlite3-*"):
        leftover.unlink(missing_ok=True)
    return path


@contextmanager
def file_database(directory: Path) -> Iterator[FileDatabase]:
    """A fresh migrated database file `live.sqlite3` in `directory`."""
    path = directory / "live.sqlite3"
    shutil.copyfile(_template(), path)
    yield FileDatabase(path)
