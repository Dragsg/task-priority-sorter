import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  deleteOnboardingCalendar,
  fetchOnboardingContext,
  getStoredUser,
  updateCurrentUser,
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
  const [username, setUsername] = useState("");
  const [calendarFile, setCalendarFile] = useState(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [calendarBusy, setCalendarBusy] = useState(false);
  const [usernameBusy, setUsernameBusy] = useState(false);

  useEffect(() => {
    async function loadContext() {
      try {
        const data = await fetchOnboardingContext();
        setUser(data.user);
        setOnboarding(data.onboarding);
        setUsername(data.user?.username ?? "");
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

  async function handleUsernameUpdate(event) {
    event.preventDefault();

    try {
      setUsernameBusy(true);
      setError("");
      setStatus("");
      const result = await updateCurrentUser({ username });
      setUser(result.user);
      setUsername(result.user.username);
      setStatus("Username updated.");
    } catch (updateError) {
      setError(updateError.message);
    } finally {
      setUsernameBusy(false);
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
        <h1 className="simple-title">Manage your account settings</h1>
        <p className="simple-copy">
          You&apos;re signed in as <strong>{user.username}</strong>. Your onboarding answers are already
          saved, so this page lets you update your account username and calendar timing context.
        </p>
      </section>

      <section className="simple-card">
        <section className="calendar-panel">
          <div className="calendar-panel-header">
            <div>
              <p className="summary-label">Account</p>
              <p className="panel-copy">
                Update the username you use to sign in. This change is saved directly to your
                account record.
              </p>
            </div>
            <div className="summary-value summary-value-stack">
              <span>Display name: {user.name}</span>
              <span>Current username: {user.username}</span>
            </div>
          </div>

          <form className="calendar-upload-form" onSubmit={handleUsernameUpdate}>
            <label className="field-group">
              <span>Username</span>
              <input
                className="auth-input"
                disabled={usernameBusy}
                onChange={(event) => setUsername(event.target.value)}
                type="text"
                value={username}
              />
            </label>
            <div className="manual-task-actions">
              <button
                className="auth-button"
                disabled={usernameBusy || !username.trim() || username.trim() === user.username}
                type="submit"
              >
                {usernameBusy ? "Saving..." : "Save username"}
              </button>
            </div>
          </form>
        </section>

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
