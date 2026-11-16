"""Request limits per client address: named sliding-minute buckets in process memory (ADR-0030)."""

import threading

from django.conf import settings
from django.http import HttpRequest

WINDOW = 60.0
BUCKETS = ("login", "code", "submit", "start", "login_address")
_SETTING = {
    "login": "KVZ_LOGIN_ATTEMPTS_PER_MINUTE",
    "code": "KVZ_CODE_ATTEMPTS_PER_MINUTE",
    "submit": "KVZ_SUBMITS_PER_MINUTE",
    "start": "KVZ_STARTS_PER_MINUTE",
    "login_address": "KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE",
}
_SWEEP_AT = 1000  # keys tracked before idle ones are dropped
_events: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()


def client_ip(request: HttpRequest) -> str:
    """The N-th X-Forwarded-For value from the right, N = KVZ_TRUSTED_PROXIES (ADR-0066).

    That is the value the outermost trusted proxy appended; values further left came from the
    client or proxies we do not know, so they can be forged.
    Caddy writes one value; with no trusted proxy the address of the connection counts.
    """
    hops: int = settings.KVZ_TRUSTED_PROXIES
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    values = [value.strip() for value in forwarded.split(",") if value.strip()]
    if hops and values:
        return values[-min(hops, len(values))]
    return request.META.get("REMOTE_ADDR", "").strip() or "unknown"


def _limit(bucket: str) -> int:
    value: int = getattr(settings, _SETTING[bucket])  # KeyError for an unknown bucket
    return value


def _recent(key: tuple[str, str], now: float) -> list[float]:
    recent = [moment for moment in _events.get(key, []) if now - moment < WINDOW]
    if recent:
        _events[key] = recent
    else:
        _events.pop(key, None)
    return recent


def allow(bucket: str, key: str, now: float) -> bool:
    limit = _limit(bucket)
    with _lock:
        return len(_recent((bucket, key), now)) < limit


def record(bucket: str, key: str, now: float) -> None:
    _limit(bucket)  # refuses an unknown bucket before anything is stored
    with _lock:
        if len(_events) >= _SWEEP_AT:
            _sweep(now)
        _recent((bucket, key), now)
        _events.setdefault((bucket, key), []).append(now)


def try_acquire(bucket: str, key: str, now: float) -> bool:
    """Check the window and take a slot under one lock, so parallel callers cannot all pass.

    A refusal stores nothing. `release` gives a taken slot back.
    """
    limit = _limit(bucket)
    with _lock:
        if len(_events) >= _SWEEP_AT:
            _sweep(now)
        recent = _recent((bucket, key), now)
        if len(recent) >= limit:
            return False
        _events.setdefault((bucket, key), []).append(now)
        return True


def release(bucket: str, key: str) -> None:
    """Remove the newest event of the key; nothing when there is none."""
    with _lock:
        events = _events.get((bucket, key))
        if not events:
            return
        events.pop()
        if not events:
            del _events[(bucket, key)]


def retry_after() -> str:
    return str(int(WINDOW))


def _sweep(now: float) -> None:
    for key in list(_events):
        _recent(key, now)


def sweep(now: float) -> None:
    with _lock:
        _sweep(now)


def tracked() -> int:
    with _lock:
        return len(_events)


def reset() -> None:
    with _lock:
        _events.clear()
