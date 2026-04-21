import { useEffect, useState } from "react";
import {
  fetchGmailStatus,
  fetchNewEmails,
  fetchRecentEmails,
  fetchNewOutlookEmails,
  fetchOutlookStatus,
  fetchRecentOutlookEmails,
  getGmailLinkUrl,
  getOutlookLinkUrl,
} from "./api";

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

export default function App() {
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

  async function handleLoadRecentEmails() {
    try {
      setGmailBusyAction("recent");
      setGmailError("");
      const data = await fetchRecentEmails();
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
      const data = await fetchRecentOutlookEmails();
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

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Email Linking</p>
        <h1>Connect Gmail and Outlook inboxes</h1>
        <p className="subtitle">
          This page is using placeholder <code>user_id = 1</code> until your
          real login flow is ready. The page now keeps Gmail and Outlook in the
          same place so the user can link either provider and reuse the saved
          refresh token later.
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

      <section className="tasks-card action-panel gmail-panel">
        <div className="section-heading">
          <div>
            <h2>Gmail</h2>
            <p>Start the Gmail OAuth flow</p>
          </div>
          <a className="primary-button" href={getGmailLinkUrl()}>
            Link Gmail
          </a>
        </div>

        <p className="helper-text">
          After Google sends the user back here, you can load the most recent 5
          emails and then check for newer emails that arrive after linking.
        </p>

        {gmailFlash ? <p className="success-text">{gmailFlash}</p> : null}
        {gmailError ? <p className="error-text">{gmailError}</p> : null}

        <div className="button-row">
          <button
            className="secondary-button"
            disabled={!gmailStatus.linked || gmailBusyAction === "recent"}
            onClick={handleLoadRecentEmails}
            type="button"
          >
            {gmailBusyAction === "recent" ? "Loading..." : "Load last 5 emails"}
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
          <a className="primary-button outlook-button" href={getOutlookLinkUrl()}>
            Link Outlook
          </a>
        </div>

        <p className="helper-text">
          Microsoft account selection happens on the Microsoft sign-in screen.
          After linking, the backend stores the refresh token in the new
          Outlook table and can reuse it on refresh.
        </p>

        {outlookFlash ? <p className="success-text">{outlookFlash}</p> : null}
        {outlookError ? <p className="error-text">{outlookError}</p> : null}

        <div className="button-row">
          <button
            className="secondary-button outlook-secondary-button"
            disabled={!outlookStatus.linked || outlookBusyAction === "recent"}
            onClick={handleLoadRecentOutlookEmails}
            type="button"
          >
            {outlookBusyAction === "recent" ? "Loading..." : "Load last 5 emails"}
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
        title="Gmail: Last 5 emails"
      />

      <EmailList
        description="These are emails Gmail reports as new since the last saved history point."
        emails={gmailNewEmails}
        title="Gmail: New incoming emails"
      />

      <EmailList
        description="These are the latest Outlook inbox emails loaded after the account was linked."
        emails={outlookRecentEmails}
        title="Outlook: Last 5 emails"
      />

      <EmailList
        description="These are newer Outlook inbox emails received after the saved cursor."
        emails={outlookNewEmails}
        title="Outlook: New incoming emails"
      />
    </main>
  );
}
