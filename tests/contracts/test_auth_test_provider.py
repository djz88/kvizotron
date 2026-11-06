import os
import subprocess
import sys

from tests.support.run import AUTH_TEST_SITE, REPO


def test_test_only_provider_passes_the_shared_contract_suite():
    env = os.environ | {
        "PYTHONPATH": os.pathsep.join([str(REPO), str(AUTH_TEST_SITE)]),
        "DJANGO_SETTINGS_MODULE": "tests.settings",
        "KVZ_PROVIDER_AUTH": "auth.test",
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/contracts/auth_test_suite.py", "-q"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "8 passed" in result.stdout
