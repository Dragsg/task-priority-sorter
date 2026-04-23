import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  deleteOnboardingCalendar,
  fetchOnboardingContext,
  getStoredUser,
  getStoredUserId,
  saveOnboardingAnswers,
  storeUser,
  uploadOnboardingCalendar,
} from "../api";
import PageNav from "../components/PageNav";
import {
  IMPORTANT_TOPIC_OPTIONS,
  PERFORMANCE_TIME_OPTIONS,
  PRIORITISE_BY_OPTIONS,
  hasOnboardingAccess,
  isOnboardingComplete,
  normalizeOnboardingAnswer,
  revokeOnboardingAccess,
} from "../onboardingOptions";

const ONBOARDING_CACHE_VERSION = 2;

function getOnboardingCacheKey(userId) {
  return `task-priority-onboarding:v${ONBOARDING_CACHE_VERSION}:${userId}`;
}

function readOnboardingCache(userId) {
  if (!userId) {
    return null;
  }

  try {
    const raw = localStorage.getItem(getOnboardingCacheKey(userId));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    return {
      user: parsed.user ?? null,
      onboarding: parsed.onboarding ?? null,
    };
  } catch {
    return null;
  }
}

function writeOnboardingCache(userId, user, onboarding) {
  if (!userId) {
    return;
  }

  try {
    localStorage.setItem(
      getOnboardingCacheKey(userId),
      JSON.stringify({
        cachedAt: new Date().toISOString(),
        user: user ?? null,
        onboarding: onboarding ?? null,
      })
    );
  } catch {
    // Ignore cache write failures and keep the page usable.
  }
}

function formatCalendarTimestamp(value) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function QuestionGroup({ description, name, onChange, options, title, value }) {
  return (
    <section className="onboarding-question-group">
      <div className="calendar-panel-header">
        <div>
          <p className="summary-label">{title}</p>
          <p className="panel-copy">{description}</p>
        </div>
      </div>
      <div className="option-form">
        {options.map((option) => (
          <label className="option-row" key={option}>
            <input
              checked={value === option}
              name={name}
              onChange={() => onChange(option)}
              type="radio"
            />
            <span>
              <strong>{option}</strong>
            </span>
          </label>
        ))}
      </div>
    </section>
  );
}

