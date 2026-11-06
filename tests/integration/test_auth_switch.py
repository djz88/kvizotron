"""AC-02: the auth provider changes on restart and passes the same contract tests."""

from pathlib import Path

import pytest

from tests.support.modules import make_module
from tests.support.run import AUTH_TEST_SITE, REPO, run, run_manage, run_python

SITES = [AUTH_TEST_SITE]
LOCAL_PASSWORD = "correct horse battery"
CREATE = f'''
from app.kernel.models import AdminUser
AdminUser.objects.create_admin("alice", "{LOCAL_PASSWORD}")
'''


def can_log_in(secret, *, db, provider):
    result = run_python(
        "from django.contrib.auth import authenticate\n"
        f'print(authenticate(None, username="alice", password="{secret}") is not None)',
        db=db,
        sites=SITES,
        env={"KVZ_PROVIDER_AUTH": provider},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip() == "True"


def test_two_auth_providers_without_selection_abort(tmp_path):
    result = run_manage("check", db=tmp_path / "db.sqlite3", sites=SITES)
    assert result.returncode != 0
    assert "KVZ_PROVIDER_AUTH" in result.stderr


def test_selected_provider_decides_after_restart(tmp_path):
    db = tmp_path / "db.sqlite3"
    env = {"KVZ_PROVIDER_AUTH": "auth.test"}
    assert run_manage("migrate", "--noinput", db=db, sites=SITES, env=env).returncode == 0
    assert run_python(CREATE, db=db, sites=SITES, env=env).returncode == 0

    assert can_log_in("test-only-token", db=db, provider="auth.test")
    assert not can_log_in(LOCAL_PASSWORD, db=db, provider="auth.test")

    assert can_log_in(LOCAL_PASSWORD, db=db, provider="auth.local")
    assert not can_log_in("test-only-token", db=db, provider="auth.local")


def test_login_page_uses_the_selected_provider(tmp_path):
    db = tmp_path / "db.sqlite3"
    env = {"KVZ_PROVIDER_AUTH": "auth.test"}
    assert run_manage("migrate", "--noinput", db=db, sites=SITES, env=env).returncode == 0
    assert run_python(CREATE, db=db, sites=SITES, env=env).returncode == 0

    def login_status(secret):
        code = (
            f"r = client.post('/admin/login', {{'login': 'alice', 'password': '{secret}'}})\n"
            "print(r.status_code)"
        )
        result = run_python(code, db=db, sites=SITES, env=env)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    assert login_status("test-only-token") == "302"
    assert login_status(LOCAL_PASSWORD) == "200"


def test_test_provider_is_not_in_the_image_context():
    rules = Path(REPO / ".dockerignore").read_text().splitlines()
    assert rules[1] == "*"
    assert not [rule for rule in rules if rule.startswith("!") and "tests" in rule]


@pytest.mark.parametrize(
    ("backend", "reason"),
    [("nope_missing.X", "nope_missing"), ("builtins.object", "AuthenticationProvider")],
)
def test_bad_auth_backend_aborts_at_startup(tmp_path, backend, reason):
    make_module(tmp_path, "auth.broken", kind="provider", provides=["auth"], auth_backend=backend)
    result = run(
        "-c",
        "import app.wsgi",
        db=tmp_path / "db.sqlite3",
        sites=[tmp_path],
        env={"KVZ_PROVIDER_AUTH": "auth.broken"},
    )
    assert result.returncode != 0
    last_line = result.stderr.strip().splitlines()[-1]
    assert "auth.broken" in last_line
    assert reason in last_line
