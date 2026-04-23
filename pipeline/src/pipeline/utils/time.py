from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SINGAPORE_TIMEZONE_NAME = "Asia/Singapore"
SINGAPORE_TIMEZONE = ZoneInfo(SINGAPORE_TIMEZONE_NAME)


def singapore_now() -> datetime:
    return datetime.now(SINGAPORE_TIMEZONE)


def utc_now_naive() -> datetime:
    """Return a Singapore-local timestamp without tzinfo for naive timestamp columns."""

    return singapore_now().replace(tzinfo=None)


def current_hour_for_timezone(timezone_name: str, *, fallback: str = "Asia/Singapore") -> int:
    """Return the current local hour for a timezone, falling back safely when needed."""

    for candidate in (timezone_name, fallback, "Asia/Singapore", "UTC"):
        try:
            return datetime.now(ZoneInfo(candidate)).hour
        except ZoneInfoNotFoundError:
            continue
    return singapore_now().hour
