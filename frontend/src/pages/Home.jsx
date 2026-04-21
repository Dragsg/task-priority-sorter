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

  return (
    <main className="simple-shell">
      <section className="simple-card">
        <p className="auth-eyebrow">Home</p>
        <h1 className="simple-title">
          {user ? `Hello, ${user.name || user.email}` : "Loading your workspace"}
        </h1>
        <p className="simple-copy">
          {user ? (
            <>
              Logged in as <strong>{user.email}</strong>.
            </>
          ) : (
            "Fetching your account details..."
          )}
        </p>
        <p className="simple-copy">
          Preference:{" "}
          <strong>{user ? user.preferences || "Not set yet" : "Loading..."}</strong>
        </p>

        <div className="home-actions">
          <Link
            className={`auth-button home-link${user ? "" : " disabled-link"}`}
            onClick={(event) => {
              if (!user) {
                event.preventDefault();
              }
            }}
            to="/linking"
          >
            Go to linking page
          </Link>
          <Link
            className={`secondary-button home-link${user ? "" : " disabled-link"}`}
            onClick={(event) => {
              if (!user) {
                event.preventDefault();
              }
            }}
            to="/onboarding"
          >
            Update preferences
          </Link>
          <button
            className="inline-button danger-button"
            disabled={!user}
            onClick={handleLogout}
            type="button"
          >
            Log out
          </button>
        </div>
      </section>
    </main>
  );
}
