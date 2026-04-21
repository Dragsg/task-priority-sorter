import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchCurrentUser, getStoredToken, signIn, signUp } from "../api";

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
        localStorage.removeItem("token");
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
          Sign in first, then we can connect Gmail and Outlook from the linking
          page.
        </p>

        <form className="auth-form" onSubmit={handleSubmit}>
          <input
            className="auth-input"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="Email"
            type="email"
            value={email}
          />
          <input
            className="auth-input"
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Password"
            type="password"
            value={password}
          />
          {isSignUp ? (
            <input
              className="auth-input"
              onChange={(event) => setName(event.target.value)}
              placeholder="What should we call you?"
              type="text"
              value={name}
            />
          ) : null}

          {error ? <p className="error-text auth-error">{error}</p> : null}

          <button className="auth-button" disabled={busy} type="submit">
            {busy ? "Please wait..." : isSignUp ? "Create account" : "Log in"}
          </button>
        </form>

        <p className="auth-switch">
          {isSignUp ? "Already have an account?" : "Don't have an account?"}{" "}
          <button
            className="inline-button"
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
