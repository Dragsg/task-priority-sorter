import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  deleteCurrentUser,
  deleteOnboardingCalendar,
  fetchOnboardingContext,
  getStoredUser,
  getStoredUserId,
  storeUser,
  updateCurrentUser,
  uploadOnboardingCalendar,
} from "../api";
import CalendarContextSummary from "../components/CalendarContextSummary";
import { clearOnboardingCache, readOnboardingCache, writeOnboardingCache } from "../onboardingCache";
import PageNav from "../components/PageNav";

export default function Preferences() {
  const navigate = useNavigate();
  const storedUserId = getStoredUserId();
  const storedUser = getStoredUser();
  const [cachedOnboarding] = useState(() => readOnboardingCache(storedUserId));
  const [user, setUser] = useState(() => cachedOnboarding?.user ?? storedUser);
  const [onboarding, setOnboarding] = useState(() => cachedOnboarding?.onboarding ?? null);
  const [username, setUsername] = useState(() => (cachedOnboarding?.user ?? storedUser)?.username ?? "");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [calendarBusy, setCalendarBusy] = useState(false);
  const [usernameBusy, setUsernameBusy] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const calendarInputRef = useRef(null);

  useEffect(() => {
    let isCancelled = false;

    async function loadContext() {
      try {
        const data = await fetchOnboardingContext();
        if (isCancelled) {
          return;
        }
        setUser(data.user);
        setOnboarding(data.onboarding);
        setUsername(data.user?.username ?? "");
        setError("");
      } catch (loadError) {
        if (isCancelled) {
          return;
        }
        if (cachedOnboarding) {
          setError(loadError.message || "Using your saved account settings while fresh context loads.");
          return;
        }
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    loadContext();

    return () => {
      isCancelled = true;
    };
  }, [cachedOnboarding, navigate]);

  useEffect(() => {
    if (!user?.userId || !onboarding) {
      return;
    }
    writeOnboardingCache(user.userId, user, onboarding);
  }, [onboarding, user]);

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
      storeUser(result.user);
      setStatus("Username updated.");
    } catch (updateError) {
      setError(updateError.message);
    } finally {
      setUsernameBusy(false);
    }
  }

  async function handleAccountDelete(event) {
    event.preventDefault();

    try {
      setDeleteBusy(true);
      setDeleteError("");
      setStatus("");
      await deleteCurrentUser({ username: deleteConfirmation });
      clearOnboardingCache(user?.userId);
      clearStoredToken();
      navigate("/", { replace: true });
    } catch (deleteRequestError) {
      setDeleteError(deleteRequestError.message);
    } finally {
      setDeleteBusy(false);
    }
  }

  function openDeleteDialog() {
    setDeleteConfirmation("");
    setDeleteError("");
    setIsDeleteDialogOpen(true);
  }

  function closeDeleteDialog() {
    if (deleteBusy) {
      return;
    }
    setDeleteConfirmation("");
    setDeleteError("");
    setIsDeleteDialogOpen(false);
  }

  if (!user) {
    return <main className="simple-shell">Loading your account settings...</main>;
  }

  const calendarSource = onboarding?.calendar_source;
  const busyWindowCount = onboarding?.busy_windows?.length ?? 0;
  const recurringInsightCount = onboarding?.recurring_task_notes?.length ?? 0;
  const displayedInsightCount = busyWindowCount > 0
    ? Math.min(recurringInsightCount, busyWindowCount)
    : recurringInsightCount;

  return (
    <main className="simple-shell">
      <PageNav />
      <section className="simple-hero">
        <p className="auth-eyebrow">Account</p>
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
              <span>
                {onboarding
                  ? calendarSource
                    ? "Calendar linked"
                    : "No calendar linked"
                  : "Loading calendar context"}
              </span>
              <span>
                {!onboarding
                  ? "Checking saved availability insights"
                  : calendarSource
                  ? displayedInsightCount > 0
                    ? `${displayedInsightCount} availability insights`
                    : `${busyWindowCount} upcoming busy windows`
                  : "0 availability insights"}
              </span>
            </div>
          </div>

          <CalendarContextSummary onboarding={onboarding} />

          {!onboarding ? (
            <p className="panel-copy">Loading your saved calendar context...</p>
          ) : null}

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
                  disabled={calendarBusy || !onboarding}
                  onClick={handleCalendarRemove}
                  type="button"
                >
                  Remove calendar
                </button>
              ) : null}
            </div>
          </div>
        </section>

        <section className="calendar-panel danger-panel">
          <div className="calendar-panel-header">
            <div>
              <p className="summary-label">Delete Account</p>
            </div>
            <div className="summary-value summary-value-stack">
              <span>Permanent action</span>
              <span>Cannot be undone</span>
            </div>
          </div>

          <div className="manual-task-actions">
            <button
              className="auth-button danger-button"
              onClick={openDeleteDialog}
              type="button"
            >
              Delete account
            </button>
          </div>
        </section>

        {status ? <p className="success-text">{status}</p> : null}
        {error ? <p className="error-text auth-error">{error}</p> : null}
      </section>

      {isDeleteDialogOpen ? (
        <div
          aria-modal="true"
          className="modal-backdrop"
          onClick={closeDeleteDialog}
          role="dialog"
        >
          <div
            className="confirm-dialog"
            onClick={(event) => event.stopPropagation()}
          >
            <p className="summary-label">Confirm Account Deletion</p>
            <h2 className="confirm-dialog-title">Delete this account permanently?</h2>
            <p className="panel-copy">
              This will permanently delete your account and all related data.
            </p>
            <div className="danger-panel-note">
              Type <strong>{user.username}</strong> to confirm deletion.
            </div>
            <form className="calendar-upload-form" onSubmit={handleAccountDelete}>
              <label className="field-group">
                <span>Confirm username</span>
                <input
                  autoComplete="off"
                  autoFocus
                  className="auth-input"
                  disabled={deleteBusy}
                  onChange={(event) => setDeleteConfirmation(event.target.value)}
                  placeholder={user.username}
                  type="text"
                  value={deleteConfirmation}
                />
              </label>
              {deleteError ? <p className="error-text auth-error">{deleteError}</p> : null}
              <div className="manual-task-actions confirm-dialog-actions">
                <button
                  className="secondary-button"
                  disabled={deleteBusy}
                  onClick={closeDeleteDialog}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="auth-button danger-button"
                  disabled={deleteBusy || deleteConfirmation.trim() !== user.username}
                  type="submit"
                >
                  {deleteBusy ? "Deleting account..." : "Delete permanently"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </main>
  );
}
