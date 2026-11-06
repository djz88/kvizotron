"""Synchronous in-process events (ADR-0016). Handlers run after commit and must stay short."""

import logging
from collections.abc import Callable, Mapping

from django.db import transaction

from app.kernel.registry import is_enabled

logger = logging.getLogger(__name__)

EVENTS: frozenset[str] = frozenset(
    {
        "quiz.published",
        "run.opened",
        "attempt.submitted",
        "run.closed",
        "draw.completed",
        "retention.executed",
    }
)

Handler = Callable[[Mapping[str, object]], None]

_handlers: dict[str, list[tuple[Handler, str]]] = {}


def subscribe(event: str, handler: Handler, *, owner: str) -> None:
    _check_known(event)
    _handlers.setdefault(event, []).append((handler, owner))


def emit(event: str, payload: Mapping[str, object]) -> None:
    """Dispatch after commit, so a rolled-back operation emits nothing."""
    _check_known(event)
    transaction.on_commit(lambda: _dispatch(event, payload))


def _check_known(event: str) -> None:
    if event not in EVENTS:
        raise ValueError(f"Unknown event: {event}")


def _dispatch(event: str, payload: Mapping[str, object]) -> None:
    for handler, owner in _handlers.get(event, []):
        # The operation is already committed, so a handler must not fail it. The log carries
        # only the type: messages and payloads can contain answers or personal data.
        try:
            if is_enabled(owner):
                handler(payload)
        except Exception as exc:
            logger.error("Event %s: handler of %s failed: %s", event, owner, type(exc).__name__)
