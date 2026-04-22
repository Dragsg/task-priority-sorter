from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_now_naive() -> datetime:
    """Return a UTC timestamp without tzinfo for storage in naive UTC columns."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def current_hour_for_timezone(timezone_name: str, *, fallback: str = "Asia/Singapore") -> int:
    """Return the current local hour for a timezone, falling back safely when needed."""

    for candidate in (timezone_name, fallback, "Asia/Singapore", "UTC"):
        try:
            return datetime.now(ZoneInfo(candidate)).hour
        except ZoneInfoNotFoundError:
            continue
    return datetime.now(timezone.utc).hour
