"""Failed access codes per client address: a sliding minute in process memory (ADR-0030)."""

import threading

from django.conf import settings
from django.http import HttpRequest

WINDOW = 60.0
_SWEEP_AT = 1000  # addresses tracked before idle ones are dropped
_failures: dict[str, list[float]] = {}
_lock = threading.Lock()


def client_ip(request: HttpRequest) -> str:
    """Caddy writes the real client address as the only X-Forwarded-For value."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    first = forwarded.split(",")[0].strip()
    return first or request.META.get("REMOTE_ADDR", "")


def _recent(ip: str, now: float) -> list[float]:
    recent = [moment for moment in _failures.get(ip, []) if now - moment < WINDOW]
    if recent:
        _failures[ip] = recent
    else:
        _failures.pop(ip, None)
    return recent


def allow(ip: str, now: float) -> bool:
    with _lock:
        return len(_recent(ip, now)) < settings.KVZ_CODE_ATTEMPTS_PER_MINUTE


def failed(ip: str, now: float) -> None:
    with _lock:
        if len(_failures) >= _SWEEP_AT:
            _sweep(now)
        _recent(ip, now)
        _failures.setdefault(ip, []).append(now)


def _sweep(now: float) -> None:
    for ip in list(_failures):
        _recent(ip, now)


def sweep(now: float) -> None:
    with _lock:
        _sweep(now)


def tracked() -> int:
    with _lock:
        return len(_failures)


def reset() -> None:
    with _lock:
        _failures.clear()
