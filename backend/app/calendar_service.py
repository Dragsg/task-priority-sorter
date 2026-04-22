from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

_MERGE_GAP = timedelta(minutes=15)
_MAX_WINDOWS = 60
_LOOKAHEAD_DAYS = 21
_SUMMARY_REFERENCE_DAYS = 180
_MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def validate_calendar_upload(*, filename: str | None, file_bytes: bytes) -> None:
    if not filename or not filename.lower().endswith(".ics"):
        raise ValueError("Only .ics calendar files are supported.")
    if not file_bytes:
        raise ValueError("Calendar file is empty.")
    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        raise ValueError("Calendar file must be 2 MB or smaller.")


def parse_calendar_context(
    *,
    filename: str,
    file_bytes: bytes,
    timezone_name: str,
    lookahead_days: int = _LOOKAHEAD_DAYS,
) -> dict[str, Any]:
    validate_calendar_upload(filename=filename, file_bytes=file_bytes)

    try:
        from dateutil.rrule import rruleset, rrulestr
        from icalendar import Calendar
    except ImportError as exc:  # pragma: no cover - dependency managed by requirements
        missing_package = exc.name or "calendar parser dependency"
        raise RuntimeError(
            "Calendar parsing dependency is missing: "
            f"{missing_package}. Install the backend requirements with the same "
            "Python interpreter that runs Flask, for example "
            "`python -m pip install -r backend/requirements.txt`, then restart the backend."
        ) from exc

    user_tz = ZoneInfo(timezone_name or "Asia/Singapore")
    calendar = Calendar.from_ical(BytesIO(file_bytes).read())
    calendar_timezone = str(calendar.get("X-WR-TIMEZONE") or timezone_name or "Asia/Singapore")
    now = datetime.now(user_tz)
    horizon_end = now + timedelta(days=lookahead_days)

    windows: list[tuple[datetime, datetime, str | None]] = []
    recurring_reference_windows: list[tuple[datetime, datetime, str | None]] = []
    for component in calendar.walk():
        if component.name != "VEVENT":
            continue
        if str(component.get("STATUS") or "").upper() == "CANCELLED":
            continue

        dtstart = _coerce_datetime(component.decoded("DTSTART"), calendar_timezone, user_tz)
        dtend_raw = component.get("DTEND")
        dtend_value = component.decoded("DTEND") if dtend_raw else None
        dtend = _coerce_datetime(dtend_value, calendar_timezone, user_tz) if dtend_value is not None else None
        if dtstart is None:
            continue
        if dtend is None or dtend <= dtstart:
            dtend = dtstart + _default_duration(component.decoded("DTSTART"))

        summary = str(component.get("SUMMARY") or "").strip() or None
        duration = dtend - dtstart
        for occurrence_start, occurrence_end in _expand_event_occurrences(
            component=component,
            dtstart=dtstart,
            duration=duration,
            window_start=now,
            window_end=horizon_end,
            rruleset_factory=rruleset,
            rrulestr_fn=rrulestr,
            calendar_timezone=calendar_timezone,
            user_tz=user_tz,
        ):
            windows.append((occurrence_start, occurrence_end, summary))

        if component.get("RRULE"):
            recurring_reference_end = max(
                horizon_end,
                dtstart + timedelta(days=_SUMMARY_REFERENCE_DAYS),
            )
            for occurrence_start, occurrence_end in _expand_event_occurrences(
                component=component,
                dtstart=dtstart,
                duration=duration,
                window_start=dtstart,
                window_end=recurring_reference_end,
                rruleset_factory=rruleset,
                rrulestr_fn=rrulestr,
                calendar_timezone=calendar_timezone,
                user_tz=user_tz,
            ):
                recurring_reference_windows.append((occurrence_start, occurrence_end, summary))

    merged = _merge_windows(sorted(windows, key=lambda item: item[0]))
    recurring_reference = _merge_windows(
        sorted(recurring_reference_windows, key=lambda item: item[0])
    )
    normalized_windows = [
        {
            "start_iso": start.isoformat(),
            "end_iso": end.isoformat(),
            "label": label,
        }
        for start, end, label in merged[:_MAX_WINDOWS]
    ]

    summary_windows = recurring_reference or merged
    recurring_notes = _derive_recurring_notes(summary_windows)
    timetable_summary = _build_timetable_summary(
        summary_windows,
        lookahead_days=lookahead_days,
        uses_recurring_reference=bool(recurring_reference),
    )

    return {
        "busy_windows": normalized_windows,
        "recurring_task_notes": recurring_notes,
        "timetable_summary": timetable_summary,
        "calendar_source": {
            "type": "ics",
            "filename": filename,
            "uploaded_at": datetime.now(user_tz).isoformat(),
            "source_hash": hashlib.sha256(file_bytes).hexdigest(),
            "calendar_timezone": calendar_timezone,
            "lookahead_days": lookahead_days,
        },
        "has_calendar": bool(normalized_windows),
    }


