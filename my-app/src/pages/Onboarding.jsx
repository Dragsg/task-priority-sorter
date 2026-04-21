import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getCurrentUser, saveOnboardingPreference } from "../lib/api";
import { clearSession, getStoredUser, persistUser } from "../lib/session";
import "../styles/Onboarding.css";

const options = [
    {
        value: "School",
        title: "School",
        description: "Keep assignments, study blocks, and deadlines easy to prioritize.",
    },
    {
        value: "Work",
        title: "Work",
        description: "Balance meetings, deadlines, and deeper project work with less friction.",
    },
    {
        value: "Personal",
        title: "Personal",
        description: "Organize routines, errands, and life admin in one calmer view.",
    },
    {
        value: "Unsure",
        title: "Still figuring it out",
        description: "Start simple now and adjust your workflow later once things click.",
    },
];

export default function Onboarding() {
    const [userData, setUserData] = useState(getStoredUser());
    const [loading, setLoading] = useState(true);
    const [preference, setPreference] = useState("");
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState("");
    const navigate = useNavigate();

    useEffect(() => {
        const loadUser = async () => {
            try {
                const payload = await getCurrentUser();
                setUserData(payload.user);
                setPreference(payload.user.preference ?? "");
                persistUser(payload.user);
            } catch {
                clearSession();
                navigate("/login", { replace: true });
            } finally {
                setLoading(false);
            }
        };

        loadUser();
    }, [navigate]);

    const handleSubmit = async (event) => {
        event.preventDefault();
        setError("");

        if (!preference) {
            setError("Choose the option that fits best for now.");
            return;
        }

        setIsSaving(true);
        try {
            const payload = await saveOnboardingPreference(preference);
            persistUser(payload.user);
            navigate("/home", { replace: true });
        } catch (requestError) {
            setError(requestError.message);
        } finally {
            setIsSaving(false);
        }
    };

    if (loading) {
        return <main className="onboarding-shell">Loading your setup...</main>;
    }

    return (
        <main className="onboarding-shell">
            <section className="onboarding-card">
                <p className="onboarding-kicker">Personalize your workspace</p>
                <h1>{userData?.name || "Welcome"}, what are you planning for most?</h1>
                <p className="onboarding-copy">
                    We use this to tune the emphasis of your dashboard. You can
                    always change it later.
                </p>

                <form className="onboarding-form" onSubmit={handleSubmit}>
                    <div className="onboarding-options">
                        {options.map((option) => (
                            <label
                                key={option.value}
                                className={`onboarding-option ${
                                    preference === option.value ? "selected" : ""
                                }`}
                            >
                                <input
                                    type="radio"
                                    name="preference"
                                    value={option.value}
                                    checked={preference === option.value}
                                    onChange={(event) => setPreference(event.target.value)}
                                />
                                <span className="onboarding-option-title">
                                    {option.title}
                                </span>
                                <span className="onboarding-option-copy">
                                    {option.description}
                                </span>
                            </label>
                        ))}
                    </div>

                    {error ? <p className="onboarding-error">{error}</p> : null}

                    <button
                        className="onboarding-submit"
                        type="submit"
                        disabled={isSaving}
                    >
                        {isSaving ? "Saving..." : "Continue to dashboard"}
                    </button>
                </form>
            </section>
        </main>
    );
}
