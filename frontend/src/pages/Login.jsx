import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  fetchCurrentUser,
  getStoredToken,
  storeUser,
  signIn,
  signUp,
} from "../api";
import {
  grantOnboardingAccess,
  isOnboardingComplete,
  revokeOnboardingAccess,
} from "../onboardingOptions";

const HIGHLIGHTS = [
  "Create an account and get into your workspace quickly.",
  "Answer a few onboarding questions so the app can adapt earlier.",
  "Return to your dashboard without repeating setup steps.",
];

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const trimmedUsername = username.trim();
  const canSubmit = isSignUp
    ? trimmedUsername && password.length >= 8
    : trimmedUsername && password;

  useEffect(() => {
    async function checkExistingSession() {
      const token = getStoredToken();
      if (!token) {
        return;
      }

      try {
        const user = await fetchCurrentUser();
        if (isOnboardingComplete(user)) {
          revokeOnboardingAccess();
          navigate("/home", { replace: true });
          return;
        }

        if (user?.userId) {
          grantOnboardingAccess(user.userId);
        }
        navigate("/onboarding", { replace: true });
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
        ? await signUp({ username, password })
        : await signIn({ username, password });
      const nextUser = payload.user ?? null;

      localStorage.setItem("token", payload.token);
      if (nextUser) {
        storeUser(nextUser);
      }

      if (nextUser && !isOnboardingComplete(nextUser)) {
        if (nextUser.userId) {
          grantOnboardingAccess(nextUser.userId);
        }
        navigate("/onboarding");
      } else {
        revokeOnboardingAccess();
        navigate("/home");
      }
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-layout">
        <div className="brand-panel">
          <p className="auth-eyebrow">Task Priority Sorter</p>
          <h1>{isSignUp ? "A calmer place to sort what matters" : "Welcome back"}</h1>
          <p className="auth-subtitle">
            {isSignUp
              ? "Set up your account, answer a few quick questions, and step into a workspace that feels quieter and more intentional."
              : "Pick up where you left off, review your setup, and move back into your workspace without friction."}
          </p>

          <div className="copy-panel">
            <p className="panel-title">What happens next</p>
            <ul className="feature-list">
              {HIGHLIGHTS.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>

        <section className="auth-card">
          <div className="auth-card-header">
            <p className="auth-section-label">{isSignUp ? "Create account" : "Sign in"}</p>
            <p className="auth-card-copy">
              {isSignUp
                ? "Pick a username and password and you are in."
                : "Use the username and password you signed up with."}
            </p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="field-group">
              <span>Username</span>
              <input
                className="auth-input"
                disabled={busy}
                onChange={(event) => setUsername(event.target.value)}
                placeholder={isSignUp ? "Choose a username" : "Enter your username"}
                type="text"
                value={username}
                autoComplete="username"
                minLength={3}
                maxLength={40}
                required
              />
            </label>
            <label className="field-group">
              <span>Password</span>
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
            </label>
            {isSignUp ? (
              <p className="field-hint">
                Use a username with at least 3 characters and a password with at least 8.
              </p>
            ) : null}

            {error ? <p className="error-text auth-error">{error}</p> : null}

            <button className="auth-button" disabled={busy || !canSubmit} type="submit">
              {busy ? "Please wait..." : isSignUp ? "Create account" : "Continue"}
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
      </section>
    </main>
  );
}
