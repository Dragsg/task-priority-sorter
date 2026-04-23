import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  fetchStatisticsSnapshot,
  getStoredUser,
  getStoredUserId,
  LIVE_REFRESH_INTERVAL_MS,
} from "../api";
import PageNav from "../components/PageNav";
import { IMPORTANT_TOPIC_OPTIONS, getOnboardingAnswerLabel } from "../onboardingOptions";

const SUMMARY_CARD_HELP = {
  signedIn: "The account whose task queue and profile are being summarized here.",
  focus: "The topic area you said matters most right now, which helps anchor the queue's context.",
  totalTasks: "The number of prioritized tasks currently returned in your dashboard queue.",
  averageConfidence:
    "The average confidence across all queued tasks. Higher means the queue is being ranked with more certainty overall.",
  criticalTasks: "Tasks currently marked as CRITICAL priority.",
  highTasks: "Tasks currently marked as HIGH priority.",
  dueSoon: "Tasks with a tracked deadline within the next 24 hours.",
  profileConfidence:
    "The confidence score for your overall learned prioritization profile, separate from any single task.",
};

const SECTION_HELP = {
  priorityDistribution:
    "Shows how your current queue is spread across CRITICAL, HIGH, MEDIUM, and LOW priority tiers.",
  actionWindows:
    "Shows when the system thinks each task should be handled, such as NOW or THIS_WEEK.",
  platformMix:
    "Shows which platforms contributed to the tasks in your current queue.",
  nearestDeadlines:
    "The tasks with the smallest remaining deadline window, based on deadline_hours.",
  strongestSignals:
    "The tasks with the highest individual confidence scores right now.",
};

function formatPercent(value) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function formatDeadline(hours) {
  if (hours == null) {
    return "No deadline";
  }
  if (hours < 1) {
    return "Under 1 hour";
  }
  if (hours < 24) {
    return `${Math.round(hours)} hours`;
  }

  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"}`;
}