export default function Onboarding() {
  const navigate = useNavigate();
  const storedUserId = getStoredUserId();
  const storedUser = getStoredUser();
  const [cachedOnboarding] = useState(() => readOnboardingCache(storedUserId));
  const [user, setUser] = useState(() => cachedOnboarding?.user ?? storedUser);
  const [onboarding, setOnboarding] = useState(() => cachedOnboarding?.onboarding ?? null);
  const [performanceTime, setPerformanceTime] = useState("");
  const [importantTopic, setImportantTopic] = useState("");
  const [prioritiseBy, setPrioritiseBy] = useState("");
  const [calendarFile, setCalendarFile] = useState(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [calendarBusy, setCalendarBusy] = useState(false);

  useEffect(() => {
    async function loadContext() {
      try {
        const data = await fetchOnboardingContext();
        if (!hasOnboardingAccess(data.user?.userId)) {
          navigate("/home", { replace: true });
          return;
        }
        setUser(data.user);
        setOnboarding(data.onboarding);
        setPerformanceTime(normalizeOnboardingAnswer(PERFORMANCE_TIME_OPTIONS, data.user?.performanceTime));
        setImportantTopic(normalizeOnboardingAnswer(IMPORTANT_TOPIC_OPTIONS, data.user?.importantTopic));
        setPrioritiseBy(normalizeOnboardingAnswer(PRIORITISE_BY_OPTIONS, data.user?.prioritiseBy));
      } catch (loadError) {
        if (cachedOnboarding) {
          setError(loadError.message || "Using your saved setup while fresh context loads.");
          return;
        }
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    if (cachedOnboarding?.user) {
      setPerformanceTime(normalizeOnboardingAnswer(PERFORMANCE_TIME_OPTIONS, cachedOnboarding.user.performanceTime));
      setImportantTopic(normalizeOnboardingAnswer(IMPORTANT_TOPIC_OPTIONS, cachedOnboarding.user.importantTopic));
      setPrioritiseBy(normalizeOnboardingAnswer(PRIORITISE_BY_OPTIONS, cachedOnboarding.user.prioritiseBy));
    }

    loadContext();
  }, [cachedOnboarding, navigate]);

  useEffect(() => {
    if (!user?.userId || !onboarding) {
      return;
    }
    writeOnboardingCache(user.userId, user, onboarding);
  }, [onboarding, user]);

  useEffect(() => {
    if (user && isOnboardingComplete(user)) {
      revokeOnboardingAccess();
      navigate("/home", { replace: true });
    }
  }, [navigate, user]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!performanceTime || !importantTopic || !prioritiseBy) {
      setError("Answer all three onboarding questions before continuing.");
      return;
    }

    try {
      setBusy(true);
      setError("");
      setStatus("");
      const result = await saveOnboardingAnswers({
        performanceTime,
        importantTopic,
        prioritiseBy,
      });
      const updatedUser = result.user ?? null;
      if (updatedUser) {
        setUser(updatedUser);
        storeUser(updatedUser);
      }
      revokeOnboardingAccess();
      navigate("/home", { replace: true });
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCalendarUpload(event) {
    event.preventDefault();
    if (!calendarFile) {
      setError("Choose a .ics file to upload.");
      return;
    }

    try {
      setCalendarBusy(true);
      setError("");
      setStatus("");
      const result = await uploadOnboardingCalendar(calendarFile);
      setOnboarding(result.onboarding);
      setCalendarFile(null);
      setStatus("Calendar context updated.");
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setCalendarBusy(false);
    }
  }

  async function handleCalendarRemove() {
    try {
      setCalendarBusy(true);
      setError("");
      setStatus("");
      const result = await deleteOnboardingCalendar();
      setOnboarding(result.onboarding);
      setStatus("Calendar context removed.");
    } catch (removeError) {
      setError(removeError.message);
    } finally {
      setCalendarBusy(false);
    }
  }

  if (!user || !onboarding) {
    return <main className="simple-shell">Loading your setup...</main>;
  }

  const calendarSource = onboarding.calendar_source;
  const busyWindowCount = onboarding.busy_windows?.length ?? 0;

  return (
    <main className="simple-shell">
      <PageNav />
      <section className="simple-hero">
        <p className="auth-eyebrow">Onboarding</p>
        <h1 className="simple-title">Help the queue learn your working style</h1>
        <p className="simple-copy">
          You&apos;re signed in as <strong>{user.username}</strong>. Answer three quick questions,
          then optionally add a calendar file for timing context.
        </p>
        <p className="simple-note">
          Calendar uploads are optional. They are used only to extract busy windows and summaries,
          not to store the raw `.ics` text.
        </p>
      </section>

      <section className="simple-card">
        <form className="option-form" onSubmit={handleSubmit}>
          <QuestionGroup
            description="This helps the app understand when you naturally have the most momentum for important tasks."
            name="performanceTime"
            onChange={setPerformanceTime}
            options={PERFORMANCE_TIME_OPTIONS}
            title="When is it easiest for you to get important work done?"
            value={performanceTime}
          />
          <QuestionGroup
            description="Pick the area that matters most right now, so the queue can frame your work with the right context."
            name="importantTopic"
            onChange={setImportantTopic}
            options={IMPORTANT_TOPIC_OPTIONS}
            title="Which topics or areas matter most to you right now?"
            value={importantTopic}
          />
          <QuestionGroup
            description="Choose the main lens you want the system to use when deciding what should surface first."
            name="prioritiseBy"
            onChange={setPrioritiseBy}
            options={PRIORITISE_BY_OPTIONS}
            title="When choosing what to surface first, what should matter most?"
            value={prioritiseBy}
          />

          <section className="calendar-panel">
            <div className="calendar-panel-header">
              <div>
                <p className="summary-label">Optional calendar upload (.ics)</p>
                <p className="panel-copy">
                  Upload one active `.ics` file to give the pipeline timetable context for the next
                  21 days.
                </p>
              </div>
              <div className="summary-value summary-value-stack">
                <span>{calendarSource ? "Calendar linked" : "No calendar linked"}</span>
                <span>{busyWindowCount} busy windows stored</span>
              </div>
            </div>

            {calendarSource ? (
              <div className="calendar-summary">
                <p className="task-source-line">
                  <span>File:</span> {calendarSource.filename}
                </p>
                <p className="task-source-line">
                  <span>Uploaded:</span> {formatCalendarTimestamp(calendarSource.uploaded_at)}
                </p>
                <p className="task-source-line">
                  <span>Timezone:</span>{" "}
                  {calendarSource.calendar_timezone || onboarding.timezone || "Asia/Singapore"}
                </p>
                {onboarding.timetable_summary ? (
                  <p className="task-source-line task-source-preview">
                    <span>Summary:</span> {onboarding.timetable_summary}
                  </p>
                ) : null}
              </div>
            ) : null}

            <div className="calendar-upload-form">
              <label className="field-group">
                <span>Calendar file</span>
                <input
                  accept=".ics"
                  className="auth-input auth-file-input"
                  onChange={(event) => setCalendarFile(event.target.files?.[0] ?? null)}
                  type="file"
                />
              </label>
              <div className="manual-task-actions">
                <button
                  className="auth-button"
                  disabled={calendarBusy}
                  onClick={handleCalendarUpload}
                  type="button"
                >
                  {calendarBusy ? "Uploading..." : calendarSource ? "Replace calendar" : "Upload calendar"}
                </button>
                {calendarSource ? (
                  <button
                    className="secondary-button"
                    disabled={calendarBusy}
                    onClick={handleCalendarRemove}
                    type="button"
                  >
                    Remove calendar
                  </button>
                ) : null}
              </div>
            </div>
          </section>

          <div className="manual-task-actions">
            <button className="auth-button" disabled={busy} type="submit">
              {busy ? "Saving..." : "Finish setup"}
            </button>
          </div>
        </form>

        {status ? <p className="success-text">{status}</p> : null}
        {error ? <p className="error-text auth-error">{error}</p> : null}
      </section>
    </main>
  );
}
