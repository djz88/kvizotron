"""Tells a restore that the `app` service is alive: a hidden file touched while it serves."""

import atexit
import logging
import time
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from app.domain import heartbeat

logger = logging.getLogger(__name__)
_last: float | None = None
_exit_registered = False


def _register_exit() -> None:
    """Remove the file when the process ends cleanly, so a restore need not wait for it."""
    global _exit_registered
    if not _exit_registered:
        _exit_registered = True
        atexit.register(heartbeat.clear, "app")


class HeartbeatMiddleware:
    """Writes the `app` heartbeat at most once per `APP_INTERVAL` seconds, whatever the request.

    The time of the last write is per process. A failure never reaches the response.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        global _last
        now = time.monotonic()
        if _last is None or now - _last >= heartbeat.APP_INTERVAL:
            _last = now
            try:
                _register_exit()
                heartbeat.beat("app")
            except Exception as exc:
                logger.warning("The app heartbeat could not be written: %s", type(exc).__name__)
        return self.get_response(request)
