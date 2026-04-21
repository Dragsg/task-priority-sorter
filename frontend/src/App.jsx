import { useEffect, useState } from "react";
import {
  fetchGmailStatus,
  fetchNewEmails,
  fetchRecentEmails,
  getGmailLinkUrl,
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
  const [status, setStatus] = useState({
    linked: false,
    userId: 1,
    emailAddress: "",
  });
  const [recentEmails, setRecentEmails] = useState([]);
  const [newEmails, setNewEmails] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gmailState = params.get("gmail");
    const linkedEmail = params.get("email");
    const reason = params.get("reason");

    if (gmailState === "linked") {
      setFlash(
        linkedEmail
          ? `Gmail linked successfully: ${linkedEmail}`
          : "Gmail linked successfully."
      );
      window.history.replaceState({}, "", window.location.pathname);
    } else if (gmailState === "error") {
      setError(`Gmail linking failed: ${reason ?? "unknown_error"}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    async function loadStatus() {
      try {
        setLoading(true);
        const data = await fetchGmailStatus();
        setStatus(data);
      } catch (loadError) {
        setError(loadError.message);
      } finally {
        setLoading(false);
      }
    }

    loadStatus();
  }, []);

  async function handleLoadRecentEmails() {
    try {
      setBusyAction("recent");
      setError("");
      const data = await fetchRecentEmails();
      setRecentEmails(data.messages ?? []);
      setStatus((current) => ({
        ...current,
        historyId: data.historyId ?? current.historyId,
      }));
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setBusyAction("");
    }
  }

  async function handleLoadNewEmails() {
    try {
      setBusyAction("new");
      setError("");
      const data = await fetchNewEmails();
      setNewEmails(data.messages ?? []);
      setStatus((current) => ({
        ...current,
        historyId: data.historyId ?? current.historyId,
      }));
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setBusyAction("");
    }
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Gmail Linking</p>
        <h1>Connect a Gmail inbox</h1>
        <p className="subtitle">
          This page is using placeholder <code>user_id = 1</code> until your
          real login flow is ready. When the user clicks the button, Google will
          show its own account picker so they can choose which Gmail address to
          link.
        </p>
      </section>

      <section className="status-card">
        <div>
          <h2>Link status</h2>
          <p className="status-copy">
            {loading
              ? "Checking current Gmail link..."
              : status.linked
                ? `Linked to ${status.emailAddress}`
                : "No Gmail account linked yet"}
          </p>
        </div>
        <p className="status-pill">{status.linked ? "Linked" : "Not linked"}</p>
      </section>

      <section className="tasks-card action-panel">
        <div className="section-heading">
          <div>
            <h2>Step 1</h2>
            <p>Start the Gmail OAuth flow</p>
          </div>
          <a className="primary-button" href={getGmailLinkUrl()}>
            Link email
          </a>
        </div>

        <p className="helper-text">
          After Google sends the user back here, you can load the most recent 5
          emails and then check for newer emails that arrive after linking.
        </p>

        {flash ? <p className="success-text">{flash}</p> : null}
        {error ? <p className="error-text">{error}</p> : null}

        <div className="button-row">
          <button
            className="secondary-button"
            disabled={!status.linked || busyAction === "recent"}
            onClick={handleLoadRecentEmails}
            type="button"
          >
            {busyAction === "recent" ? "Loading..." : "Load last 5 emails"}
          </button>
          <button
            className="secondary-button"
            disabled={!status.linked || busyAction === "new"}
            onClick={handleLoadNewEmails}
            type="button"
          >
            {busyAction === "new" ? "Checking..." : "Check new emails"}
          </button>
        </div>
      </section>

      <EmailList
        description="These are the latest inbox emails loaded after the account was linked."
        emails={recentEmails}
        title="Last 5 emails"
      />

      <EmailList
        description="These are emails Gmail reports as new since the last saved history point."
        emails={newEmails}
        title="New incoming emails"
      />
    </main>
  );
}