def clear_calendar_context() -> dict[str, Any]:
    return {
        "busy_windows": [],
        "recurring_task_notes": [],
        "timetable_summary": None,
        "calendar_source": None,
        "has_calendar": False,
    }


def _coerce_datetime(value: Any, timezone_name: str, user_tz: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(timezone_name))
        return value.astimezone(user_tz)
    if isinstance(value, date):
        midnight = datetime.combine(value, time.min)
        return midnight.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(user_tz)
    return None


def _default_duration(decoded_start: Any) -> timedelta:
    if isinstance(decoded_start, date) and not isinstance(decoded_start, datetime):
        return timedelta(days=1)
    return timedelta(hours=1)


def _expand_event_occurrences(
    *,
    component,
    dtstart: datetime,
    duration: timedelta,
    window_start: datetime,
    window_end: datetime,
    rruleset_factory,
    rrulestr_fn,
    calendar_timezone: str,
    user_tz: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    rrule_value = component.get("RRULE")
    if not rrule_value:
        if dtstart > window_end or dtstart + duration < window_start:
            return []
        return [(max(dtstart, window_start), min(dtstart + duration, window_end))]

    rule_set = rruleset_factory()
    rule_set.rrule(rrulestr_fn(rrule_value.to_ical().decode(), dtstart=dtstart))
    for exdate in _iter_exdates(component, calendar_timezone, user_tz):
        rule_set.exdate(exdate)

    occurrences: list[tuple[datetime, datetime]] = []
    for occurrence in rule_set.between(window_start - duration, window_end, inc=True):
        occurrence_end = occurrence + duration
        if occurrence_end < window_start or occurrence > window_end:
            continue
        occurrences.append((max(occurrence, window_start), min(occurrence_end, window_end)))
    return occurrences


def _iter_exdates(component, timezone_name: str, user_tz: ZoneInfo) -> list[datetime]:
    values = component.get("EXDATE")
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]

    result: list[datetime] = []
    for exdate in values:
        dates = exdate.dts if hasattr(exdate, "dts") else []
        for item in dates:
            coerced = _coerce_datetime(item.dt, timezone_name, user_tz)
            if coerced is not None:
                result.append(coerced)
    return result


def _merge_windows(windows: list[tuple[datetime, datetime, str | None]]) -> list[tuple[datetime, datetime, str | None]]:
    if not windows:
        return []

    merged: list[tuple[datetime, datetime, str | None]] = [windows[0]]
    for start, end, label in windows[1:]:
        last_start, last_end, last_label = merged[-1]
        if start <= last_end + _MERGE_GAP:
            merged[-1] = (
                last_start,
                max(last_end, end),
                last_label if last_label == label else last_label or label,
            )
            continue
        merged.append((start, end, label))
    return merged


def _derive_recurring_notes(windows: list[tuple[datetime, datetime, str | None]]) -> list[str]:
    grouped: dict[tuple[int, str, str], int] = defaultdict(int)
    for start, end, _label in windows:
        key = (start.weekday(), start.strftime("%H:%M"), end.strftime("%H:%M"))
        grouped[key] += 1

    notes: list[str] = []
    for (weekday, start_label, end_label), count in sorted(grouped.items(), key=lambda item: (-item[1], item[0][0], item[0][1])):
        if count < 2:
            continue
        notes.append(f"{_WEEKDAY_NAMES[weekday]} usually stays busy around {start_label}-{end_label}.")
        if len(notes) >= 5:
            break
    return notes


def _build_timetable_summary(
    windows: list[tuple[datetime, datetime, str | None]],
    *,
    lookahead_days: int,
    uses_recurring_reference: bool = False,
) -> str | None:
    if not windows:
        return f"No busy calendar windows detected in the next {lookahead_days} days."

    weekday_minutes = Counter()
    daypart_minutes = Counter()
    for start, end, _label in windows:
        minutes = max(int((end - start).total_seconds() // 60), 0)
        weekday_minutes[start.weekday()] += minutes
        midpoint_hour = start.hour
        if midpoint_hour < 12:
            daypart_minutes["morning"] += minutes
        elif midpoint_hour < 18:
            daypart_minutes["afternoon"] += minutes
        else:
            daypart_minutes["evening"] += minutes

    busiest_days = [weekday for weekday, _minutes in weekday_minutes.most_common(2)]
    busiest_days = sorted(busiest_days)
    calmest_daypart = min(("morning", "afternoon", "evening"), key=lambda key: daypart_minutes.get(key, 0))
    busiest_label = " and ".join(_WEEKDAY_NAMES[index] for index in busiest_days)
    if uses_recurring_reference:
        return f"Regular schedule is busiest on {busiest_label}; {calmest_daypart}s are usually the most open."
    return f"Busiest on {busiest_label}; {calmest_daypart}s look the most open."
