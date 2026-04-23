import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  deleteOnboardingCalendar,
  fetchOnboardingContext,
  getStoredUser,
  uploadOnboardingCalendar,
} from "../api";
import PageNav from "../components/PageNav";

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

export default function Preferences() {
  const navigate = useNavigate();
  const [user, setUser] = useState(() => getStoredUser());
  const [onboarding, setOnboarding] = useState(null);
  const [calendarFile, setCalendarFile] = useState(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    async function loadContext() {
      try {
        const data = await fetchOnboardingContext();
        setUser(data.user);
        setOnboarding(data.onboarding);
      } catch {
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    loadContext();
  }, [navigate]);

  async function handleCalendarUpload(event) {
    event.preventDefault();
    if (!calendarFile) {
      setError("Choose a .ics file to upload.");
      return;
    }

    try {
      setBusy(true);
      setError("");
      setStatus("");
      const result = await uploadOnboardingCalendar(calendarFile);
      setOnboarding(result.onboarding);
      setCalendarFile(null);
      setStatus("Calendar context updated.");
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCalendarRemove() {
    try {
      setBusy(true);
      setError("");
      setStatus("");
      const result = await deleteOnboardingCalendar();
      setOnboarding(result.onboarding);
      setStatus("Calendar context removed.");
    } catch (removeError) {
      setError(removeError.message);
    } finally {
      setBusy(false);
    }
  }

  if (!user || !onboarding) {
    return <main className="simple-shell">Loading your preferences...</main>;
  }

  const calendarSource = onboarding.calendar_source;
  const busyWindowCount = onboarding.busy_windows?.length ?? 0;

  return (
    <main className="simple-shell">
      <PageNav />
      <section className="simple-hero">
        <p className="auth-eyebrow">Preferences</p>
        <h1 className="simple-title">Manage your calendar context</h1>
        <p className="simple-copy">
          You&apos;re signed in as <strong>{user.username}</strong>. Your onboarding answers are already
          saved, so this page only manages calendar timing context.
        </p>
      </section>

      <section className="simple-card">
        <section className="calendar-panel">
          <div className="calendar-panel-header">
            <div>
              <p className="summary-label">Calendar Context (.ics)</p>
              <p className="panel-copy">
                Upload one active `.ics` file to give the pipeline timetable context for the next
                21 days.
              </p>
            </div>
            <div className="summary-value summary-value-stack">
              <span>{calendarSource ? "Calendar linked" : "No calendar linked"}</span>
              <span>{busyWindowCount} busy windows stored</span>
            </div>
          </div>

          {calendarSource ? (
            <div className="calendar-summary">
              <p className="task-source-line">
                <span>File:</span> {calendarSource.filename}
              </p>
              <p className="task-source-line">
                <span>Uploaded:</span> {formatCalendarTimestamp(calendarSource.uploaded_at)}
              </p>
              <p className="task-source-line">
                <span>Timezone:</span>{" "}
                {calendarSource.calendar_timezone || onboarding.timezone || "Asia/Singapore"}
              </p>
              {onboarding.timetable_summary ? (
                <p className="task-source-line task-source-preview">
                  <span>Summary:</span> {onboarding.timetable_summary}
                </p>
              ) : null}
            </div>
          ) : null}

          <form className="calendar-upload-form" onSubmit={handleCalendarUpload}>
            <label className="field-group">
              <span>Calendar file</span>
              <input
                accept=".ics"
                className="auth-input auth-file-input"
                onChange={(event) => setCalendarFile(event.target.files?.[0] ?? null)}
                type="file"
              />
            </label>
            <div className="manual-task-actions">
              <button className="auth-button" disabled={busy} type="submit">
                {busy ? "Uploading..." : calendarSource ? "Replace calendar" : "Upload calendar"}
              </button>
              {calendarSource ? (
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={handleCalendarRemove}
                  type="button"
                >
                  Remove calendar
                </button>
              ) : null}
              <Link className="secondary-button" to="/home">
                Back to dashboard
              </Link>
            </div>
          </form>
        </section>

        {status ? <p className="success-text">{status}</p> : null}
        {error ? <p className="error-text auth-error">{error}</p> : null}
      </section>
    </main>
  );
}
