from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SINGAPORE_TIMEZONE_NAME = "Asia/Singapore"
SINGAPORE_TIMEZONE = ZoneInfo(SINGAPORE_TIMEZONE_NAME)


def now_sgt() -> datetime:
    return datetime.now(SINGAPORE_TIMEZONE)


def to_sgt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=SINGAPORE_TIMEZONE)
    return value.astimezone(SINGAPORE_TIMEZONE)


def parse_iso_to_sgt(value: str | None) -> datetime | None:
    if not value:
        return None
    return to_sgt(datetime.fromisoformat(value.replace("Z", "+00:00")))
