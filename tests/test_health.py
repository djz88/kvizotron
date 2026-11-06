import os
import subprocess
import sys

from django.conf import settings

from tests.support.run import run_manage, run_python

CHECK_BROKEN_DB = """
import django
django.setup()
from django.test import Client
response = Client().get("/healthz")
print(response.status_code)
print(response.content.decode())
"""


def test_healthz_ok(client, db):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_unreadable_database_is_503_without_details():
    env = os.environ | {
        "DJANGO_SETTINGS_MODULE": "app.settings",
        "KVZ_SECRET_KEY": "test-only-not-a-secret",
        "KVZ_DOMAIN": "testserver",
        "KVZ_DB_PATH": "/nonexistent-secret-dir/db.sqlite3",
    }
    result = subprocess.run(
        [sys.executable, "-c", CHECK_BROKEN_DB], env=env, capture_output=True, text=True, check=True
    )
    status, body = result.stdout.strip().splitlines()
    assert status == "503"
    assert body == '{"status": "unavailable"}'
    assert "nonexistent-secret-dir" not in result.stdout + result.stderr


def test_foreign_host_is_rejected(client):
    assert client.get("/healthz", HTTP_HOST="evil.example.net").status_code == 400


def test_healthz_uses_provider(client, monkeypatch):
    monkeypatch.setattr(settings.KVZ_PERSISTENCE, "healthcheck", lambda: False)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_vanished_database_file_gives_503_and_is_not_recreated(tmp_path):
    db = tmp_path / "db.sqlite3"
    assert run_manage("migrate", "--noinput", db=db).returncode == 0
    db.unlink()
    result = run_python('print(client.get("/healthz").status_code)', db=db)
    assert result.stdout.strip() == "503", result.stderr
    assert not db.exists()
