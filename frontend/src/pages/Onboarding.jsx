import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
<<<<<<< HEAD
  fetchCurrentUser,
  getStoredUser,
  saveOnboardingPreferences,
  storeUser,
=======
  deleteOnboardingCalendar,
  fetchOnboardingContext,
  saveOnboardingPreferences,
  uploadOnboardingCalendar,
>>>>>>> 197cbed (WIP: local changes before syncing main)
} from "../api";
import PageNav from "../components/PageNav";
import { PREFERENCE_OPTIONS } from "../preferences";

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

export default function Onboarding() {
  const navigate = useNavigate();
  const [user, setUser] = useState(() => getStoredUser());
  const [preferences, setPreferences] = useState("");
  const [onboarding, setOnboarding] = useState(null);
  const [calendarFile, setCalendarFile] = useState(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [calendarBusy, setCalendarBusy] = useState(false);

  useEffect(() => {
    async function loadContext() {
      try {
        const data = await fetchOnboardingContext();
        setUser(data.user);
        setOnboarding(data.onboarding);
        const savedPreference =
          data.user?.preferences || data.onboarding?.static_preferences?.focus_preference || "";
        setPreferences(savedPreference);
      } catch {
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    loadContext();
  }, [navigate]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!preferences) {
      setError("Please choose one option before continuing.");
      return;
    }

    try {
      setBusy(true);
      setError("");
<<<<<<< HEAD
      await saveOnboardingPreferences(preferences);
      if (user) {
        const updatedUser = { ...user, preferences };
        setUser(updatedUser);
        storeUser(updatedUser);
      }
      navigate("/home");
=======
      setStatus("");
      const result = await saveOnboardingPreferences(preferences);
      setUser(result.user);
      setStatus("Preferences saved.");
>>>>>>> 197cbed (WIP: local changes before syncing main)
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

<<<<<<< HEAD
=======
  async function handleCalendarUpload(event) {
    event.preventDefault();
    if (!calendarFile) {
      setError("Choose a .ics file to upload.");
      return;
    }

    try {
      setCalendarBusy(true);
      setError("");
      setStatus("");
      const result = await uploadOnboardingCalendar(calendarFile);
      setOnboarding(result.onboarding);
      setCalendarFile(null);
      setStatus("Calendar context updated.");
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setCalendarBusy(false);
    }
  }

  async function handleCalendarRemove() {
    try {
      setCalendarBusy(true);
      setError("");
      setStatus("");
      const result = await deleteOnboardingCalendar();
      setOnboarding(result.onboarding);
      setStatus("Calendar context removed.");
    } catch (removeError) {
      setError(removeError.message);
    } finally {
      setCalendarBusy(false);
    }
  }

  if (!user || !onboarding) {
    return <main className="simple-shell">Loading your setup...</main>;
  }

  const calendarSource = onboarding.calendar_source;
  const busyWindowCount = onboarding.busy_windows?.length ?? 0;

>>>>>>> 197cbed (WIP: local changes before syncing main)
  return (
    <main className="simple-shell">
      <PageNav />
      <section className="simple-hero">
        <p className="auth-eyebrow">Preferences</p>
        <h1 className="simple-title">Shape the context your queue learns from</h1>
        <p className="simple-copy">
<<<<<<< HEAD
          You&apos;re signed in as <strong>{user?.email ?? "your account"}</strong>.
          Choose the context you want this workspace to support first.
=======
          You&apos;re signed in as <strong>{user.email}</strong>. Set your main focus mode and
          optionally add a calendar file for timing context.
>>>>>>> 197cbed (WIP: local changes before syncing main)
        </p>
        <p className="simple-note">
          Calendar uploads are used only as scheduling context. The system stores normalized busy
          windows and summaries, not the raw `.ics` text.
        </p>
      </section>

      <section className="simple-card">
        <form className="option-form" onSubmit={handleSubmit}>
          {PREFERENCE_OPTIONS.map((option) => (
            <label className="option-row" key={option.value}>
              <input
                checked={preferences === option.value}
                name="preferences"
                onChange={() => setPreferences(option.value)}
                type="radio"
              />
              <span>
                <strong>{option.title}</strong>
                <small>{option.description}</small>
              </span>
            </label>
          ))}

          <div className="manual-task-actions">
            <button className="auth-button" disabled={busy} type="submit">
              {busy ? "Saving..." : "Save preferences"}
            </button>
            <button
              className="secondary-button"
              onClick={() => navigate("/home")}
              type="button"
            >
              Back to queue
            </button>
          </div>
        </form>

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
              <button className="auth-button" disabled={calendarBusy} type="submit">
                {calendarBusy ? "Uploading..." : calendarSource ? "Replace calendar" : "Upload calendar"}
              </button>
              {calendarSource ? (
                <button
                  className="secondary-button"
                  disabled={calendarBusy}
                  onClick={handleCalendarRemove}
                  type="button"
                >
                  Remove calendar
                </button>
              ) : null}
            </div>
          </form>

          {onboarding.recurring_task_notes?.length ? (
            <div className="calendar-notes">
              <p className="summary-label">Recurring Notes</p>
              {onboarding.recurring_task_notes.map((note) => (
                <p className="task-source-line" key={note}>
                  {note}
                </p>
              ))}
            </div>
          ) : null}
        </section>

        {status ? <p className="success-text">{status}</p> : null}
        {error ? <p className="error-text auth-error">{error}</p> : null}
      </section>
    </main>
  );
}
