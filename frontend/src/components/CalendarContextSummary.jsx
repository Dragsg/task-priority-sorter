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
  const busyWindowCount = onboarding?.busy_windows?.length ?? 0;
  const recurringNotes = onboarding?.recurring_task_notes ?? [];
  const displayedRecurringNotes = recurringNotes.slice(
    0,
    busyWindowCount > 0 ? Math.min(recurringNotes.length, busyWindowCount) : recurringNotes.length
  );

  if (!calendarSource) {
    return null;
  }

  return (
    <>
      <div className="calendar-summary">
        <div className="calendar-detail-grid">
          <article className="calendar-detail-card">
            <p className="calendar-detail-label">File</p>
            <p className="calendar-detail-value">{calendarSource.filename}</p>
          </article>
          <article className="calendar-detail-card">
            <p className="calendar-detail-label">Uploaded</p>
            <p className="calendar-detail-value">{formatCalendarTimestamp(calendarSource.uploaded_at)}</p>
          </article>
          <article className="calendar-detail-card">
            <p className="calendar-detail-label">Timezone</p>
            <p className="calendar-detail-value">
              {calendarSource.calendar_timezone || onboarding?.timezone || "Asia/Singapore"}
            </p>
          </article>
          <article className="calendar-detail-card calendar-detail-card-wide">
            <p className="calendar-detail-label">Schedule overview</p>
            <p className="calendar-detail-value calendar-detail-value-soft">
              {onboarding?.timetable_summary || "No recurring schedule summary detected yet."}
            </p>
          </article>
        </div>
      </div>

      {displayedRecurringNotes.length ? (
        <div className="calendar-notes">
          <div className="calendar-notes-header">
            <p className="summary-label">Availability insights</p>
            <p className="calendar-notes-count">{displayedRecurringNotes.length} highlights</p>
          </div>
          <ul className="calendar-note-list">
            {displayedRecurringNotes.map((note) => (
              <li className="calendar-note-item" key={note}>
                {note}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}
