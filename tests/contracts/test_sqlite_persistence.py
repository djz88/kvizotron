import pytest

from app.kernel.errors import StartupError
from app.providers.persistence_sqlite.provider import SqliteProvider
from tests.contracts.persistence import PersistenceContract
from tests.support.run import run_manage, run_python


class TestSqlite(PersistenceContract):
    provider = SqliteProvider()


def test_file_database_uses_wal_and_immediate(tmp_path):
    db = tmp_path / "db.sqlite3"
    assert run_manage("migrate", "--noinput", db=db).returncode == 0
    result = run_python(
        """
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("PRAGMA journal_mode")
    print(cursor.fetchone()[0])
print(connection.settings_dict["OPTIONS"]["transaction_mode"])
""",
        db=db,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["wal", "IMMEDIATE"]


def test_missing_db_path_names_variable(monkeypatch):
    monkeypatch.delenv("KVZ_DB_PATH")
    with pytest.raises(StartupError, match="KVZ_DB_PATH"):
        SqliteProvider().database_settings()
