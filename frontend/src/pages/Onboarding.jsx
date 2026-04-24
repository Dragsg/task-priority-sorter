import { useEffect, useRef, useState } from "react";
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
import {
  IMPORTANT_TOPIC_OPTIONS,
  PERFORMANCE_TIME_OPTIONS,
  PRIORITISE_BY_OPTIONS,
  isOnboardingComplete,
  normalizeOnboardingAnswer,
  revokeOnboardingAccess,
} from "../onboardingOptions";
import { readOnboardingCache, writeOnboardingCache } from "../onboardingCache";
import CalendarContextSummary from "../components/CalendarContextSummary";
const QUESTION_STEPS = [
  {
    key: "performanceTime",
    title: "When is it easiest for you to get important work done?",
    description:
      "This helps the app understand when you naturally have the most momentum for important tasks.",
    options: PERFORMANCE_TIME_OPTIONS,
  },
  {
    key: "importantTopic",
    title: "Which topics or areas matter most to you right now?",
    description:
      "Pick the area that matters most right now, so the queue can frame your work with the right context.",
    options: IMPORTANT_TOPIC_OPTIONS,
  },
  {
    key: "prioritiseBy",
    title: "When choosing what to surface first, what should matter most?",
    description:
      "Choose the main lens you want the system to use when deciding what should surface first.",
    options: PRIORITISE_BY_OPTIONS,
  },
];

