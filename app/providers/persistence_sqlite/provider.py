"""SQLite as the database. Read while settings load, so Django is imported only inside methods."""

import logging
import os
from pathlib import Path
from typing import Any

from app.kernel.errors import StartupError

logger = logging.getLogger(__name__)


class SqliteProvider:
    id = "persistence.sqlite"

    def database_settings(self) -> dict[str, Any]:
        path = os.environ.get("KVZ_DB_PATH", "")
        if not path:
            raise StartupError("Environment variable KVZ_DB_PATH must be set")
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": path,
            "OPTIONS": {
                "transaction_mode": "IMMEDIATE",
                "timeout": 20,
                "init_command": "PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL;",
            },
        }

    def healthcheck(self) -> bool:
        from django.db import Error, connection

        # Connecting would silently create a new, empty database in place of a vanished file.
        if not connection.is_in_memory_db() and not Path(connection.settings_dict["NAME"]).exists():
            logger.error("Health check failed: database file is missing")
            return False
        try:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
        except Error as exc:
            # Only the type: the message of a database error can contain file paths.
            logger.error("Health check failed: %s", type(exc).__name__)
            return False
        return True
