import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchCurrentUser, saveOnboardingPreferences } from "../api";

const OPTIONS = ["School", "Work", "Personal", "Unsure"];

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

  return (
    <main className="simple-shell">
      <section className="simple-card">
        <p className="auth-eyebrow">Onboarding</p>
        <h1 className="simple-title">
          {user
            ? `${user.email}, before you begin, let us personalise your experience`
            : "Before you begin, let us personalise your experience"}
        </h1>
        <p className="simple-copy">
          {user ? "What do you plan to use this tool for?" : "Loading your account details..."}
        </p>

        <form className="option-form" onSubmit={handleSubmit}>
          {OPTIONS.map((option) => (
            <label className="option-row" key={option}>
              <input
                checked={preferences === option}
                disabled={!user}
                name="preferences"
                onChange={() => setPreferences(option)}
                type="radio"
              />
              <span>{option}</span>
            </label>
          ))}

          {error ? <p className="error-text auth-error">{error}</p> : null}

          <button className="auth-button" disabled={busy || !user} type="submit">
            {busy ? "Saving..." : "Continue"}
          </button>
        </form>
      </section>
    </main>
  );
}
