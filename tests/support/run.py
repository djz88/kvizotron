"""Runs code in a fresh process, because module discovery happens once, while settings load."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEMO_SITE = REPO / "tests" / "fixtures" / "demo_site"
AUTH_TEST_SITE = REPO / "tests" / "fixtures" / "auth_test_site"


def _environment(db: Path, sites: list[Path], env: dict[str, str]) -> dict[str, str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("KVZ_")}
    return clean | {
        "DJANGO_SETTINGS_MODULE": "app.settings",
        "KVZ_SECRET_KEY": "test-only-not-a-secret",
        "KVZ_DOMAIN": "testserver",
        "KVZ_DB_PATH": str(db),
        "PYTHONPATH": os.pathsep.join([str(REPO), *map(str, sites)]),
        **env,
    }


def run(
    *args: str, db: Path, sites: list[Path] | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO,
        env=_environment(db, sites or [], env or {}),
        capture_output=True,
        text=True,
        check=False,
    )


def run_manage(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return run("manage.py", *args, **kwargs)


def run_python(code: str, **kwargs) -> subprocess.CompletedProcess[str]:
    prelude = "import django\ndjango.setup()\nfrom django.test import Client\nclient = Client()\n"
    return run("-c", prelude + code, **kwargs)
