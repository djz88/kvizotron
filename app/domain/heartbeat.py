"""Heartbeat files and the pass record of the `jobs` service.

One hidden file per name (`app`, `jobs`) lives beside the database file; its modification time
is the heartbeat. A second file holds the record of the last hourly pass. Nothing here opens a
database or the network: the reading functions and `python -m app.domain.heartbeat check` use the
standard library only, and the settings are imported inside `directory()`. Writing never raises,
because a heartbeat must not stop a request or a pass; reading what is missing or broken gives
`None`.
"""

import contextlib
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

STALE_SECONDS = 60
JOBS_INTERVAL = 15
APP_INTERVAL = 10
FINISH_LIMIT_SECONDS = 7200
START_LIMIT_SECONDS = 3600
RECORD_FILE = ".kvz-jobs-pass.json"


@dataclass(frozen=True)
class PassRecord:
    started: datetime | None
    finished: datetime | None
    outcome: str | None


def directory() -> Path | None:
    """The folder of the database file, or None for an in-memory or unusable database."""
    try:
        from django.conf import settings

        name = settings.DATABASES["default"]["NAME"]
        text = os.fspath(name)
    except Exception:
        return None
    if not isinstance(text, str) or not text or text == ":memory:" or text.startswith("file:"):
        return None
    return Path(text).parent


def _resolve(given: Path | None) -> Path | None:
    return given if given is not None else directory()


def _file(name: str, folder: Path) -> Path:
    return folder / f".kvz-heartbeat-{name}"


def beat(name: str, directory: Path | None = None) -> None:
    folder = _resolve(directory)
    if folder is None:
        return
    with contextlib.suppress(OSError):
        path = _file(name, folder)
        try:
            os.utime(path)
        except FileNotFoundError:
            path.touch()


def age(name: str, directory: Path, now: float | None = None) -> float | None:
    try:
        modified = _file(name, directory).stat().st_mtime
    except OSError:
        return None
    return (time.time() if now is None else now) - modified


def clear(name: str, directory: Path | None = None) -> None:
    folder = _resolve(directory)
    if folder is None:
        return
    with contextlib.suppress(OSError):
        _file(name, folder).unlink()


def write_pass(
    started: datetime, finished: datetime | None, outcome: str | None, directory: Path | None = None
) -> None:
    folder = _resolve(directory)
    if folder is None:
        return
    body = {
        "started": started.isoformat() if started else None,
        "finished": finished.isoformat() if finished else None,
        "outcome": outcome,
    }
    temporary = None
    try:
        handle, temporary = tempfile.mkstemp(dir=folder, prefix=".kvz-jobs-pass-", suffix=".tmp")
        with os.fdopen(handle, "w") as stream:
            json.dump(body, stream)
        os.replace(temporary, folder / RECORD_FILE)
        temporary = None
    except OSError:
        pass
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


def _moment(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def read_pass(directory: Path | None = None) -> PassRecord | None:
    folder = _resolve(directory)
    if folder is None:
        return None
    try:
        body = json.loads((folder / RECORD_FILE).read_text())
        outcome = body.get("outcome")
        return PassRecord(
            _moment(body.get("started")),
            _moment(body.get("finished")),
            outcome if isinstance(outcome, str) else None,
        )
    except OSError, ValueError, AttributeError:
        return None


def jobs_healthy(now: datetime, directory: Path | None = None) -> bool:
    """False only when the record shows a pass that finished or started too long ago.

    A start newer than the finish (or no finish) is a pass in progress, judged by its own start,
    so the first pass after a long stop is not held against the previous, old finish.
    A `jobs` heartbeat older than three beat periods is unhealthy whatever the record says; a
    missing one (first start) is not.
    """
    folder = _resolve(directory)
    if folder is not None:
        stale = age("jobs", folder, now.timestamp())
        if stale is not None and stale > 3 * JOBS_INTERVAL:
            return False
    record = read_pass(directory)
    if record is None:
        return True
    try:
        running = record.started is not None and (
            record.finished is None or record.started > record.finished
        )
        if running and record.started is not None:
            return (now - record.started).total_seconds() <= START_LIMIT_SECONDS
        if record.finished is not None:
            return (now - record.finished).total_seconds() <= FINISH_LIMIT_SECONDS
    except TypeError:
        return True
    return True


def jobs_alive(now: float, directory: Path | None = None) -> bool:
    """Only whether the `jobs` loop still beats: what a probe that restarts may ask (ADR-0066).

    A long pass (a big backup) is no reason to kill the container in the middle of it, so the
    pass record is left to `jobs_healthy` and the pages. A missing heartbeat (first start) is alive.
    """
    folder = _resolve(directory)
    if folder is None:
        return True
    stale = age("jobs", folder, now)
    return stale is None or stale <= 3 * JOBS_INTERVAL


def main(argv: list[str]) -> int:
    """`check`: the status Compose shows; `check --alive`: what a Kubernetes liveness probe asks."""
    if argv == ["check"]:
        return 0 if jobs_healthy(datetime.now().astimezone()) else 1
    if argv == ["check", "--alive"]:
        return 0 if jobs_alive(datetime.now().timestamp()) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
