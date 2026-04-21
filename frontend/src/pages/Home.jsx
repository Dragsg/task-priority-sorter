import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { clearStoredToken, fetchCurrentUser } from "../api";

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
    return <main className="simple-shell">Loading...</main>;
  }

  return (
    <main className="simple-shell">
      <section className="simple-card">
        <p className="auth-eyebrow">Home</p>
        <h1 className="simple-title">Hello, {user.name || user.email}</h1>
        <p className="simple-copy">
          Logged in as <strong>{user.email}</strong>.
        </p>
        <p className="simple-copy">
          Preference: <strong>{user.preferences || "Not set yet"}</strong>
        </p>

        <div className="home-actions">
          <Link className="auth-button home-link" to="/linking">
            Go to linking page
          </Link>
          <Link className="secondary-button home-link" to="/onboarding">
            Update preferences
          </Link>
          <button className="inline-button danger-button" onClick={handleLogout} type="button">
            Log out
          </button>
        </div>
      </section>
    </main>
  );
}
