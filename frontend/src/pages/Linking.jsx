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

  return (
    <main className="app-shell">
      <PageNav />
      <section className="hero">
        <p className="eyebrow">Email Linking</p>
        <h1>Connect Gmail and Outlook inboxes</h1>
        <p className="subtitle">
          Signed in as <code>{user?.email ?? "..."}</code>. Your linking page
          now lives at <code>/linking</code> so the login flow can own the
          default route.
        </p>
      </section>

      <section className="status-card dual-status-card">
        <div>
          <h2>Gmail status</h2>
          <p className="status-copy">
            {gmailLoading
              ? "Checking current Gmail link..."
              : gmailStatus.linked
                ? `Linked to ${gmailStatus.emailAddress}`
                : "No Gmail account linked yet"}
          </p>
        </div>
        <p className="status-pill">{gmailStatus.linked ? "Linked" : "Not linked"}</p>
      </section>

      <section className="status-card dual-status-card">
        <div>
          <h2>Outlook status</h2>
          <p className="status-copy">
            {outlookLoading
              ? "Checking current Outlook link..."
              : outlookStatus.linked
                ? `Linked to ${outlookStatus.emailAddress}`
                : "No Outlook account linked yet"}
          </p>
        </div>
        <p className="status-pill">{outlookStatus.linked ? "Linked" : "Not linked"}</p>
      </section>

      <section className="status-card dual-status-card sync-status-card">
        <div>
          <h2>Automatic task refresh</h2>
          <p className="status-copy">
            Last run: {formatSyncTimestamp(backgroundSyncStatus.last_run_at)}
          </p>
          <p className="status-copy">
            Last completed refresh: {formatSyncTimestamp(backgroundSyncStatus.last_success_at)}
          </p>
          <p className="status-copy">
            Checked {backgroundSyncStatus.linked_users_checked} linked account
            {backgroundSyncStatus.linked_users_checked === 1 ? "" : "s"} across{" "}
            {backgroundSyncStatus.gmail_users_checked} Gmail link
            {backgroundSyncStatus.gmail_users_checked === 1 ? "" : "s"} and{" "}
            {backgroundSyncStatus.outlook_users_checked} Outlook link
            {backgroundSyncStatus.outlook_users_checked === 1 ? "" : "s"} in the latest cycle.
          </p>
          <p className="status-copy">
            Refreshed {backgroundSyncStatus.users_refreshed} account
            {backgroundSyncStatus.users_refreshed === 1 ? "" : "s"}, rebuilt{" "}
            {backgroundSyncStatus.last_total_task_cards} task card
            {backgroundSyncStatus.last_total_task_cards === 1 ? "" : "s"}, and hit{" "}
            {backgroundSyncStatus.users_failed} failure
            {backgroundSyncStatus.users_failed === 1 ? "" : "s"}.
          </p>
        </div>
        <p className="status-pill">
          {backgroundSyncStatus.last_success_at ? "Running" : "Starting"}
        </p>
      </section>

      <section className="tasks-card action-panel gmail-panel">
        <div className="section-heading">
          <div>
            <h2>Gmail</h2>
            <p>Start the Gmail OAuth flow</p>
          </div>
          <button className="primary-button" onClick={startGmailLink} type="button">
            Link Gmail
          </button>
        </div>

        <p className="helper-text">
          After Google sends the user back here, you can load a selected number
          of recent emails and then check for newer emails that arrive after linking.
          The automatic 15-minute job now refreshes the full task pipeline, not just
          the raw email cache.
        </p>

        {gmailFlash ? <p className="success-text">{gmailFlash}</p> : null}
        {gmailError ? <p className="error-text">{gmailError}</p> : null}

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

      <section className="tasks-card action-panel outlook-panel">
        <div className="section-heading">
          <div>
            <h2>Outlook</h2>
            <p>Start the Microsoft OAuth flow</p>
          </div>
          <button
            className="primary-button outlook-button"
            onClick={startOutlookLink}
            type="button"
          >
            Link Outlook
          </button>
        </div>

        <p className="helper-text">
          Microsoft account selection happens on the Microsoft sign-in screen.
          After linking, the backend stores the refresh token in the Outlook
          table and can reuse it on refresh. The backend now reruns email fetch
          plus task prioritization every 15 minutes while it is running.
        </p>

        {outlookFlash ? <p className="success-text">{outlookFlash}</p> : null}
        {outlookError ? <p className="error-text">{outlookError}</p> : null}

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
            className="secondary-button outlook-secondary-button"
            disabled={!outlookStatus.linked || outlookBusyAction === "recent"}
            onClick={handleLoadRecentOutlookEmails}
            type="button"
          >
            {outlookBusyAction === "recent"
              ? "Loading..."
              : `Load last ${outlookRecentLimit} emails`}
          </button>
          <button
            className="secondary-button outlook-secondary-button"
            disabled={!outlookStatus.linked || outlookBusyAction === "new"}
            onClick={handleLoadNewOutlookEmails}
            type="button"
          >
            {outlookBusyAction === "new" ? "Checking..." : "Check new emails"}
          </button>
        </div>
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
    </main>
  );
}
