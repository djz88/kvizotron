"""The `app` heartbeat is written by the first request and then at most every ten seconds."""

import pytest

from app.api import heartbeat as middleware
from app.domain import heartbeat

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_process(monkeypatch):
    monkeypatch.setattr(middleware, "_last", None)
    monkeypatch.setattr(middleware, "_exit_registered", True)


@pytest.fixture
def beats(monkeypatch):
    calls = []
    monkeypatch.setattr(heartbeat, "beat", lambda name, directory=None: calls.append(name))
    return calls


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(middleware.time, "monotonic", lambda: now[0])
    return now


def test_a_request_writes_the_app_heartbeat(client, beats):
    """AC-143: a restore can tell that `app` is alive."""
    assert client.get("/healthz").status_code == 200
    assert beats == ["app"]


def test_a_request_creates_the_file_beside_the_database(client, monkeypatch, tmp_path):
    monkeypatch.setattr(heartbeat, "directory", lambda: tmp_path)
    client.get("/healthz")
    assert heartbeat.age("app", tmp_path) is not None


def test_a_second_request_within_ten_seconds_does_not_write_again(client, beats, clock):
    client.get("/healthz")
    clock[0] += heartbeat.APP_INTERVAL - 0.5
    client.get("/")
    assert beats == ["app"]
    clock[0] += 1
    client.get("/")
    assert beats == ["app", "app"]


def test_the_health_check_counts(client, beats):
    client.get("/healthz")
    assert beats == ["app"]


def test_a_failing_write_does_not_change_the_response(client, monkeypatch):
    def broken(name, directory=None):
        raise RuntimeError("secret path /data")

    monkeypatch.setattr(heartbeat, "beat", broken)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_failure_is_logged_without_its_text(client, monkeypatch, caplog):
    def broken(name, directory=None):
        raise RuntimeError("secret path /data")

    monkeypatch.setattr(heartbeat, "beat", broken)
    client.get("/healthz")
    assert "RuntimeError" in caplog.text
    assert "secret" not in caplog.text


def test_the_file_is_removed_when_the_process_ends(monkeypatch):
    registered = []
    monkeypatch.setattr(middleware, "_exit_registered", False)
    monkeypatch.setattr(middleware.atexit, "register", lambda *args: registered.append(args))
    middleware._register_exit()
    middleware._register_exit()
    assert registered == [(heartbeat.clear, "app")]


def test_the_middleware_is_the_last_one():
    from django.conf import settings

    assert settings.MIDDLEWARE[-1] == "app.api.heartbeat.HeartbeatMiddleware"
