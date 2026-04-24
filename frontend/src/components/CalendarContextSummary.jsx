function formatCalendarTimestamp(value) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

export default function CalendarContextSummary({ onboarding }) {
  const calendarSource = onboarding?.calendar_source;
  const recurringNotes = onboarding?.recurring_task_notes ?? [];

  if (!calendarSource) {
    return null;
  }

  return (
    <>
      <div className="calendar-summary">
        <p className="task-source-line">
          <span>File:</span> {calendarSource.filename}
        </p>
        <p className="task-source-line">
          <span>Uploaded:</span> {formatCalendarTimestamp(calendarSource.uploaded_at)}
        </p>
        <p className="task-source-line">
          <span>Timezone:</span> {calendarSource.calendar_timezone || onboarding?.timezone || "Asia/Singapore"}
        </p>
        {onboarding?.timetable_summary ? (
          <p className="task-source-line task-source-preview">
            <span>Schedule pattern:</span> {onboarding.timetable_summary}
          </p>
        ) : null}
      </div>

      {recurringNotes.length ? (
        <div className="calendar-notes">
          <p className="summary-label">Busy / Free pattern</p>
          <ul className="calendar-note-list">
            {recurringNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}