function getStepIndexFromAnswers({ performanceTime, importantTopic, prioritiseBy }) {
  if (!performanceTime) {
    return 0;
  }
  if (!importantTopic) {
    return 1;
  }
  if (!prioritiseBy) {
    return 2;
  }
  return QUESTION_STEPS.length;
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
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [calendarBusy, setCalendarBusy] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const calendarInputRef = useRef(null);

  function syncAnswers(nextUser) {
    const nextPerformanceTime = normalizeOnboardingAnswer(
      PERFORMANCE_TIME_OPTIONS,
      nextUser?.performanceTime
    );
    const nextImportantTopic = normalizeOnboardingAnswer(
      IMPORTANT_TOPIC_OPTIONS,
      nextUser?.importantTopic
    );
    const nextPrioritiseBy = normalizeOnboardingAnswer(
      PRIORITISE_BY_OPTIONS,
      nextUser?.prioritiseBy
    );

    setPerformanceTime(nextPerformanceTime);
    setImportantTopic(nextImportantTopic);
    setPrioritiseBy(nextPrioritiseBy);
    setStepIndex(
      getStepIndexFromAnswers({
        performanceTime: nextPerformanceTime,
        importantTopic: nextImportantTopic,
        prioritiseBy: nextPrioritiseBy,
      })
    );
  }

  useEffect(() => {
    async function loadContext() {
      try {
        const data = await fetchOnboardingContext();
        setUser(data.user);
        setOnboarding(data.onboarding);
        syncAnswers(data.user);
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
      syncAnswers(cachedOnboarding.user);
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

  function handleNextStep() {
    const currentStep = QUESTION_STEPS[stepIndex];
    if (!currentStep) {
      return;
    }

    const answers = {
      performanceTime,
      importantTopic,
      prioritiseBy,
    };
    if (!answers[currentStep.key]) {
      setError("Choose one option before continuing.");
      return;
    }

    setError("");
    setStatus("");
    setStepIndex((current) => Math.min(current + 1, QUESTION_STEPS.length));
  }

  function handlePreviousStep() {
    setError("");
    setStatus("");
    setStepIndex((current) => Math.max(current - 1, 0));
  }

  function handleCalendarPickerOpen() {
    if (calendarBusy) {
      return;
    }
    calendarInputRef.current?.click();
  }

  async function handleCalendarSelection(event) {
    const selectedFile = event.target.files?.[0] ?? null;
    if (!selectedFile) {
      return;
    }

    try {
      setCalendarBusy(true);
      setError("");
      setStatus("");
      const result = await uploadOnboardingCalendar(selectedFile);
      setOnboarding(result.onboarding);
      setStatus("Calendar context updated. You can finish setup now.");
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      event.target.value = "";
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
  const recurringInsightCount = onboarding.recurring_task_notes?.length ?? 0;
  const displayedInsightCount = busyWindowCount > 0
    ? Math.min(recurringInsightCount, busyWindowCount)
    : recurringInsightCount;
  const isCalendarStep = stepIndex === QUESTION_STEPS.length;
  const currentQuestion = QUESTION_STEPS[stepIndex];
  const totalSteps = QUESTION_STEPS.length + 1;
  const answeredQuestionCount = [performanceTime, importantTopic, prioritiseBy].filter(Boolean).length;
  const progressPercent = Math.round((answeredQuestionCount / QUESTION_STEPS.length) * 100);
  const selectedAnswers = {
    performanceTime,
    importantTopic,
    prioritiseBy,
  };

  return (
    <main className="simple-shell">
      <section className="simple-hero">
        <p className="auth-eyebrow">Onboarding</p>
        <p className="summary-label">
          Step {stepIndex + 1} of {totalSteps}
        </p>
        <h1 className="simple-title">
          {isCalendarStep ? "Optional calendar context" : "Help the queue learn your working style"}
        </h1>
        <p className="simple-copy">
          You&apos;re signed in as <strong>{user.username}</strong>.{" "}
          {isCalendarStep
            ? "You can upload a calendar file now, or skip this step and add it later under Account."
            : "We'll ask one question at a time, and the rest of the app will unlock after these answers are saved."}
        </p>
        <p className="simple-note">
          {isCalendarStep
            ? "Calendar uploads are optional. They are used only to extract busy windows and summaries, not to store the raw `.ics` text."
            : "Other tabs stay locked until onboarding is complete."}
        </p>
      </section>

      <section className="simple-card">
        <section className="onboarding-progress-panel" aria-label="Onboarding progress">
          <div className="onboarding-progress-header">
            <p className="summary-label">Progress</p>
            <p className="summary-value">{progressPercent}% complete</p>
          </div>
          <div
            aria-hidden="true"
            className="onboarding-progress-track"
          >
            <span
              className="onboarding-progress-fill"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </section>

        {isCalendarStep ? (
          <form className="option-form" onSubmit={handleSubmit}>
            <div className="summary-grid">
              <article className="summary-card">
                <p className="summary-label">Best work window</p>
                <p className="summary-value">{selectedAnswers.performanceTime}</p>
              </article>
              <article className="summary-card">
                <p className="summary-label">Most important area</p>
                <p className="summary-value">{selectedAnswers.importantTopic}</p>
              </article>
              <article className="summary-card">
                <p className="summary-label">Prioritise by</p>
                <p className="summary-value">{selectedAnswers.prioritiseBy}</p>
              </article>
              <article className="summary-card">
                <p className="summary-label">Calendar status</p>
                <p className="summary-value">{calendarSource ? "Ready to use" : "Not linked yet"}</p>
              </article>
            </div>

            <section className="calendar-panel">
              <div className="calendar-panel-header">
                <div>
                  <p className="summary-label">Optional calendar upload (.ics)</p>
                  <p className="panel-copy">
                    Upload one active `.ics` file to give the pipeline timetable context for the
                    next 21 days. You can also skip this now and add it later in Account.
                  </p>
                </div>
                <div className="summary-value summary-value-stack">
                  <span>{calendarSource ? "Calendar linked" : "No calendar linked"}</span>
                  <span>
                    {calendarSource
                      ? displayedInsightCount > 0
                        ? `${displayedInsightCount} availability insights`
                        : `${busyWindowCount} upcoming busy windows`
                      : "0 availability insights"}
                  </span>
                </div>
              </div>

              <CalendarContextSummary onboarding={onboarding} />

              <div className="calendar-upload-form">
                <input
                  accept=".ics"
                  className="onboarding-calendar-input"
                  onChange={handleCalendarSelection}
                  ref={calendarInputRef}
                  type="file"
                />
                <div className="manual-task-actions">
                  <button
                    className="auth-button"
                    disabled={calendarBusy}
                    onClick={handleCalendarPickerOpen}
                    type="button"
                  >
                    {calendarBusy
                      ? "Uploading..."
                      : calendarSource
                        ? "Replace calendar"
                        : "Upload calendar"}
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
              <button
                className="secondary-button"
                disabled={busy || calendarBusy}
                onClick={handlePreviousStep}
                type="button"
              >
                Back
              </button>
              {!calendarSource ? (
                <button className="secondary-button" disabled={busy || calendarBusy} type="submit">
                  {busy ? "Finishing..." : "Skip for now"}
                </button>
              ) : null}
              {calendarSource ? (
                <button className="auth-button" disabled={busy || calendarBusy} type="submit">
                  {busy ? "Finishing..." : "Finish setup"}
                </button>
              ) : null}
            </div>
          </form>
        ) : (
          <>
            <QuestionGroup
              description={currentQuestion.description}
              name={currentQuestion.key}
              onChange={(nextValue) => {
                setError("");
                setStatus("");
                if (currentQuestion.key === "performanceTime") {
                  setPerformanceTime(nextValue);
                  return;
                }
                if (currentQuestion.key === "importantTopic") {
                  setImportantTopic(nextValue);
                  return;
                }
                setPrioritiseBy(nextValue);
              }}
              options={currentQuestion.options}
              title={currentQuestion.title}
              value={selectedAnswers[currentQuestion.key]}
            />

            <div className="manual-task-actions">
              {stepIndex > 0 ? (
                <button className="secondary-button" onClick={handlePreviousStep} type="button">
                  Back
                </button>
              ) : null}
              <button className="auth-button" onClick={handleNextStep} type="button">
                Continue
              </button>
            </div>
          </>
        )}

        {status ? <p className="success-text">{status}</p> : null}
        {error ? <p className="error-text auth-error">{error}</p> : null}
      </section>
    </main>
  );
}
