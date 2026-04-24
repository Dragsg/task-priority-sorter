import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  fetchStatisticsSnapshot,
  getStoredUser,
  getStoredUserId,
  LIVE_REFRESH_INTERVAL_MS,
} from "../api";
import PageNav from "../components/PageNav";

const SECTION_HELP = {
  priorityDistribution:
    "Shows how your current queue is spread across CRITICAL, HIGH, MEDIUM, and LOW priority tiers.",
  actionWindows:
    "Shows when the system thinks each task should be handled, such as NOW or THIS_WEEK.",
  platformMix:
    "Shows which platforms contributed to the tasks in your current queue.",
  nearestDeadlines:
    "The tasks with the smallest remaining deadline window, based on deadline_hours.",
};

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
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadStatistics() {
      try {
        const statistics = await fetchStatisticsSnapshot();
        setUser(statistics.user);
        setSummary(statistics.summary ?? EMPTY_SUMMARY);
        setDistributions(statistics.distributions ?? EMPTY_DISTRIBUTIONS);
        setNearestDeadlines(statistics.nearestDeadlines ?? []);
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
    });
  }, [distributions, nearestDeadlines, summary, user]);

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
      <section className="structured-page" aria-label="Insights">
        <section className="structured-overview workspace-overview" aria-label="Insights overview">
          <article className="structured-overview-item">
            <p className="overview-label">Signed in as</p>
            <p className="overview-value">{user?.username ?? "Loading..."}</p>
          </article>
          <article className="structured-overview-item">
            <p className="overview-label">Queued tasks</p>
            <p className="overview-value">{summary.totalTaskCards}</p>
          </article>
          <article className="structured-overview-item">
            <p className="overview-label">Critical tasks</p>
            <p className="overview-value">{summary.criticalTasks}</p>
          </article>
          <article className="structured-overview-item">
            <p className="overview-label">Due within 24h</p>
            <p className="overview-value">{summary.dueWithin24Hours}</p>
          </article>
        </section>

        <section className="structured-section">
          <div className="structured-section-header">
            <div className="structured-section-copy">
              <h2 className="structured-section-title">Queue breakdown</h2>
              <p className="panel-copy">
                Use this page when you want to understand patterns in the queue, not just pick the
                next task.
              </p>
            </div>
            <div className="structured-meta">
              <span>{nearestDeadlines.length} tracked deadlines</span>
              <span>{summary.highPriorityTasks} high-priority tasks in the current snapshot</span>
            </div>
          </div>

          <div className="structured-section-body">
            {error ? <p className="error-text">{error}</p> : null}

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
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}