function DistributionCard({ description, emptyLabel, rows, title }) {
  const maxCount = rows[0]?.count ?? 0;

  return (
    <article className="stats-card">
      <div className="tasks-heading">
        <div>
          <p className="panel-title">{title}</p>
          <p className="stats-help-copy">{description}</p>
        </div>
      </div>
      {rows.length ? (
        <div className="stats-list">
          {rows.map((row) => (
            <div className="stats-row" key={row.label}>
              <div className="stats-row-top">
                <span>{row.label}</span>
                <strong>{row.count}</strong>
              </div>
              <div className="stats-bar-track">
                <div
                  className="stats-bar-fill"
                  style={{
                    width: `${maxCount ? (row.count / maxCount) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="panel-copy">{emptyLabel}</p>
      )}
    </article>
  );
}

const EMPTY_SUMMARY = {
  totalTaskCards: 0,
  criticalTasks: 0,
  highPriorityTasks: 0,
  dueWithin24Hours: 0,
  averageConfidence: 0,
  profileConfidence: 0,
};

const EMPTY_DISTRIBUTIONS = {
  priorityTiers: [],
  actionWindows: [],
  platformMix: [],
};
const STATISTICS_CACHE_VERSION = 1;

function getStatisticsCacheKey(userId) {
  return `task-priority-statistics:v${STATISTICS_CACHE_VERSION}:${userId}`;
}

function readStatisticsCache(userId) {
  if (!userId) {
    return null;
  }

  try {
    const raw = localStorage.getItem(getStatisticsCacheKey(userId));
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw);
    return {
      user: parsed.user ?? null,
      summary: parsed.summary ?? EMPTY_SUMMARY,
      distributions: parsed.distributions ?? EMPTY_DISTRIBUTIONS,
      nearestDeadlines: Array.isArray(parsed.nearestDeadlines) ? parsed.nearestDeadlines : [],
      strongestSignals: Array.isArray(parsed.strongestSignals) ? parsed.strongestSignals : [],
    };
  } catch {
    return null;
  }
}

function writeStatisticsCache(userId, payload) {
  if (!userId) {
    return;
  }

  try {
    localStorage.setItem(
      getStatisticsCacheKey(userId),
      JSON.stringify({
        cachedAt: new Date().toISOString(),
        user: payload.user ?? null,
        summary: payload.summary ?? EMPTY_SUMMARY,
        distributions: payload.distributions ?? EMPTY_DISTRIBUTIONS,
        nearestDeadlines: payload.nearestDeadlines ?? [],
        strongestSignals: payload.strongestSignals ?? [],
      })
    );
  } catch {
    // Ignore cache write failures and keep the page usable.
  }
}

function getTaskKey(task) {
  return task.canonical_task_id || task.task_id || task.created_at || task.task_title;
}

function getTaskTierClassName(priorityTier) {
  const tier = String(priorityTier || "low").toLowerCase();
  return `task-tier task-tier-${tier}`;
}

export default function Statistics() {
  const navigate = useNavigate();
  const cachedUserId = getStoredUserId();
  const cachedStatistics = readStatisticsCache(cachedUserId);
  const [user, setUser] = useState(() => cachedStatistics?.user ?? getStoredUser());
  const [summary, setSummary] = useState(() => cachedStatistics?.summary ?? EMPTY_SUMMARY);
  const [distributions, setDistributions] = useState(
    () => cachedStatistics?.distributions ?? EMPTY_DISTRIBUTIONS
  );
  const [nearestDeadlines, setNearestDeadlines] = useState(
    () => cachedStatistics?.nearestDeadlines ?? []
  );
  const [strongestSignals, setStrongestSignals] = useState(
    () => cachedStatistics?.strongestSignals ?? []
  );
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadStatistics() {
      try {
        const statistics = await fetchStatisticsSnapshot();
        setUser(statistics.user);
        setSummary(statistics.summary ?? EMPTY_SUMMARY);
        setDistributions(statistics.distributions ?? EMPTY_DISTRIBUTIONS);
        setNearestDeadlines(statistics.nearestDeadlines ?? []);
        setStrongestSignals(statistics.strongestSignals ?? []);
        setError("");
      } catch {
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    loadStatistics();
  }, [navigate]);

  useEffect(() => {
    if (!user?.userId) {
      return;
    }

    writeStatisticsCache(user.userId, {
      user,
      summary,
      distributions,
      nearestDeadlines,
      strongestSignals,
    });
  }, [distributions, nearestDeadlines, strongestSignals, summary, user]);

  useEffect(() => {
    let isCancelled = false;
    let refreshInFlight = false;

    async function refreshStatisticsQuietly() {
      if (document.hidden || refreshInFlight) {
        return;
      }

      refreshInFlight = true;
      try {
        const statistics = await fetchStatisticsSnapshot();
        if (isCancelled) {
          return;
        }
        setUser(statistics.user);
        setSummary(statistics.summary ?? EMPTY_SUMMARY);
        setDistributions(statistics.distributions ?? EMPTY_DISTRIBUTIONS);
        setNearestDeadlines(statistics.nearestDeadlines ?? []);
        setStrongestSignals(statistics.strongestSignals ?? []);
      } catch {
        // Keep the latest rendered snapshot if the periodic refresh misses a cycle.
      } finally {
        refreshInFlight = false;
      }
    }

    const intervalId = window.setInterval(refreshStatisticsQuietly, LIVE_REFRESH_INTERVAL_MS);

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  return (
    <main className="simple-shell">
      <PageNav />
      <section className="simple-hero">
        <p className="auth-eyebrow">Statistics</p>
        <h1 className="simple-title">See the shape of your task load</h1>
        <p className="simple-copy">
          A backend-backed overview of the current user's task cards, including urgency,
          confidence, deadlines, and where the work is coming from.
        </p>
      </section>

      <section className="simple-card">
        <div className="summary-grid summary-grid-wide">
          <article className="summary-card">
            <p className="summary-label">Signed in as</p>
            <p className="summary-value">{user?.username ?? "Refreshing your account..."}</p>
            <p className="stats-help-copy">{SUMMARY_CARD_HELP.signedIn}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Important topic</p>
            <p className="summary-value">
              {getOnboardingAnswerLabel(IMPORTANT_TOPIC_OPTIONS, user?.importantTopic)}
            </p>
            <p className="stats-help-copy">{SUMMARY_CARD_HELP.focus}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Total queued tasks</p>
            <p className="summary-value">{summary.totalTaskCards}</p>
            <p className="stats-help-copy">{SUMMARY_CARD_HELP.totalTasks}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Average confidence</p>
            <p className="summary-value">{formatPercent(summary.averageConfidence)}</p>
            <p className="stats-help-copy">{SUMMARY_CARD_HELP.averageConfidence}</p>
          </article>
        </div>

        <div className="summary-grid summary-grid-wide stats-top-grid">
          <article className="summary-card">
            <p className="summary-label">Critical tasks</p>
            <p className="summary-value">{summary.criticalTasks}</p>
            <p className="stats-help-copy">{SUMMARY_CARD_HELP.criticalTasks}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">High priority tasks</p>
            <p className="summary-value">{summary.highPriorityTasks}</p>
            <p className="stats-help-copy">{SUMMARY_CARD_HELP.highTasks}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Due within 24h</p>
            <p className="summary-value">{summary.dueWithin24Hours}</p>
            <p className="stats-help-copy">{SUMMARY_CARD_HELP.dueSoon}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Profile confidence</p>
            <p className="summary-value">{formatPercent(summary.profileConfidence)}</p>
            <p className="stats-help-copy">{SUMMARY_CARD_HELP.profileConfidence}</p>
          </article>
        </div>

        <div className="tracker-actions">
          <Link className="secondary-button home-link" to="/home">
            Back to dashboard
          </Link>
          <Link className="secondary-button home-link" to="/linking">
            View linked accounts
          </Link>
        </div>

        {error ? <p className="error-text">{error}</p> : null}

        <section className="tasks-section">
          <div className="stats-grid">
            <DistributionCard
              description={SECTION_HELP.priorityDistribution}
              emptyLabel="No tasks yet, so there is no priority distribution to show."
              rows={distributions.priorityTiers ?? []}
              title="Priority distribution"
            />
            <DistributionCard
              description={SECTION_HELP.actionWindows}
              emptyLabel="No task windows yet, so there is nothing to compare."
              rows={distributions.actionWindows ?? []}
              title="Action windows"
            />
            <DistributionCard
              description={SECTION_HELP.platformMix}
              emptyLabel="No linked-task platform data yet."
              rows={distributions.platformMix ?? []}
              title="Platform mix"
            />

            <article className="stats-card">
              <div className="tasks-heading">
                <div>
                  <p className="panel-title">Nearest deadlines</p>
                  <p className="stats-help-copy">{SECTION_HELP.nearestDeadlines}</p>
                </div>
              </div>
              {nearestDeadlines.length ? (
                <div className="stats-callout-list">
                  {nearestDeadlines.map((task) => (
                    <div className="stats-callout" key={getTaskKey(task)}>
                      <div>
                        <p className="stats-callout-title">{task.task_title}</p>
                        <p className="stats-callout-copy">{formatDeadline(task.deadline_hours)}</p>
                      </div>
                      <span className={getTaskTierClassName(task.priority_tier)}>
                        {task.priority_tier || "LOW"}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="panel-copy">None of the current tasks have a tracked deadline.</p>
              )}
            </article>

            <article className="stats-card stats-card-wide">
              <div className="tasks-heading">
                <div>
                  <p className="panel-title">Strongest signals in the queue</p>
                  <p className="stats-help-copy">{SECTION_HELP.strongestSignals}</p>
                </div>
              </div>
              {strongestSignals.length ? (
                <div className="stats-signal-list">
                  {strongestSignals.map((task) => (
                    <article className="tracker-task-card" key={getTaskKey(task)}>
                      <div className="tracker-task-top">
                        <span className={getTaskTierClassName(task.priority_tier)}>
                          {task.priority_tier || "LOW"}
                        </span>
                        <span className="task-window">{formatPercent(task.confidence ?? 0)}</span>
                      </div>
                      <h2 className="tracker-task-title">{task.task_title}</h2>
                      <p className="tracker-task-date">
                        {task.action_window || "No action window"} | {formatDeadline(task.deadline_hours)}
                      </p>
                      <p className="tracker-task-notes">
                        {task.rationale || "No rationale available for this task yet."}
                      </p>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="task-card task-card-empty">
                  <p className="summary-value">No task statistics yet.</p>
                  <p className="panel-copy">
                    Once tasks exist in the dashboard, this page will turn them into a clearer overview.
                  </p>
                </div>
              )}
            </article>
          </div>
        </section>
      </section>
    </main>
  );
}
