import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { loginUser, signupUser } from "../lib/api";
import { getToken, persistSession } from "../lib/session";
import "../styles/Login.css";

export default function Login() {
    const [form, setForm] = useState({
        name: "",
        email: "",
        password: "",
    });
    const [isSignUp, setIsSignUp] = useState(true);
    const [isCheckingSession, setIsCheckingSession] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState("");
    const navigate = useNavigate();

    useEffect(() => {
        if (getToken()) {
            navigate("/home", { replace: true });
            return;
        }

        setIsCheckingSession(false);
    }, [navigate]);

    const updateField = (field) => (event) => {
        setForm((current) => ({
            ...current,
            [field]: event.target.value,
        }));
    };

    const toggleMode = () => {
        setIsSignUp((current) => !current);
        setError("");
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        setError("");
        setIsSubmitting(true);

        try {
            const payload = isSignUp
                ? await signupUser(form)
                : await loginUser({
                      email: form.email,
                      password: form.password,
                  });

            persistSession(payload);
            navigate(
                payload.user?.has_completed_onboarding ? "/home" : "/onboarding",
                { replace: true },
            );
        } catch (requestError) {
            setError(requestError.message);
        } finally {
            setIsSubmitting(false);
        }
    };

    if (isCheckingSession) {
        return <main className="auth-shell">Checking your session...</main>;
    }

    return (
        <main className="auth-shell">
            <section className="auth-panel auth-panel-hero">
                <p className="auth-kicker">Task Priority Sorter</p>
                <h1>Make calmer decisions before your task list gets loud.</h1>
                <p className="auth-lead">
                    A fresh flow for signing in, setting your focus, and landing
                    in a dashboard that knows what matters next.
                </p>
                <div className="auth-stat-row">
                    <div>
                        <strong>1 place</strong>
                        <span>to capture, sort, and focus your work</span>
                    </div>
                    <div>
                        <strong>3 steps</strong>
                        <span>from account setup to a tailored dashboard</span>
                    </div>
                </div>
            </section>

            <section className="auth-panel auth-panel-form">
                <div className="auth-form-header">
                    <p className="auth-kicker">{isSignUp ? "Create account" : "Sign in"}</p>
                    <h2>{isSignUp ? "Start with a clean setup." : "Welcome back."}</h2>
                    <p>
                        {isSignUp
                            ? "Create your account, then choose the planning mode that fits you best."
                            : "Sign in to continue to your dashboard and task priorities."}
                    </p>
                </div>

                <form className="auth-form" onSubmit={handleSubmit}>
                    {isSignUp ? (
                        <label className="auth-field">
                            <span>Name</span>
                            <input
                                type="text"
                                value={form.name}
                                onChange={updateField("name")}
                                placeholder="Alex Johnson"
                                autoComplete="name"
                                required
                            />
                        </label>
                    ) : null}

                    <label className="auth-field">
                        <span>Email</span>
                        <input
                            type="email"
                            value={form.email}
                            onChange={updateField("email")}
                            placeholder="you@example.com"
                            autoComplete="email"
                            required
                        />
                    </label>

                    <label className="auth-field">
                        <span>Password</span>
                        <input
                            type="password"
                            value={form.password}
                            onChange={updateField("password")}
                            placeholder="At least 8 characters"
                            autoComplete={isSignUp ? "new-password" : "current-password"}
                            required
                        />
                    </label>

                    {error ? <p className="auth-error">{error}</p> : null}

                    <button className="auth-submit" type="submit" disabled={isSubmitting}>
                        {isSubmitting
                            ? "Working..."
                            : isSignUp
                              ? "Create account"
                              : "Log in"}
                    </button>
                </form>

                <p className="auth-switch">
                    {isSignUp ? "Already have an account?" : "Need an account?"}{" "}
                    <button
                        type="button"
                        className="auth-switch-button"
                        onClick={toggleMode}
                    >
                        {isSignUp ? "Log in" : "Create one"}
                    </button>
                </p>

                <p className="auth-footer">
                    After signup you will personalize your workspace before
                    entering the app. <Link to="/home">Preview home</Link>
                </p>
            </section>
        </main>
    );
}
