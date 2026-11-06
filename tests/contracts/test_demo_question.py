import os
import subprocess
import sys

from tests.support.run import DEMO_SITE, REPO


def test_demo_module_passes_shared_contract_suites():
    env = os.environ | {
        "PYTHONPATH": os.pathsep.join([str(REPO), str(DEMO_SITE)]),
        "DJANGO_SETTINGS_MODULE": "tests.settings",
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/contracts/demo_question_suite.py", "-q"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "12 passed" in result.stdout
