"""The `jobs` service has a real healthcheck, not one that is always healthy."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def jobs_block() -> str:
    text = (ROOT / "deploy" / "compose.yaml").read_text()
    match = re.search(r"^  jobs:\n(.*?)(?=^  \S)", text, re.S | re.M)
    assert match, "no jobs service in compose.yaml"
    return match.group(1)


def test_jobs_healthcheck_reads_the_pass_record():
    """AC-144: the check runs the heartbeat module and is not `true`."""
    block = jobs_block()

    assert 'test: ["CMD", "python", "-m", "app.domain.heartbeat", "check"]' in block, (
        "jobs healthcheck must run the heartbeat check"
    )
    assert '"true"' not in block
    assert "a running container is healthy" not in block


def test_jobs_healthcheck_timing():
    """AC-144: a minute between checks, ten seconds each, a minute to start, three tries."""
    block = jobs_block()

    for line in ("interval: 60s", "timeout: 10s", "start_period: 60s", "retries: 3"):
        assert line in block, line
