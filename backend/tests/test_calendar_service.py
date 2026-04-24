from datetime import datetime, timedelta

from app.calendar_service import parse_calendar_context


def _local_ics_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def test_timetable_summary_prefers_recurring_schedule_over_one_off_exams():
    now = datetime.now()
    current_monday = now - timedelta(days=now.weekday())
    recurring_start_monday = (current_monday - timedelta(weeks=8)).replace(hour=11, minute=30, second=0, microsecond=0)
    recurring_start_wednesday = (current_monday - timedelta(weeks=8) + timedelta(days=2)).replace(
        hour=9,
        minute=30,
        second=0,
        microsecond=0,
    )
    upcoming_tuesday = (current_monday + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
    upcoming_thursday = (current_monday + timedelta(days=3)).replace(hour=13, minute=0, second=0, microsecond=0)

    calendar_text = "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:mon-class",
            "SUMMARY:Regular Monday Class",
            f"DTSTART:{_local_ics_stamp(recurring_start_monday)}",
            f"DTEND:{_local_ics_stamp(recurring_start_monday + timedelta(hours=3))}",
            "RRULE:FREQ=WEEKLY;COUNT=10;BYDAY=MO",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:wed-class",
            "SUMMARY:Regular Wednesday Class",
            f"DTSTART:{_local_ics_stamp(recurring_start_wednesday)}",
            f"DTEND:{_local_ics_stamp(recurring_start_wednesday + timedelta(hours=4))}",
            "RRULE:FREQ=WEEKLY;COUNT=10;BYDAY=WE",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:tue-exam",
            "SUMMARY:One-off Tuesday Exam",
            f"DTSTART:{_local_ics_stamp(upcoming_tuesday)}",
            f"DTEND:{_local_ics_stamp(upcoming_tuesday + timedelta(hours=2))}",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:thu-exam",
            "SUMMARY:One-off Thursday Exam",
            f"DTSTART:{_local_ics_stamp(upcoming_thursday)}",
            f"DTEND:{_local_ics_stamp(upcoming_thursday + timedelta(hours=2))}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )

    context = parse_calendar_context(
        filename="timetable.ics",
        file_bytes=calendar_text.encode("utf-8"),
        timezone_name="Asia/Singapore",
    )

    summary = context["timetable_summary"]
    assert "Monday" in summary
    assert "Wednesday" in summary
    assert "Tuesday and Thursday" not in summary


def test_recurring_notes_align_with_schedule_summary():
    now = datetime.now()
    current_monday = now - timedelta(days=now.weekday())
    recurring_start_monday = (current_monday - timedelta(weeks=8)).replace(hour=11, minute=30, second=0, microsecond=0)
    recurring_start_wednesday = (current_monday - timedelta(weeks=8) + timedelta(days=2)).replace(
        hour=9,
        minute=30,
        second=0,
        microsecond=0,
    )
    upcoming_friday = (current_monday + timedelta(days=4)).replace(hour=15, minute=30, second=0, microsecond=0)

    calendar_text = "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:mon-class",
            "SUMMARY:Regular Monday Class",
            f"DTSTART:{_local_ics_stamp(recurring_start_monday)}",
            f"DTEND:{_local_ics_stamp(recurring_start_monday + timedelta(hours=3))}",
            "RRULE:FREQ=WEEKLY;COUNT=10;BYDAY=MO",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:wed-class",
            "SUMMARY:Regular Wednesday Class",
            f"DTSTART:{_local_ics_stamp(recurring_start_wednesday)}",
            f"DTEND:{_local_ics_stamp(recurring_start_wednesday + timedelta(hours=4))}",
            "RRULE:FREQ=WEEKLY;COUNT=10;BYDAY=WE",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:fri-one-off",
            "SUMMARY:One-off Friday Event",
            f"DTSTART:{_local_ics_stamp(upcoming_friday)}",
            f"DTEND:{_local_ics_stamp(upcoming_friday + timedelta(minutes=50))}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )

    context = parse_calendar_context(
        filename="timetable.ics",
        file_bytes=calendar_text.encode("utf-8"),
        timezone_name="Asia/Singapore",
    )

    notes = context["recurring_task_notes"]
    joined_notes = " ".join(notes)
    summary = context["timetable_summary"]
    assert "Monday is typically busiest around 11:30-14:30." in joined_notes
    assert "Wednesday is typically busiest around 09:30-13:30." in joined_notes
    if "mornings are usually the most open" in summary.lower():
        assert "Mornings are usually the most open." in joined_notes
    elif "afternoons are usually the most open" in summary.lower():
        assert "Afternoons are usually the most open." in joined_notes
    else:
        assert "Evenings are usually the most open." in joined_notes
    assert "Friday" not in joined_notes
