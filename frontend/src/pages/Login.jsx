import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  fetchCurrentUser,
  getStoredToken,
  signIn,
  signUp,
} from "../api";

const HIGHLIGHTS = [
  "Create an account and get into your workspace quickly.",
  "Save a focus preference so the app feels more tailored from the start.",
  "Return to your dashboard without repeating setup steps.",
];

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const trimmedEmail = email.trim();
  const trimmedName = name.trim();
  const canSubmit = isSignUp
    ? trimmedEmail && password.length >= 8 && trimmedName.length >= 2
    : trimmedEmail && password;

  useEffect(() => {
    async function checkExistingSession() {
      const token = getStoredToken();
      if (!token) {
        return;
      }

      try {
        const user = await fetchCurrentUser();
        navigate(user.preferences ? "/home" : "/onboarding", { replace: true });
      } catch {
        clearStoredToken();
      }
    }

    checkExistingSession();
  }, [navigate]);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const payload = isSignUp
        ? await signUp({ email, password, name })
        : await signIn({ email, password });

      localStorage.setItem("token", payload.token);
      navigate(isSignUp || !payload.user.preferences ? "/onboarding" : "/home");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <p className="auth-eyebrow">Task Priority Sorter</p>
        <h1>{isSignUp ? "Create your account" : "Welcome back"}</h1>
        <p className="auth-subtitle">
          {isSignUp
            ? "Get started with a short setup so your dashboard is ready as soon as you sign in."
            : "Sign in to review your saved preference, update your setup, and continue where you left off."}
        </p>

        <div className="copy-panel">
          <p className="panel-title">What happens next</p>
          <ul className="feature-list">
            {HIGHLIGHTS.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <input
            className="auth-input"
            disabled={busy}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            type="email"
            value={email}
            autoComplete="email"
            required
          />
          <input
            className="auth-input"
            disabled={busy}
            onChange={(event) => setPassword(event.target.value)}
            placeholder={isSignUp ? "At least 8 characters" : "Enter your password"}
            type="password"
            value={password}
            autoComplete={isSignUp ? "new-password" : "current-password"}
            minLength={isSignUp ? 8 : undefined}
            required
          />
          {isSignUp ? (
            <input
              className="auth-input"
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
              placeholder="What should we call you?"
              type="text"
              value={name}
              autoComplete="name"
              minLength={2}
              maxLength={80}
              required
            />
          ) : null}

          {isSignUp ? (
            <p className="field-hint">
              Use a name with at least 2 characters and a password with at least 8.
            </p>
          ) : null}

          {error ? <p className="error-text auth-error">{error}</p> : null}

          <button className="auth-button" disabled={busy || !canSubmit} type="submit">
            {busy ? "Please wait..." : isSignUp ? "Create account" : "Log in"}
          </button>
        </form>

        <p className="auth-switch">
          {isSignUp ? "Already have an account?" : "Don't have an account?"}{" "}
          <button
            className="inline-button"
            disabled={busy}
            onClick={() => {
              setError("");
              setIsSignUp((current) => !current);
            }}
            type="button"
          >
            {isSignUp ? "Log in" : "Create one"}
          </button>
        </p>
      </section>
    </main>
  );
}
