import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  fetchCurrentUser,
  saveOnboardingPreferences,
} from "../api";
import { PREFERENCE_OPTIONS } from "../preferences";

export default function Onboarding() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [preferences, setPreferences] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    async function loadUser() {
      try {
        const data = await fetchCurrentUser();
        setUser(data);
        if (data.preferences) {
          setPreferences(data.preferences);
        }
      } catch {
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    loadUser();
  }, [navigate]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!preferences) {
      setError("Please choose one option before continuing.");
      return;
    }

    try {
      setBusy(true);
      setError("");
      await saveOnboardingPreferences(preferences);
      navigate("/home");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  if (!user) {
    return <main className="simple-shell">Loading your setup...</main>;
  }

  return (
    <main className="simple-shell">
      <section className="simple-hero">
        <p className="auth-eyebrow">Onboarding</p>
        <h1 className="simple-title">Pick the workspace that fits your day</h1>
        <p className="simple-copy">
          You&apos;re signed in as <strong>{user.email}</strong>. Choose the context
          you want this workspace to support first.
        </p>
        <p className="simple-note">
          Think of this as your starting mode. You can update it later whenever your work changes.
        </p>
      </section>

      <section className="simple-card">
        <form className="option-form" onSubmit={handleSubmit}>
          {PREFERENCE_OPTIONS.map((option) => (
            <label className="option-row" key={option.value}>
              <input
                checked={preferences === option.value}
                name="preferences"
                onChange={() => setPreferences(option.value)}
                type="radio"
              />
              <span>
                <strong>{option.title}</strong>
                <small>{option.description}</small>
              </span>
            </label>
          ))}

          {error ? <p className="error-text auth-error">{error}</p> : null}

          <button className="auth-button" disabled={busy} type="submit">
            {busy ? "Saving..." : "Save and continue"}
          </button>
        </form>
      </section>
    </main>
  );
}
