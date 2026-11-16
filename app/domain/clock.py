"""Times are stored in UTC, and read and shown in the one configured zone (FR-10, ADR-0048)."""

import os
import time
from datetime import UTC, date, datetime
from typing import Any

from django.utils import timezone

from app.domain import settings

FORM_FORMAT = "%Y-%m-%dT%H:%M"
SHOWN_FORMAT = "%Y-%m-%d %H:%M %Z"
EXACT_FORMAT = "%Y-%m-%d %H:%M:%S %Z"
NO_SUCH_TIME = "this time does not exist"


def whole_second(value: datetime) -> datetime:
    """The unit deadlines are compared in (ADR-0025)."""
    return value.replace(microsecond=0)


def parse_local(value: str) -> datetime:
    """An entered time, read in the configured zone. Raises ValueError for what cannot be used.

    A time the clock change skips does not exist, so it is refused. One that happens twice takes
    the first occurrence.
    """
    naive = datetime.fromisoformat(value)
    if naive.tzinfo is not None:
        raise ValueError("a time is read in the configured zone")
    zone = settings.zone()
    utc = naive.replace(tzinfo=zone).astimezone(UTC)
    if utc.astimezone(zone).replace(tzinfo=None) != naive:
        raise ValueError(NO_SUCH_TIME)
    return utc


def shown(value: datetime | None) -> str:
    return value.astimezone(settings.zone()).strftime(SHOWN_FORMAT) if value else "–"


def iso(value: datetime | None) -> str:
    """ISO 8601 with the offset of the configured zone, for files a machine reads."""
    return value.astimezone(settings.zone()).isoformat(timespec="seconds") if value else ""


def local_date(value: datetime) -> date:
    """The calendar date of a moment in the configured zone (the name of a day's backup)."""
    return value.astimezone(settings.zone()).date()


def form_value(value: datetime | None) -> str:
    """What a `datetime-local` field needs."""
    return value.astimezone(settings.zone()).strftime(FORM_FORMAT) if value else ""


def server_zone() -> str:
    """The zone the server process runs in (`TZ`), which can differ from the configured one."""
    return os.environ.get("TZ") or time.tzname[0]


def server_clock() -> dict[str, Any]:
    now = timezone.now()
    zone = settings.zone()
    return {
        "epoch": int(now.timestamp()),
        "text": now.astimezone(zone).strftime(EXACT_FORMAT),
        "zone": zone.key,
        "utc": now.astimezone(UTC).strftime(EXACT_FORMAT),
        "server_zone": server_zone(),
        "server_text": now.astimezone().strftime(EXACT_FORMAT),
    }
