"""One container: migrations, then the application and the jobs loop side by side (ADR-0066).

Compose runs these as the services `migrate`, `app` and `jobs`; this command is for a deployment
that wants a single container, such as one pod in Kubernetes behind an ingress. A child that ends
ends the container, so the orchestrator restarts all of it and never leaves half of it running.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

from django.core.management.base import BaseCommand

# The image's default command (one worker: SQLite and the request limits in process memory
# depend on it, ADR-0036) ...
IMAGE_COMMAND = [
    "gunicorn",
    "app.wsgi:application",
    "--bind",
    "0.0.0.0:8000",
    "--workers",
    "1",
    "--threads",
    "8",
    # gunicorn 26 opens a control socket under $HOME, which the image user does not have.
    "--no-control-socket",
]
# ... plus idle connections kept longer than an ingress keeps them (ingress-nginx: 60 s), or a POST
# sent on one gunicorn just closed is reset and answered 502. Caddy in Compose closes its own after
# 1 s instead (ADR-0058).
GUNICORN = [*IMAGE_COMMAND, "--keep-alive", "75"]
POLL = 0.2


def children() -> list[tuple[list[str], float]]:
    """Each command with its grace after SIGTERM: gunicorn's graceful timeout, and what a pass
    copying the database and the media needs (Compose gives `jobs` 120 s in all)."""
    jobs = [sys.executable, "manage.py", "jobs"]
    return [(GUNICORN, 30.0), (jobs, 115.0)]


def prepare() -> None:
    """A fresh volume is empty: the image's directory under it does not show through.

    The path is the one the persistence provider reads (`KVZ_DB_PATH`, set by the image); without
    it there is nothing to prepare and the provider itself refuses to start.
    """
    path = os.environ.get("KVZ_DB_PATH")
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)


def _stop_all(running: Sequence[tuple[subprocess.Popen, float]]) -> None:
    """SIGTERM to all; each grace counts from that one moment, not one after another."""
    begun = time.monotonic()
    for process, _grace in running:
        if process.poll() is None:
            process.terminate()
    for process, grace in running:
        try:
            process.wait(max(begun + grace - time.monotonic(), 0))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _exit_code(code: int) -> int:
    """A child killed by a signal ends like a shell reports it: 128 + the signal number."""
    return 128 - code if code < 0 else code or 1


def run(
    migrate: list[str] | None,
    commands: Sequence[tuple[list[str], float]],
    *,
    stop: threading.Event | None = None,
) -> int:
    """Run `migrate` to its end, then every command until one ends or `stop` is set.

    Returns 0 after a stop, the code of a failed migration, or the code of the first child that
    ended (1 when it ended with 0, since a service must not end on its own; 128 + N when signal N
    killed it).
    """
    stop = stop or threading.Event()
    if migrate is not None:
        code = subprocess.call(migrate)  # noqa: S603 - fixed commands of this module, no input
        if code:
            return _exit_code(code)
        if stop.is_set():  # stopped while migrating: start nothing
            return 0
    running: list[tuple[subprocess.Popen, float]] = []
    try:
        for command, grace in commands:
            running.append((subprocess.Popen(command), grace))  # noqa: S603 - fixed commands
    except BaseException:
        _stop_all(running)  # never leave half of the container running
        raise
    while not stop.wait(POLL):
        ended = [process.returncode for process, _ in running if process.poll() is not None]
        if ended:
            _stop_all(running)
            return _exit_code(ended[0])
    _stop_all(running)
    return 0


class Command(BaseCommand):
    help = "Migrate, then run the application and the jobs loop in this one container."
    requires_system_checks: list[str] = []  # the children run their own

    def handle(self, *args, **options):
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda _signum, _frame: stop.set())
        prepare()
        migrate = [sys.executable, "manage.py", "migrate", "--noinput"]
        sys.exit(run(migrate, children(), stop=stop))
