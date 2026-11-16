"""A real server process on a database file: what the in-memory test database cannot show.

The suite's own database is in memory and shared by the threads of one process, so it knows
nothing of WAL, `IMMEDIATE` transactions or the busy timeout. `running_server` starts the
production command (`gunicorn app.wsgi:application`, one worker with eight threads) on
`127.0.0.1` and a free port, against a database file such as the one of the `file_db` fixture,
and yields the base URL. The environment is the one of `tests/support/run.py`: none of the
caller's `KVZ_*` variables, a test secret key and the given paths.

    with running_server(file_db.path, tmp_path / "media") as base:
        urllib.request.urlopen(f"{base}/healthz")

The server's output (stdout and stderr, gunicorn's error log included) goes to `server.log`
next to the database file, so a test reads it after the block for an assertion; it is also part
of the message when the server never answers. The server runs in a process group of its own and
ends with SIGTERM when the block ends, with SIGKILL for the whole group when it does not stop
within a few seconds. No network beyond the loopback address.
"""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.support.run import REPO, _environment

HOST = "localhost"
START_TIMEOUT = 30.0
STOP_TIMEOUT = 5.0
LOG_NAME = "server.log"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _answers(base: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=2) as response:  # noqa: S310  # loopback
            return bool(response.status == 200)
    except urllib.error.URLError, OSError:
        return False


@contextmanager
def running_server(db: Path, media: Path, env: dict[str, str] | None = None) -> Iterator[str]:
    """Starts the server and waits (at most 30 s) until `/healthz` answers; yields the base URL.

    `env` adds or replaces variables, for a test that needs another limit. `media` is created.
    """
    media.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    base = f"http://{HOST}:{port}"
    environment = _environment(
        db, [], {"KVZ_DOMAIN": HOST, "KVZ_MEDIA_PATH": str(media), **(env or {})}
    )
    command = [
        sys.executable,
        "-m",
        "gunicorn",
        "app.wsgi:application",
        "--bind",
        f"127.0.0.1:{port}",
        "--workers",
        "1",
        "--threads",
        "8",
        "--no-control-socket",
    ]
    log = db.parent / LOG_NAME
    with log.open("wb") as output:
        process = subprocess.Popen(  # noqa: S603  # fixed command, the interpreter of the tests
            command,
            cwd=REPO,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # a group of its own, so no worker outlives the master
        )
        try:
            deadline = time.monotonic() + START_TIMEOUT
            while not _answers(base):
                if process.poll() is not None or time.monotonic() > deadline:
                    output.flush()
                    raise AssertionError(
                        f"the server did not answer /healthz:\n{log.read_text(errors='replace')}"
                    )
                time.sleep(0.2)
            yield base
        finally:
            process.terminate()
            try:
                process.wait(STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            try:
                os.killpg(process.pid, signal.SIGKILL)  # whatever of the group is still alive
            except ProcessLookupError:
                pass
