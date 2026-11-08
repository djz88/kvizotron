import sqlite3

import pytest
from django.db import OperationalError

from tests.support import busy


def test_waiting_gives_up_within_seconds(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("app.domain.attempts.time.sleep", slept.append)

    def locked():
        raise OperationalError("database table is locked")

    with pytest.raises(OperationalError):
        busy.waiting(locked)
    assert sum(slept) < 5, "a lock that never clears must fail fast, not hang CI"


def test_waiting_returns_once_the_lock_clears():
    calls = iter([sqlite3.OperationalError, None])

    def flaky():
        if next(calls):
            raise OperationalError("database is locked")
        return "ok"

    assert busy.waiting(flaky) == "ok"
