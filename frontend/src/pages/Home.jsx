import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { clearStoredToken, fetchCurrentUser } from "../api";
import { getPreferenceLabel } from "../preferences";

export default function Home() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);

  useEffect(() => {
    async function loadUser() {
      try {
        const data = await fetchCurrentUser();
        setUser(data);
      } catch {
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    loadUser();
  }, [navigate]);

  function handleLogout() {
    clearStoredToken();
    navigate("/", { replace: true });
  }

  if (!user) {
    return <main className="simple-shell">Loading your dashboard...</main>;
  }

  return (
    <main className="simple-shell">
      <section className="simple-card">
        <p className="auth-eyebrow">Home</p>
        <h1 className="simple-title">Hello, {user.name || user.email}</h1>
        <p className="simple-copy">
          Your workspace is ready. Review your setup, adjust your preference,
          or continue into the rest of the app.
        </p>

        <div className="summary-grid">
          <article className="summary-card">
            <p className="summary-label">Signed in as</p>
            <p className="summary-value">{user.email}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Current focus</p>
            <p className="summary-value">{getPreferenceLabel(user.preferences)}</p>
          </article>
        </div>

        <div className="home-actions">
          <Link className="auth-button home-link" to="/linking">
            Open workspace
          </Link>
          <Link className="secondary-button home-link" to="/onboarding">
            Update preference
          </Link>
          <button className="inline-button danger-button" onClick={handleLogout} type="button">
            Log out
          </button>
        </div>
      </section>
    </main>
  );
}
