import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchBackgroundSyncStatus,
  fetchCurrentUser,
  fetchGmailStatus,
  fetchNewEmails,
  fetchNewOutlookEmails,
  fetchOutlookStatus,
  fetchRecentEmails,
  fetchRecentOutlookEmails,
  getGmailLinkUrl,
  getStoredUser,
  getOutlookLinkUrl,
} from "../api";
import PageNav from "../components/PageNav";

function EmailList({ title, description, emails }) {
  return (
    <section className="emails-card">
      <div className="section-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span className="count-pill">{emails.length}</span>
      </div>

      {emails.length === 0 ? (
        <p className="empty-state">No emails loaded yet.</p>
      ) : (
        <div className="email-list">
          {emails.map((email) => (
            <article className="email-card" key={email.id}>
              <p className="email-meta">{email.from}</p>
              <h3>{email.subject}</h3>
              <p className="email-snippet">{email.snippet || "No preview text."}</p>
              <p className="email-date">{email.date || email.receivedAt || ""}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function StatusPill({ label, tone = "neutral" }) {
  return <span className={`status-pill status-pill-${tone}`}>{label}</span>;
}

function ConnectionCard({
  providerName,
  providerMark,
  description,
  statusText,
  accountLabel,
  connected,
  loading,
  flashMessage,
  errorMessage,
  onConnect,
  onOpenTools,
  canOpenTools,
  connectLabel,
}) {
  return (
    <section className="connection-card">
      <div className="connection-card-top">
        <div className="connection-provider">
          <span className="connection-provider-mark" aria-hidden="true">
            {providerMark}
          </span>
          <div>
            <h2>{providerName}</h2>
            <p>{description}</p>
          </div>
        </div>
        <StatusPill
          label={loading ? "Checking" : connected ? "Connected" : "Not connected"}
          tone={loading ? "neutral" : connected ? "linked" : "idle"}
        />
      </div>

      <p className="connection-status-text">{statusText}</p>

      <div className="connection-account-line">
        <span className="connection-account-label">Account</span>
        <strong>{accountLabel}</strong>
      </div>

      {flashMessage ? <p className="success-text">{flashMessage}</p> : null}
      {errorMessage ? <p className="error-text">{errorMessage}</p> : null}

      <div className="connection-action-row">
        <button
          className="primary-button"
          disabled={!onConnect}
          onClick={onConnect}
          type="button"
        >
          {connectLabel}
        </button>
        <button
          className="secondary-button"
          disabled={!canOpenTools}
          onClick={onOpenTools}
          type="button"
        >
          Open tools
        </button>
      </div>
    </section>
  );
}

const EMAIL_COUNT_OPTIONS = [5, 10, 20, 50, 100];

function formatSyncTimestamp(value) {
  if (!value) {
    return "Not run yet";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }

  return date.toLocaleString();
}

export default function Linking() {
  const navigate = useNavigate();
  const [user, setUser] = useState(() => getStoredUser());
  const [gmailStatus, setGmailStatus] = useState({
    linked: false,
    userId: 1,
    emailAddress: "",
  });
  const [outlookStatus, setOutlookStatus] = useState({
    linked: false,
    userId: 1,
    emailAddress: "",
  });
  const [gmailRecentEmails, setGmailRecentEmails] = useState([]);
  const [gmailNewEmails, setGmailNewEmails] = useState([]);
  const [outlookRecentEmails, setOutlookRecentEmails] = useState([]);
  const [outlookNewEmails, setOutlookNewEmails] = useState([]);
  const [gmailLoading, setGmailLoading] = useState(true);
  const [outlookLoading, setOutlookLoading] = useState(true);
  const [gmailBusyAction, setGmailBusyAction] = useState("");
  const [outlookBusyAction, setOutlookBusyAction] = useState("");
  const [gmailError, setGmailError] = useState("");
  const [outlookError, setOutlookError] = useState("");
  const [gmailFlash, setGmailFlash] = useState("");
  const [outlookFlash, setOutlookFlash] = useState("");
  const [gmailRecentLimit, setGmailRecentLimit] = useState(5);
  const [outlookRecentLimit, setOutlookRecentLimit] = useState(5);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [backgroundSyncStatus, setBackgroundSyncStatus] = useState({
    last_run_at: null,
    last_success_at: null,
    gmail_users_checked: 0,
    outlook_users_checked: 0,
    linked_users_checked: 0,
    users_refreshed: 0,
    users_failed: 0,
    last_total_task_cards: 0,
  });

  useEffect(() => {
    async function loadUser() {
      try {
        const data = await fetchCurrentUser();
        setUser(data);
      } catch {
        navigate("/", { replace: true });
      }
    }

    loadUser();
  }, [navigate]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gmailState = params.get("gmail");
    const outlookState = params.get("outlook");
    const linkedEmail = params.get("email");
    const reason = params.get("reason");

    if (gmailState === "linked") {
      setGmailFlash(
        linkedEmail
          ? `Gmail linked successfully: ${linkedEmail}`
          : "Gmail linked successfully."
      );
      window.history.replaceState({}, "", window.location.pathname);
    } else if (gmailState === "error") {
      setGmailError(`Gmail linking failed: ${reason ?? "unknown_error"}`);
      window.history.replaceState({}, "", window.location.pathname);
    }

    if (outlookState === "linked") {
      setOutlookFlash(
        linkedEmail
          ? `Outlook linked successfully: ${linkedEmail}`
          : "Outlook linked successfully."
      );
      window.history.replaceState({}, "", window.location.pathname);
    } else if (outlookState === "error") {
      setOutlookError(`Outlook linking failed: ${reason ?? "unknown_error"}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    async function loadGmailStatus() {
      try {
        setGmailLoading(true);
        const data = await fetchGmailStatus();
        setGmailStatus(data);
      } catch (loadError) {
        setGmailError(loadError.message);
      } finally {
        setGmailLoading(false);
      }
    }

    loadGmailStatus();
  }, []);

  useEffect(() => {
    async function loadOutlookStatus() {
      try {
        setOutlookLoading(true);
        const data = await fetchOutlookStatus();
        setOutlookStatus(data);
      } catch (loadError) {
        setOutlookError(loadError.message);
      } finally {
        setOutlookLoading(false);
      }
    }

    loadOutlookStatus();
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function loadBackgroundSyncStatus() {
      try {
        const data = await fetchBackgroundSyncStatus();
        if (isMounted) {
          setBackgroundSyncStatus(data);
        }
      } catch {
        // Keep the page quiet if the status check fails.
      }
    }

    loadBackgroundSyncStatus();
    const intervalId = window.setInterval(loadBackgroundSyncStatus, 30000);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  async function handleLoadRecentEmails() {
    try {
      setGmailBusyAction("recent");
      setGmailError("");
      const data = await fetchRecentEmails(gmailRecentLimit);
      setGmailRecentEmails(data.messages ?? []);
      setGmailStatus((current) => ({
        ...current,
        historyId: data.historyId ?? current.historyId,
      }));
    } catch (loadError) {
      setGmailError(loadError.message);
    } finally {
      setGmailBusyAction("");
    }
  }

  async function handleLoadNewEmails() {
    try {
      setGmailBusyAction("new");
      setGmailError("");
      const data = await fetchNewEmails();
      setGmailNewEmails(data.messages ?? []);
      setGmailStatus((current) => ({
        ...current,
        historyId: data.historyId ?? current.historyId,
      }));
    } catch (loadError) {
      setGmailError(loadError.message);
    } finally {
      setGmailBusyAction("");
    }
  }

  async function handleLoadRecentOutlookEmails() {
    try {
      setOutlookBusyAction("recent");
      setOutlookError("");
      const data = await fetchRecentOutlookEmails(outlookRecentLimit);
      setOutlookRecentEmails(data.messages ?? []);
      setOutlookStatus((current) => ({
        ...current,
        lastReceivedAt: data.lastReceivedAt ?? current.lastReceivedAt,
      }));
    } catch (loadError) {
      setOutlookError(loadError.message);
    } finally {
      setOutlookBusyAction("");
    }
  }

  async function handleLoadNewOutlookEmails() {
    try {
      setOutlookBusyAction("new");
      setOutlookError("");
      const data = await fetchNewOutlookEmails();
      setOutlookNewEmails(data.messages ?? []);
      setOutlookStatus((current) => ({
        ...current,
        lastReceivedAt: data.lastReceivedAt ?? current.lastReceivedAt,
      }));
    } catch (loadError) {
      setOutlookError(loadError.message);
    } finally {
      setOutlookBusyAction("");
    }
  }

  function startGmailLink() {
    if (!user) {
      return;
    }

    window.location.href = getGmailLinkUrl(user.userId);
  }

  function startOutlookLink() {
    if (!user) {
      return;
    }

    window.location.href = getOutlookLinkUrl(user.userId);
  }

  const linkedAccountCount = Number(Boolean(gmailStatus.linked)) + Number(Boolean(outlookStatus.linked));
  const totalAccountCount = 2;
  const gmailStatusText = gmailLoading
    ? "Checking whether a Gmail account is already connected."
    : gmailStatus.linked
      ? "Your Gmail inbox is connected and ready for sync."
      : "Connect Gmail to import emails and turn them into task cards.";
  const outlookStatusText = outlookLoading
    ? "Checking whether an Outlook account is already connected."
    : outlookStatus.linked
      ? "Your Outlook inbox is connected and ready for sync."
      : "Connect Outlook to import emails and turn them into task cards.";
  const syncStatusLabel = backgroundSyncStatus.last_success_at ? "Active" : "Waiting";
  const syncHelperCopy = backgroundSyncStatus.last_success_at
    ? `Last successful refresh ${formatSyncTimestamp(backgroundSyncStatus.last_success_at)}.`
    : "Automatic refresh has not completed yet.";

  return (
    <main className="app-shell">
      <PageNav />
      <section className="hero linking-hero">
        <p className="eyebrow">Email Linking</p>
        <h1>Connect your email accounts</h1>
        <p className="subtitle">
          Link Gmail or Outlook so we can fetch emails, detect new messages, and
          build task cards for you.
        </p>
        <section className="linking-summary-card">
          <div>
            <p className="linking-summary-label">Signed in as</p>
            <p className="linking-summary-value">{user?.username ?? "Loading..."}</p>
          </div>
          <div>
            <p className="linking-summary-label">Connected</p>
            <p className="linking-summary-value">
              {linkedAccountCount} of {totalAccountCount} accounts
            </p>
          </div>
          <div>
            <p className="linking-summary-label">Auto refresh</p>
            <div className="linking-summary-inline">
              <StatusPill
                label={syncStatusLabel}
                tone={backgroundSyncStatus.last_success_at ? "live" : "neutral"}
              />
              <p className="linking-summary-copy">{syncHelperCopy}</p>
            </div>
          </div>
        </section>
      </section>

      <section className="connection-grid" aria-label="Available email providers">
        <ConnectionCard
          accountLabel={gmailStatus.emailAddress || "No Gmail account linked"}
          canOpenTools={gmailStatus.linked}
          connectLabel={gmailStatus.linked ? "Reconnect Gmail" : "Connect Gmail"}
          connected={gmailStatus.linked}
          description="Use your Google account to sync Gmail messages into your task list."
          errorMessage={gmailError}
          flashMessage={gmailFlash}
          loading={gmailLoading}
          onConnect={user ? startGmailLink : undefined}
          onOpenTools={() => setShowAdvanced(true)}
          providerMark="G"
          providerName="Gmail"
          statusText={gmailStatusText}
        />

        <ConnectionCard
          accountLabel={outlookStatus.emailAddress || "No Outlook account linked"}
          canOpenTools={outlookStatus.linked}
          connectLabel={outlookStatus.linked ? "Reconnect Outlook" : "Connect Outlook"}
          connected={outlookStatus.linked}
          description="Use your Microsoft account to sync Outlook mail into your task list."
          errorMessage={outlookError}
          flashMessage={outlookFlash}
          loading={outlookLoading}
          onConnect={user ? startOutlookLink : undefined}
          onOpenTools={() => setShowAdvanced(true)}
          providerMark="O"
          providerName="Outlook"
          statusText={outlookStatusText}
        />
      </section>

      <section className="advanced-toggle-card">
        <div>
          <p className="linking-summary-label">Advanced details</p>
          <h2>Sync status and manual email tools</h2>
          <p className="status-copy">
            Open this section if you want to inspect refresh activity, pull recent
            emails manually, or verify new message detection.
          </p>
        </div>
        <button
          className="secondary-button"
          onClick={() => setShowAdvanced((current) => !current)}
          type="button"
        >
          {showAdvanced ? "Hide advanced details" : "Show advanced details"}
        </button>
      </section>

      {showAdvanced ? (
        <section className="advanced-details-stack">
          <section className="status-card sync-status-card">
            <div>
              <div className="advanced-section-heading">
                <div>
                  <p className="linking-summary-label">Automatic refresh</p>
                  <h2>Background sync snapshot</h2>
                </div>
                <StatusPill
                  label={syncStatusLabel}
                  tone={backgroundSyncStatus.last_success_at ? "live" : "neutral"}
                />
              </div>
              <div className="sync-metrics-grid">
                <article className="sync-metric-card">
                  <p className="sync-metric-label">Last run</p>
                  <p className="sync-metric-value">
                    {formatSyncTimestamp(backgroundSyncStatus.last_run_at)}
                  </p>
                </article>
                <article className="sync-metric-card">
                  <p className="sync-metric-label">Last success</p>
                  <p className="sync-metric-value">
                    {formatSyncTimestamp(backgroundSyncStatus.last_success_at)}
                  </p>
                </article>
                <article className="sync-metric-card">
                  <p className="sync-metric-label">Linked accounts checked</p>
                  <p className="sync-metric-value">{backgroundSyncStatus.linked_users_checked}</p>
                </article>
                <article className="sync-metric-card">
                  <p className="sync-metric-label">Accounts refreshed</p>
                  <p className="sync-metric-value">{backgroundSyncStatus.users_refreshed}</p>
                </article>
                <article className="sync-metric-card">
                  <p className="sync-metric-label">Task cards rebuilt</p>
                  <p className="sync-metric-value">{backgroundSyncStatus.last_total_task_cards}</p>
                </article>
                <article className="sync-metric-card">
                  <p className="sync-metric-label">Failures</p>
                  <p className="sync-metric-value">{backgroundSyncStatus.users_failed}</p>
                </article>
              </div>
              <p className="status-copy">
                Latest cycle checked {backgroundSyncStatus.gmail_users_checked} Gmail link
                {backgroundSyncStatus.gmail_users_checked === 1 ? "" : "s"} and{" "}
                {backgroundSyncStatus.outlook_users_checked} Outlook link
                {backgroundSyncStatus.outlook_users_checked === 1 ? "" : "s"}.
              </p>
            </div>
          </section>

          <section className="advanced-tool-grid">
            <section className="tasks-card linking-tool-card">
              <div className="advanced-section-heading">
                <div>
                  <p className="linking-summary-label">Gmail tools</p>
                  <h2>Inspect Gmail sync</h2>
                </div>
                <StatusPill
                  label={gmailStatus.linked ? "Ready" : "Link first"}
                  tone={gmailStatus.linked ? "linked" : "idle"}
                />
              </div>

              <p className="helper-text">
                Load a recent Gmail sample or check for messages that arrived after
                the saved history point.
              </p>

              {!gmailStatus.linked ? (
                <p className="tool-hint">Link Gmail first to use these tools.</p>
              ) : null}

              <div className="selector-row">
                <label className="count-selector-label" htmlFor="gmail-recent-limit">
                  Recent email count
                </label>
                <select
                  className="count-selector"
                  id="gmail-recent-limit"
                  onChange={(event) => setGmailRecentLimit(Number(event.target.value))}
                  value={gmailRecentLimit}
                >
                  {EMAIL_COUNT_OPTIONS.map((count) => (
                    <option key={count} value={count}>
                      {count}
                    </option>
                  ))}
                </select>
              </div>

              <div className="button-row">
                <button
                  className="secondary-button"
                  disabled={!gmailStatus.linked || gmailBusyAction === "recent"}
                  onClick={handleLoadRecentEmails}
                  type="button"
                >
                  {gmailBusyAction === "recent"
                    ? "Loading..."
                    : `Load last ${gmailRecentLimit} emails`}
                </button>
                <button
                  className="secondary-button"
                  disabled={!gmailStatus.linked || gmailBusyAction === "new"}
                  onClick={handleLoadNewEmails}
                  type="button"
                >
                  {gmailBusyAction === "new" ? "Checking..." : "Check new emails"}
                </button>
              </div>
            </section>

            <section className="tasks-card linking-tool-card">
              <div className="advanced-section-heading">
                <div>
                  <p className="linking-summary-label">Outlook tools</p>
                  <h2>Inspect Outlook sync</h2>
                </div>
                <StatusPill
                  label={outlookStatus.linked ? "Ready" : "Link first"}
                  tone={outlookStatus.linked ? "linked" : "idle"}
                />
              </div>

              <p className="helper-text">
                Load a recent Outlook sample or check for messages that arrived
                after the saved cursor.
              </p>

              {!outlookStatus.linked ? (
                <p className="tool-hint">Link Outlook first to use these tools.</p>
              ) : null}

              <div className="selector-row">
                <label className="count-selector-label" htmlFor="outlook-recent-limit">
                  Recent email count
                </label>
                <select
                  className="count-selector"
                  id="outlook-recent-limit"
                  onChange={(event) => setOutlookRecentLimit(Number(event.target.value))}
                  value={outlookRecentLimit}
                >
                  {EMAIL_COUNT_OPTIONS.map((count) => (
                    <option key={count} value={count}>
                      {count}
                    </option>
                  ))}
                </select>
              </div>

              <div className="button-row">
                <button
                  className="secondary-button"
                  disabled={!outlookStatus.linked || outlookBusyAction === "recent"}
                  onClick={handleLoadRecentOutlookEmails}
                  type="button"
                >
                  {outlookBusyAction === "recent"
                    ? "Loading..."
                    : `Load last ${outlookRecentLimit} emails`}
                </button>
                <button
                  className="secondary-button"
                  disabled={!outlookStatus.linked || outlookBusyAction === "new"}
                  onClick={handleLoadNewOutlookEmails}
                  type="button"
                >
                  {outlookBusyAction === "new" ? "Checking..." : "Check new emails"}
                </button>
              </div>
            </section>
          </section>

          <EmailList
            description="These are the latest inbox emails loaded after the account was linked."
            emails={gmailRecentEmails}
            title={`Gmail: Last ${gmailRecentLimit} emails`}
          />

          <EmailList
            description="These are emails Gmail reports as new since the last saved history point."
            emails={gmailNewEmails}
            title="Gmail: New incoming emails"
          />

          <EmailList
            description="These are the latest Outlook inbox emails loaded after the account was linked."
            emails={outlookRecentEmails}
            title={`Outlook: Last ${outlookRecentLimit} emails`}
          />

          <EmailList
            description="These are newer Outlook inbox emails received after the saved cursor."
            emails={outlookNewEmails}
            title="Outlook: New incoming emails"
          />
        </section>
      ) : null}
    </main>
  );
}
