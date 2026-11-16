"""ADR-0066: in Kubernetes a liveness probe restarts the pod, so it asks only whether jobs lives."""

import json
import time
from datetime import UTC, datetime, timedelta

from app.domain import heartbeat


def test_a_long_pass_is_not_a_dead_process(tmp_path):
    """A backup running for two hours fails `check` but not `check --alive` (no kill mid-backup)."""
    now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    started = (now - timedelta(hours=2)).isoformat()
    (tmp_path / heartbeat.RECORD_FILE).write_text(
        json.dumps({"started": started, "finished": None})
    )
    (tmp_path / ".kvz-heartbeat-jobs").write_text("")
    assert heartbeat.jobs_healthy(now, tmp_path) is False
    assert heartbeat.jobs_alive(time.time(), tmp_path) is True


def test_a_stale_heartbeat_is_a_dead_process(tmp_path, monkeypatch):
    beat = tmp_path / ".kvz-heartbeat-jobs"
    beat.write_text("")
    old = time.time() - 10 * heartbeat.JOBS_INTERVAL
    import os

    os.utime(beat, (old, old))
    assert heartbeat.jobs_alive(time.time(), tmp_path) is False


def test_the_command_knows_both_checks():
    assert heartbeat.main(["nonsense"]) == 2
