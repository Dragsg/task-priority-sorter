import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  createTelegramLinkCode,
  deleteCurrentUser,
  deleteOnboardingCalendar,
  disconnectTelegram,
  fetchOnboardingContext,
  fetchTelegramSettings,
  getStoredUser,
  getStoredUserId,
  saveTelegramSettings,
  sendTelegramTestMessage,
  storeUser,
  updateCurrentUser,
  uploadOnboardingCalendar,
} from "../api";
import CalendarContextSummary from "../components/CalendarContextSummary";
import { clearOnboardingCache, readOnboardingCache, writeOnboardingCache } from "../onboardingCache";
import PageNav from "../components/PageNav";

const DEFAULT_TELEGRAM_SETTINGS = {
  telegramEnabled: true,
  instantCritical: true,
  instantHigh: true,
  instantMedium: false,
  instantLow: false,
  dailyDigestEnabled: true,
  dailyDigestTime: "08:00",
};

export default function Preferences() {
  const navigate = useNavigate();
  const storedUserId = getStoredUserId();
  const storedUser = getStoredUser();
  const [cachedOnboarding] = useState(() => readOnboardingCache(storedUserId));
  const [user, setUser] = useState(() => cachedOnboarding?.user ?? storedUser);
  const [onboarding, setOnboarding] = useState(() => cachedOnboarding?.onboarding ?? null);
  const [telegram, setTelegram] = useState(null);
  const [username, setUsername] = useState(() => (cachedOnboarding?.user ?? storedUser)?.username ?? "");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [telegramStatus, setTelegramStatus] = useState("");
  const [telegramError, setTelegramError] = useState("");
  const [calendarBusy, setCalendarBusy] = useState(false);
  const [usernameBusy, setUsernameBusy] = useState(false);
  const [telegramSaveBusy, setTelegramSaveBusy] = useState(false);
  const [telegramLinkBusy, setTelegramLinkBusy] = useState(false);
  const [telegramTestBusy, setTelegramTestBusy] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const calendarInputRef = useRef(null);

  useEffect(() => {
    let active = true;

    async function loadContext() {
      const [contextResult, telegramResult] = await Promise.allSettled([
          fetchOnboardingContext(),
          fetchTelegramSettings(),
      ]);

      if (!active) {
        return;
      }

      if (contextResult.status === "fulfilled") {
        const contextData = contextResult.value;
        setUser(contextData.user);
        setOnboarding(contextData.onboarding);
        setUsername(contextData.user?.username ?? "");
        setError("");
      } else {
        if (!cachedOnboarding && !storedUser) {
          clearStoredToken();
          navigate("/", { replace: true });
          return;
        }
        setError(contextResult.reason?.message || "Using your saved account settings while fresh context loads.");
      }

      if (telegramResult.status === "fulfilled") {
        setTelegram(telegramResult.value);
        setTelegramError("");
      } else {
        setTelegramError(telegramResult.reason?.message || "Unable to load Telegram settings right now.");
      }
    }

    loadContext();
    return () => {
      active = false;
    };
  }, [cachedOnboarding, navigate, storedUser]);

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

  function updateTelegramSetting(field, value) {
    setTelegram((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        settings: {
          ...(current.settings ?? DEFAULT_TELEGRAM_SETTINGS),
          [field]: value,
        },
      };
    });
  }

  async function refreshTelegram(message = "") {
    try {
      const payload = await fetchTelegramSettings();
      setTelegram(payload);
      if (message) {
        setTelegramStatus(message);
      }
      setTelegramError("");
    } catch (refreshError) {
      setTelegramError(refreshError.message);
    }
  }

  async function handleTelegramSettingsSave(event) {
    event.preventDefault();

    try {
      setTelegramSaveBusy(true);
      setTelegramError("");
      setTelegramStatus("");
      const payload = await saveTelegramSettings(telegram?.settings ?? DEFAULT_TELEGRAM_SETTINGS);
      setTelegram(payload);
      setTelegramStatus("Telegram settings saved.");
    } catch (saveError) {
      setTelegramError(saveError.message);
    } finally {
      setTelegramSaveBusy(false);
    }
  }

  async function handleTelegramLinkCode() {
    try {
      setTelegramLinkBusy(true);
      setTelegramError("");
      setTelegramStatus("");
      const payload = await createTelegramLinkCode();
      setTelegram(payload);
      setTelegramStatus("A new linking code is ready. Send it to the bot to connect this chat.");
    } catch (linkError) {
      setTelegramError(linkError.message);
    } finally {
      setTelegramLinkBusy(false);
    }
  }

  async function handleTelegramDisconnect() {
    try {
      setTelegramLinkBusy(true);
      setTelegramError("");
      setTelegramStatus("");
      const payload = await disconnectTelegram();
      setTelegram(payload);
      setTelegramStatus("Telegram has been disconnected.");
    } catch (disconnectError) {
      setTelegramError(disconnectError.message);
    } finally {
      setTelegramLinkBusy(false);
    }
  }

  async function handleTelegramTest() {
    try {
      setTelegramTestBusy(true);
      setTelegramError("");
      setTelegramStatus("");
      await sendTelegramTestMessage();
      setTelegramStatus("Daily digest for today sent to Telegram.");
    } catch (testError) {
      setTelegramError(testError.message);
    } finally {
      setTelegramTestBusy(false);
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
  const telegramSettings = telegram?.settings ?? DEFAULT_TELEGRAM_SETTINGS;
  const pendingLink = telegram?.pendingLink;
  const linkedChat = telegram?.linkedChat;
  const telegramConnectionLabel = telegram
    ? telegram.linked
      ? "Linked"
      : telegram.configured
        ? "Ready to link"
        : "Bot unavailable"
    : "Loading...";
  const dailyDigestLabel =
    telegramSettings.telegramEnabled && telegramSettings.dailyDigestEnabled
      ? `On at ${telegramSettings.dailyDigestTime}`
      : "Off";

  return (
    <main className="simple-shell">
      <PageNav />
      <section className="structured-page settings-page">
        <section className="structured-overview settings-overview" aria-label="Settings overview">
          <article className="structured-overview-item settings-overview-item">
            <p className="summary-label">Username</p>
            <p className="structured-overview-value settings-overview-value">{user.username}</p>
          </article>
          <article className="structured-overview-item settings-overview-item">
            <p className="summary-label">Telegram</p>
            <p className="structured-overview-value settings-overview-value">{telegramConnectionLabel}</p>
          </article>
          <article className="structured-overview-item settings-overview-item">
            <p className="summary-label">Calendar context</p>
            <p className="structured-overview-value settings-overview-value">
              {calendarSource ? "Linked" : "Not linked"}
            </p>
          </article>
          <article className="structured-overview-item settings-overview-item">
            <p className="summary-label">Daily digest</p>
            <p className="structured-overview-value settings-overview-value">{dailyDigestLabel}</p>
          </article>
        </section>

        <section className="structured-section settings-section">
          <div className="structured-section-header settings-section-header">
            <div className="structured-section-copy settings-section-copy">
              <h2 className="structured-section-title settings-section-title">Profile</h2>
              <p className="panel-copy">
                Update the username you use to sign in. This change is saved directly to your
                account record.
              </p>
            </div>
            <div className="structured-meta settings-meta">
              <span>Current username: {user.username}</span>
            </div>
          </div>

          <div className="structured-section-body">
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
          </div>
        </section>

        <section className="structured-section settings-section">
          <div className="structured-section-header settings-section-header">
            <div className="structured-section-copy settings-section-copy">
              <h2 className="structured-section-title settings-section-title">Notifications</h2>
              <p className="panel-copy">
                Connect your Telegram chat for instant priority alerts and a daily plan for what
                to focus on today.
              </p>
            </div>
            <div className="structured-meta settings-meta">
              <span>
                {telegram
                  ? telegram.linked
                    ? "Telegram linked"
                    : "Telegram not linked"
                  : "Loading Telegram"}
              </span>
              <span>
                {telegram
                  ? telegram.configured
                    ? "Bot configured"
                    : "Bot not configured"
                  : "Checking bot status"}
              </span>
            </div>
          </div>

          <div className="structured-section-body">
            {telegram?.configurationError ? (
              <p className="error-text auth-error">{telegram.configurationError}</p>
            ) : null}

            {!telegram ? (
              <p className="panel-copy">Loading your Telegram settings...</p>
            ) : null}

            <div className="structured-subgrid settings-notification-grid">
              <section className="structured-subsection">
                <div className="structured-subsection-header">
                  <h3 className="structured-subsection-title">Connection and linking</h3>
                  <p className="panel-copy">
                    Link the Telegram chat you want to use, then refresh or test delivery here.
                  </p>
                </div>

                <div className="telegram-status-card">
                  <div className="telegram-status-block">
                    <p className="summary-label">Connection</p>
                    {linkedChat ? (
                      <div className="telegram-link-box">
                        <strong>{linkedChat.displayName || linkedChat.username || linkedChat.chatId}</strong>
                        <span>
                          {linkedChat.username ? `@${linkedChat.username}` : "Direct chat"}
                        </span>
                        <span>
                          Linked {linkedChat.linkedAt ? new Date(linkedChat.linkedAt).toLocaleString() : "recently"}
                        </span>
                      </div>
                    ) : (
                      <div className="telegram-link-box">
                        <strong>No linked chat yet</strong>
                        <span>Generate a code, open the bot, and send it there.</span>
                      </div>
                    )}
                  </div>

                  <div className="telegram-status-block">
                    <p className="summary-label">Link code</p>
                    {pendingLink ? (
                      <div className="telegram-link-box">
                        <strong className="telegram-code-pill">{pendingLink.code}</strong>
                        <span>
                          Expires{" "}
                          {pendingLink.expiresAt ? new Date(pendingLink.expiresAt).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          }) : "soon"}
                        </span>
                        <span>Send this code to the Telegram bot from the chat you want to use.</span>
                      </div>
                    ) : (
                      <div className="telegram-link-box">
                        <strong>No active code</strong>
                        <span>Generate one whenever you want to connect a new chat.</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="telegram-instructions">
                  <p className="summary-label">Instructions</p>
                  <ol className="telegram-steps">
                    <li>Generate a temporary linking code here.</li>
                    <li>Open the Telegram bot and send that code from the chat you want to link.</li>
                    <li>Come back here and refresh the status once the bot confirms the connection.</li>
                  </ol>
                  {pendingLink?.botDeepLink ? (
                    <a
                      className="secondary-button telegram-link-button"
                      href={pendingLink.botDeepLink}
                      rel="noreferrer"
                      target="_blank"
                    >
                      Open Telegram bot
                    </a>
                  ) : null}
                </div>

                <div className="manual-task-actions">
                  <button
                    className="auth-button"
                    disabled={telegramLinkBusy || !telegram?.configured}
                    onClick={handleTelegramLinkCode}
                    type="button"
                  >
                    {telegramLinkBusy ? "Preparing..." : pendingLink ? "Generate new code" : "Generate linking code"}
                  </button>
                  <button
                    className="secondary-button"
                    disabled={telegramLinkBusy}
                    onClick={() => refreshTelegram("Telegram status refreshed.")}
                    type="button"
                  >
                    Refresh status
                  </button>
                  {telegram?.linked ? (
                    <button
                      className="secondary-button"
                      disabled={telegramLinkBusy}
                      onClick={handleTelegramDisconnect}
                      type="button"
                    >
                      Disconnect Telegram
                    </button>
                  ) : null}
                  <button
                    className="secondary-button"
                    disabled={telegramTestBusy || !telegram?.linked || !telegram?.configured}
                    onClick={handleTelegramTest}
                    type="button"
                  >
                    {telegramTestBusy ? "Sending digest..." : "Send daily digest for today"}
                  </button>
                </div>
              </section>

              <section className="structured-subsection">
                <div className="structured-subsection-header">
                  <h3 className="structured-subsection-title">Delivery preferences</h3>
                  <p className="panel-copy">
                    Choose which Telegram alerts arrive instantly and when to receive the daily digest.
                  </p>
                </div>

                <form className="calendar-upload-form" onSubmit={handleTelegramSettingsSave}>
                  <div className="telegram-toggle-grid">
                    <label className="option-row">
                      <input
                        checked={telegramSettings.telegramEnabled}
                        onChange={(event) => updateTelegramSetting("telegramEnabled", event.target.checked)}
                        type="checkbox"
                      />
                      <span>
                        <strong>Enable Telegram notifications</strong>
                        <small>Turn Telegram delivery on or off without disconnecting the chat.</small>
                      </span>
                    </label>

                    <label className="option-row">
                      <input
                        checked={telegramSettings.dailyDigestEnabled}
                        disabled={!telegramSettings.telegramEnabled}
                        onChange={(event) => updateTelegramSetting("dailyDigestEnabled", event.target.checked)}
                        type="checkbox"
                      />
                      <span>
                        <strong>Enable daily digest</strong>
                        <small>Receive one daily summary of important work for today.</small>
                      </span>
                    </label>
                  </div>

                  <div className="telegram-tier-grid">
                    <label className="option-row">
                      <input
                        checked={telegramSettings.instantCritical}
                        disabled={!telegramSettings.telegramEnabled}
                        onChange={(event) => updateTelegramSetting("instantCritical", event.target.checked)}
                        type="checkbox"
                      />
                      <span>
                        <strong>Critical alerts</strong>
                        <small>Instant Telegram alerts for critical tasks.</small>
                      </span>
                    </label>

                    <label className="option-row">
                      <input
                        checked={telegramSettings.instantHigh}
                        disabled={!telegramSettings.telegramEnabled}
                        onChange={(event) => updateTelegramSetting("instantHigh", event.target.checked)}
                        type="checkbox"
                      />
                      <span>
                        <strong>High alerts</strong>
                        <small>Instant Telegram alerts for high priority tasks.</small>
                      </span>
                    </label>

                    <label className="option-row">
                      <input
                        checked={telegramSettings.instantMedium}
                        disabled={!telegramSettings.telegramEnabled}
                        onChange={(event) => updateTelegramSetting("instantMedium", event.target.checked)}
                        type="checkbox"
                      />
                      <span>
                        <strong>Medium alerts</strong>
                        <small>Instant Telegram alerts for medium priority tasks.</small>
                      </span>
                    </label>

                    <label className="option-row">
                      <input
                        checked={telegramSettings.instantLow}
                        disabled={!telegramSettings.telegramEnabled}
                        onChange={(event) => updateTelegramSetting("instantLow", event.target.checked)}
                        type="checkbox"
                      />
                      <span>
                        <strong>Low alerts</strong>
                        <small>Instant Telegram alerts for low priority tasks.</small>
                      </span>
                    </label>
                  </div>

                  <label className="field-group telegram-time-field">
                    <span>Daily digest time</span>
                    <input
                      className="auth-input"
                      disabled={!telegramSettings.telegramEnabled || !telegramSettings.dailyDigestEnabled}
                      onChange={(event) => updateTelegramSetting("dailyDigestTime", event.target.value)}
                      type="time"
                      value={telegramSettings.dailyDigestTime}
                    />
                    <p className="field-hint">Times follow the app&apos;s current timezone context.</p>
                  </label>

                  <div className="manual-task-actions">
                    <button className="auth-button" disabled={telegramSaveBusy} type="submit">
                      {telegramSaveBusy ? "Saving..." : "Save Telegram settings"}
                    </button>
                  </div>
                </form>
              </section>
            </div>

            {telegramStatus ? <p className="success-text">{telegramStatus}</p> : null}
            {telegramError ? <p className="error-text auth-error">{telegramError}</p> : null}
          </div>
        </section>

        <section className="structured-section settings-section">
          <div className="structured-section-header settings-section-header">
            <div className="structured-section-copy settings-section-copy">
              <h2 className="structured-section-title settings-section-title">Calendar context</h2>
              <p className="panel-copy">
                Upload one active `.ics` file to give the pipeline timetable context for the next
                21 days.
              </p>
            </div>
            <div className="structured-meta settings-meta">
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

          <div className="structured-section-body">
            <section className="structured-subsection">
              <div className="structured-subsection-header">
                <h3 className="structured-subsection-title">Saved calendar context</h3>
                <p className="panel-copy">
                  Review the timetable information currently affecting prioritization, then replace or remove it here.
                </p>
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
          </div>
        </section>

        <section className="structured-section structured-section-danger settings-section settings-section-danger">
          <div className="structured-section-header settings-section-header">
            <div className="structured-section-copy settings-section-copy">
              <h2 className="structured-section-title settings-section-title">Delete account</h2>
              <p className="panel-copy">
                Permanently remove this account and all related data. This action cannot be undone.
              </p>
            </div>
            <div className="structured-meta settings-meta">
              <span>Permanent action</span>
              <span>Cannot be undone</span>
            </div>
          </div>

          <div className="structured-section-body">
            <div className="manual-task-actions">
              <button
                className="auth-button danger-button"
                onClick={openDeleteDialog}
                type="button"
              >
                Delete account
              </button>
            </div>
          </div>
        </section>

        <div className="structured-feedback settings-feedback">
          {status ? <p className="success-text">{status}</p> : null}
          {error ? <p className="error-text auth-error">{error}</p> : null}
        </div>
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
