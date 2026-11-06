import json
import os
import subprocess
import sys

import pytest

BASE_ENV = {
    "KVZ_SECRET_KEY": "test-only-not-a-secret",
    "KVZ_DOMAIN": "quiz.example.org",
    "KVZ_DB_PATH": ":memory:",
}


def load_settings(env: dict[str, str], code: str = "import app.settings"):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("KVZ_")}
    return subprocess.run(
        [sys.executable, "-c", code], env=clean | env, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("name", ["KVZ_SECRET_KEY", "KVZ_DOMAIN", "KVZ_DB_PATH"])
def test_missing_required_variable_aborts_and_names_it(name):
    env = {k: v for k, v in BASE_ENV.items() if k != name}
    result = load_settings(env)
    assert result.returncode != 0
    assert name in result.stderr


def test_empty_secret_key_aborts():
    result = load_settings(BASE_ENV | {"KVZ_SECRET_KEY": ""})
    assert result.returncode != 0
    assert "KVZ_SECRET_KEY" in result.stderr


@pytest.mark.parametrize("debug", [None, "0", "true"])
def test_production_defaults_debug_off_and_cookies_secure(debug):
    env = BASE_ENV | ({"KVZ_DEBUG": debug} if debug is not None else {})
    code = (
        "import json, app.settings as s;"
        "print(json.dumps([s.DEBUG, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE]))"
    )
    result = load_settings(env, code)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [False, True, True]


def test_debug_only_when_explicitly_one():
    code = "import app.settings as s; print(s.DEBUG)"
    result = load_settings(BASE_ENV | {"KVZ_DEBUG": "1"}, code)
    assert result.stdout.strip() == "True"


def test_domain_controls_hosts_and_csrf_origins():
    code = (
        "import json, app.settings as s;"
        "print(json.dumps([s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS]))"
    )
    result = load_settings(BASE_ENV, code)
    assert json.loads(result.stdout) == [
        ["quiz.example.org", "localhost"],
        ["https://quiz.example.org"],
    ]
