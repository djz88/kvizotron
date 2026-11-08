"""A busy timeout for threads in tests that use a real concurrent transaction."""

from collections.abc import Callable

from app.domain import attempts


def waiting[T](call: Callable[[], T]) -> T:
    """Repeat a call that met a lock.

    The test database is in memory with a shared cache, where a reader meeting a writer gets
    "table is locked" at once (SQLITE_LOCKED, no busy timeout). The file database in WAL mode
    never does that, so the retry only stands in for its busy timeout.
    """
    return attempts.with_retry(call, tries=8, base_delay=0.01)  # at most about 2.5 s in all
