"""Applies what a run's schedule made due, before anything reads a run's status (ADR-0048)."""

import logging
from collections.abc import Callable

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse

from app.domain import run_schedule

logger = logging.getLogger(__name__)
# A health check must not touch the database itself, and a script or a flag needs no run.
SKIPPED = ("/healthz", "/assets/")


class RunClockMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(SKIPPED):
            return self.get_response(request)
        try:
            run_schedule.settle()
        except DatabaseError:
            # The next request tries again, and a submission does not depend on this.
            logger.exception("Could not apply the run schedule")
        return self.get_response(request)
