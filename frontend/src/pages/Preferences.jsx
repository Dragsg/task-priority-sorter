import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  deleteOnboardingCalendar,
  fetchOnboardingContext,
  getStoredUser,
  updateCurrentUser,
  uploadOnboardingCalendar,
} from "../api";
import CalendarContextSummary from "../components/CalendarContextSummary";
import PageNav from "../components/PageNav";

export default function Preferences() {
  const navigate = useNavigate();
  const [user, setUser] = useState(() => getStoredUser());
  const [onboarding, setOnboarding] = useState(null);
  const [username, setUsername] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [calendarBusy, setCalendarBusy] = useState(false);
  const [usernameBusy, setUsernameBusy] = useState(false);
  const calendarInputRef = useRef(null);

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

  function handleCalendarPickerOpen() {
    if (calendarBusy) {
      return;
    }
    calendarInputRef.current?.click();
  }

  async function handleCalendarSelection(event) {
    const selectedFile = event.target.files?.[0] ?? null;
    if (!selectedFile) {
      return;
    }

    try {
      setCalendarBusy(true);
      setError("");
      setStatus("");
      const result = await uploadOnboardingCalendar(selectedFile);
      setOnboarding(result.onboarding);
      setStatus("Calendar context updated.");
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      event.target.value = "";
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
  const recurringInsightCount = onboarding.recurring_task_notes?.length ?? 0;
  const displayedInsightCount = busyWindowCount > 0
    ? Math.min(recurringInsightCount, busyWindowCount)
    : recurringInsightCount;

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
              <span>
                {calendarSource
                  ? displayedInsightCount > 0
                    ? `${displayedInsightCount} availability insights`
                    : `${busyWindowCount} upcoming busy windows`
                  : "0 availability insights"}
              </span>
            </div>
          </div>

          <CalendarContextSummary onboarding={onboarding} />

          <div className="calendar-upload-form">
            <input
              accept=".ics"
              className="onboarding-calendar-input"
              onChange={handleCalendarSelection}
              ref={calendarInputRef}
              type="file"
            />
            <div className="manual-task-actions">
              <button
                className="auth-button"
                disabled={calendarBusy}
                onClick={handleCalendarPickerOpen}
                type="button"
              >
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
          </div>
        </section>

        {status ? <p className="success-text">{status}</p> : null}
        {error ? <p className="error-text auth-error">{error}</p> : null}
      </section>
    </main>
  );
}
