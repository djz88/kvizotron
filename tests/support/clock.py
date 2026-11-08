"""Time under the test's control. Everything in the app asks `timezone.now()`."""

from datetime import datetime

import pytest
from django.utils import timezone


def freeze(monkeypatch: pytest.MonkeyPatch, when: datetime) -> None:
    monkeypatch.setattr(timezone, "now", lambda: when)
