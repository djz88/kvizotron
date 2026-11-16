"""The `jobs` service: a pass at the start and then every hour, without cron.

A pass runs the retention pass, deletes expired login sessions and, once per local day, makes the
backup of the database and the media.
"""

import logging
import signal
import threading
from collections.abc import Callable
from functools import partial

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from app.domain import admins, backup, heartbeat, retention

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600.0


def run_loop(
    stop: threading.Event, wait: Callable[[float], bool], one_pass: Callable[[], object]
) -> None:
    while not stop.is_set():
        close_old_connections()
        try:
            one_pass()
        except Exception as exc:  # the type only: a message could carry a path or a value
            logger.error("The pass failed: %s", type(exc).__name__)
        finally:
            close_old_connections()
        wait(INTERVAL_SECONDS)


def pass_once(stop: Callable[[], bool] | None = None) -> None:
    """One pass, recorded: started when it begins, finished with its outcome when it ends.

    While it runs the record keeps the previous finish and outcome, so a reader still sees the
    last completed pass. The outcome is `failed` when any of the retention pass, the backup and
    the prune raised; otherwise `stopped` when `stop` was set before the backup, else `ok` (also
    for a pass with no backup due). `stop` tells the retention pass that the service is ending,
    so it stops between runs, and keeps the pass from starting a backup.
    """
    previous = heartbeat.read_pass()
    started = timezone.now()
    heartbeat.write_pass(
        started,
        previous.finished if previous else None,
        previous.outcome if previous else None,
    )
    outcome = "failed"
    try:
        outcome = _work(stop)
    finally:
        heartbeat.write_pass(started, timezone.now(), outcome)


def _work(stop: Callable[[], bool] | None) -> str:
    """Retention first, then today's backup when there is none; neither stops the other.

    A backup that fails must not leave data kept beyond its retention, and a retention pass that
    fails must not leave the day without a backup. `create` and `prune` take the same lock, so
    they run one after the other. Pruning runs even when the backup failed (a full disk is the
    likely reason and pruning frees it); it always keeps the newest backup that verifies. The log
    gets the exception type only. When `stop` is set after the retention pass, no backup starts
    (Compose would kill it halfway) and the outcome is `stopped`, unless something already
    raised. The outcome: `ok`, `failed` or `stopped`.
    """
    clean = True
    try:
        retention.run_pass(None, stop)  # positional, as the stand-ins of the tests take *args
    except Exception as exc:  # the type only: a message could carry a path or a value
        logger.error("The retention pass failed: %s", type(exc).__name__)
        clean = False
    try:
        admins.clear_expired_sessions()
    except Exception as exc:
        logger.error("Clearing expired sessions failed: %s", type(exc).__name__)
        clean = False
    if stop is not None and stop():
        return "stopped" if clean else "failed"
    now = timezone.now()
    try:
        if not backup.due(now):
            return "ok" if clean else "failed"
    except Exception as exc:
        logger.error("The daily backup failed: %s", type(exc).__name__)
        return "failed"
    try:
        backup.create(now)
    except Exception as exc:
        logger.error("The daily backup failed: %s", type(exc).__name__)
        clean = False
    try:
        pruned = backup.prune(now, settings.KVZ_BACKUP_RETENTION_DAYS)
    except Exception as exc:
        logger.error("Pruning the backups failed: %s", type(exc).__name__)
        clean = False
    else:
        if pruned.stayed:  # not a failed pass: the count only, the type was logged where it arose
            logger.warning("%d backup directories could not be deleted", len(pruned.stayed))
    return "ok" if clean else "failed"


def keep_beating(done: threading.Event) -> None:
    """Touch the `jobs` heartbeat every `JOBS_INTERVAL` seconds until `done` is set."""
    while not done.wait(heartbeat.JOBS_INTERVAL):
        heartbeat.beat("jobs")


class Command(BaseCommand):
    help = "Run the retention pass and the daily backup every hour until stopped."

    def handle(self, *args, **options):
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
        done = threading.Event()
        heartbeat.beat("jobs")
        beating = threading.Thread(
            target=keep_beating, args=(done,), name="jobs-heartbeat", daemon=True
        )
        beating.start()
        try:
            run_loop(stop, stop.wait, partial(pass_once, stop=stop.is_set))
        finally:
            done.set()
            beating.join()
            heartbeat.clear("jobs")
