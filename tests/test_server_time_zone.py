"""Django must not replace the container's time zone with its own default (America/Chicago)."""

import subprocess
import sys

CODE = "import django; django.setup(); from app.domain import clock; print(clock.server_zone())"


def _server_zone(tz: str | None, db: str) -> str:
    env = {
        "KVZ_DB_PATH": db,
        "PATH": "/usr/bin:/bin",
        "DJANGO_SETTINGS_MODULE": "app.settings",
        "KVZ_SECRET_KEY": "test-only-not-secret",
        "KVZ_DOMAIN": "localhost",
    }
    if tz:
        env["TZ"] = tz
    done = subprocess.run(
        [sys.executable, "-c", CODE], env=env, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def test_the_container_zone_survives_django_setup(tmp_path):
    assert _server_zone("Europe/Prague", str(tmp_path / "db.sqlite3")) == "Europe/Prague"


def test_without_tz_the_server_is_utc(tmp_path):
    assert _server_zone(None, str(tmp_path / "db.sqlite3")) == "UTC"
