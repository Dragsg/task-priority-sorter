import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  createManualTask,
  fetchDashboardBootstrap,
  fetchPipelineProfile,
  fetchPrioritizedTasks,
  getStoredUserId,
  removePrioritizedTask,
  submitTaskFeedback,
  syncPrioritizedTasks,
} from "../api";
import PageNav from "../components/PageNav";
import { getPreferenceLabel } from "../preferences";

const TASK_TYPE_OPTIONS = [
  { value: "submission", label: "Submission" },
  { value: "meeting", label: "Meeting" },
  { value: "reading", label: "Reading" },
  { value: "admin", label: "Admin" },
  { value: "social", label: "Social" },
];
const DASHBOARD_CACHE_VERSION = 1;
const PRIORITY_TIERS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const PRIORITY_ORDER = Object.fromEntries(
  PRIORITY_TIERS.map((tier, index) => [tier, index])
);

function getDashboardCacheKey(userId) {
  return `task-priority-dashboard:v${DASHBOARD_CACHE_VERSION}:${userId}`;
}

function readDashboardCache(userId) {
  if (!userId) {
    return null;
  }
  try {
    const raw = localStorage.getItem(getDashboardCacheKey(userId));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    return {
      user: parsed.user ?? null,
      tasks: Array.isArray(parsed.tasks) ? parsed.tasks : [],
      profile: parsed.profile ?? null,
    };
  } catch {
    return null;
  }
}

function writeDashboardCache(userId, user, tasks, profile) {
  if (!userId) {
    return;
  }
  try {
    localStorage.setItem(
      getDashboardCacheKey(userId),
      JSON.stringify({
        cachedAt: new Date().toISOString(),
        user: user ?? null,
        tasks: Array.isArray(tasks) ? tasks : [],
        profile: profile ?? null,
      })
    );
  } catch {
    // Ignore cache write failures and keep the live UI responsive.
  }
}

function buildSyncStatus(result) {
  const pieces = [];
  const gmail = result.emailSync?.gmail;
  const outlook = result.emailSync?.outlook;

  if (gmail?.linked) {
    pieces.push(
      gmail.error
        ? "Gmail refresh failed"
        : `Gmail ${gmail.mode || "sync"}: ${gmail.fetchedCount} message${gmail.fetchedCount === 1 ? "" : "s"}`
    );
  }

  if (outlook?.linked) {
    pieces.push(
      outlook.error
        ? "Outlook refresh failed"
        : `Outlook ${outlook.mode || "sync"}: ${outlook.fetchedCount} message${outlook.fetchedCount === 1 ? "" : "s"}`
    );
  }

  const cardSummary = result.taskCardCount
    ? `Generated ${result.taskCardCount} prioritized task card${result.taskCardCount === 1 ? "" : "s"}.`
    : "Pipeline ran successfully, but no actionable task cards were created yet.";

  return pieces.length ? `${pieces.join(" | ")}. ${cardSummary}` : cardSummary;
}

function describeFeedback(action, direction) {
  if (action === "GOT_IT") {
    return "On it";
  }
  if (action === "RESCHEDULE") {
    return "Moved to later";
  }
  if (action === "ALREADY_DONE") {
    return "Marked as done";
  }
  if (action === "WRONG_PRIORITY" && direction === "too_low") {
    return "Moved up one priority level";
  }
  if (action === "WRONG_PRIORITY" && direction === "too_high") {
    return "Moved down one priority level";
  }
  return "Feedback saved";
}

function formatPriorityTierLabel(priorityTier) {
  if (!priorityTier) {
    return "Unknown";
  }
  return `${priorityTier.charAt(0)}${priorityTier.slice(1).toLowerCase()}`;
}

function describePriorityTarget(direction, currentPriorityTier) {
  const targetTier = shiftPriorityTier(currentPriorityTier, direction);
  return `Changed priority to ${formatPriorityTierLabel(targetTier)}`;
}

function createFeedbackState(action, direction, currentPriorityTier) {
  return {
    action,
    direction: direction ?? null,
    label:
      action === "WRONG_PRIORITY" && direction
        ? describePriorityTarget(direction, currentPriorityTier)
        : describeFeedback(action, direction),
  };
}

function compareTaskPriority(a, b) {
  const priorityDelta =
    (PRIORITY_ORDER[a.priority_tier] ?? PRIORITY_TIERS.length) -
    (PRIORITY_ORDER[b.priority_tier] ?? PRIORITY_TIERS.length);

  if (priorityDelta !== 0) {
    return priorityDelta;
  }

  return (a.deadline_hours ?? Number.POSITIVE_INFINITY) - (b.deadline_hours ?? Number.POSITIVE_INFINITY);
}

function shiftPriorityTier(priorityTier, direction) {
  const currentIndex = PRIORITY_TIERS.indexOf(priorityTier);
  if (currentIndex === -1) {
    return priorityTier;
  }

  if (direction === "too_low") {
    return PRIORITY_TIERS[Math.max(0, currentIndex - 1)];
  }

  if (direction === "too_high") {
    return PRIORITY_TIERS[Math.min(PRIORITY_TIERS.length - 1, currentIndex + 1)];
  }

  return priorityTier;
}

function sortTasks(tasks) {
  return [...tasks].sort(compareTaskPriority);
}

function getPriorityChangeOptions(priorityTier) {
  const currentIndex = PRIORITY_TIERS.indexOf(priorityTier);
  if (currentIndex === -1) {
    return {
      increaseTarget: priorityTier,
      decreaseTarget: priorityTier,
      increaseDisabled: true,
      decreaseDisabled: true,
    };
  }

  return {
    increaseTarget: PRIORITY_TIERS[Math.max(0, currentIndex - 1)],
    decreaseTarget: PRIORITY_TIERS[Math.min(PRIORITY_TIERS.length - 1, currentIndex + 1)],
    increaseDisabled: currentIndex === 0,
    decreaseDisabled: currentIndex === PRIORITY_TIERS.length - 1,
  };
}

function formatDeadline(hours) {
  if (hours == null) {
    return null;
  }

  if (hours < 1) {
    return "under 1h left";
  }

  const rounded = Math.round(hours);
  const days = Math.floor(rounded / 24);
  const remainingHours = rounded % 24;

  if (days > 0 && remainingHours > 0) {
    return `${days}d ${remainingHours}h left`;
  }
  if (days > 0) {
    return `${days}d left`;
  }
  return `${rounded}h left`;
}

function formatActionWindow(value) {
  const labels = {
    NOW: "Do this now",
    TODAY: "Do this today",
    THIS_WEEK: "Do this this week",
    DEFER: "Can wait",
  };
  return labels[value] || value;
}

function formatSourceTimestamp(value) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function cleanPreviewText(value) {
  if (!value) {
    return null;
  }
  return value.replace(/[\u034f\u200b-\u200f\u202a-\u202e]/g, "").replace(/\s+/g, " ").trim();
}

function truncateText(value, limit) {
  const cleaned = cleanPreviewText(value);
  if (!cleaned || cleaned.length <= limit) {
    return cleaned;
  }
  const boundary = cleaned.lastIndexOf(" ", limit - 3);
  if (boundary >= Math.floor(limit * 0.55)) {
    return `${cleaned.slice(0, boundary).trim()}...`;
  }
  return `${cleaned.slice(0, limit - 3).trim()}...`;
}

function buildQueueSummary(task) {
  return (
    truncateText(task.task_description, 150) ||
    truncateText(task.source_snippet, 150) ||
    truncateText(task.source_subject, 120) ||
    "Expand this task to see the original email context."
  );
}

function TaskSource({ task, compact = false }) {
  const sender = cleanPreviewText(task.source_sender);
  const subject = cleanPreviewText(task.source_subject);
  const preview = truncateText(task.source_snippet || task.task_description, compact ? 180 : 320);
  const received = formatSourceTimestamp(task.source_timestamp_iso);

  if (!sender && !subject && !preview && !received) {
    return null;
  }

  return (
    <div className={`task-source${compact ? " task-source-compact" : ""}`}>
      {subject ? (
        <p className="task-source-line">
          <span>Subject:</span> {subject}
        </p>
      ) : null}
      {sender ? (
        <p className="task-source-line">
          <span>From:</span> {sender}
        </p>
      ) : null}
      {preview ? (
        <p className="task-source-line task-source-preview">
          <span>Email:</span> {preview}
        </p>
      ) : null}
      {received && !compact ? (
        <p className="task-source-line">
          <span>Received:</span> {received}
        </p>
      ) : null}
    </div>
  );
}

function TaskActions({
  task,
  feedbackState,
  isBusy,
  onFeedback,
  onRemove,
}) {
  const feedbackLabel = feedbackState?.label ?? null;
  const isStarted = feedbackState?.action === "GOT_IT";
  const isLocked =
    Boolean(feedbackState) &&
    !isStarted &&
    feedbackState?.action !== "WRONG_PRIORITY";
  const priorityChangeOptions = getPriorityChangeOptions(task.priority_tier);

  return (
    <>
      {feedbackLabel ? (
        <p className="task-feedback-note">Updated: {feedbackLabel}</p>
      ) : null}
      {isStarted ? (
        <>
          <div className="task-actions">
            <button
              className="primary-button"
              disabled={isBusy}
              onClick={() => onFeedback(task.canonical_task_id, "ALREADY_DONE")}
              type="button"
            >
              Completed
            </button>
          </div>
          <div className="task-secondary-actions">
            <button
              className="inline-button task-remove-link"
              disabled={isBusy}
              onClick={() => onRemove(task.canonical_task_id)}
              type="button"
            >
              Remove task
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="task-actions">
            <button
              className="primary-button"
              disabled={isBusy || isLocked}
              onClick={() => onFeedback(task.canonical_task_id, "GOT_IT")}
              type="button"
            >
              On it
            </button>
            <button
              className="secondary-button"
              disabled={isBusy || isLocked}
              onClick={() => onFeedback(task.canonical_task_id, "RESCHEDULE")}
              type="button"
            >
              Later
            </button>
            <button
              className="secondary-button"
              disabled={isBusy || isLocked}
              onClick={() => onFeedback(task.canonical_task_id, "ALREADY_DONE")}
              type="button"
            >
              Done
            </button>
          </div>
          <div className="task-secondary-actions">
            <span className="task-secondary-label">Adjust ranking:</span>
            <button
              className="inline-button"
              disabled={isBusy || isLocked || priorityChangeOptions.increaseDisabled}
              title={
                priorityChangeOptions.increaseDisabled
                  ? `Already ${formatPriorityTierLabel(priorityChangeOptions.increaseTarget)}`
                  : `Change priority to ${formatPriorityTierLabel(priorityChangeOptions.increaseTarget)}`
              }
              onClick={() =>
                onFeedback(
                  task.canonical_task_id,
                  "WRONG_PRIORITY",
                  "too_low",
                  task.priority_tier
                )
              }
              type="button"
            >
              Change priority to {formatPriorityTierLabel(priorityChangeOptions.increaseTarget)}
            </button>
            <button
              className="inline-button"
              disabled={isBusy || isLocked || priorityChangeOptions.decreaseDisabled}
              title={
                priorityChangeOptions.decreaseDisabled
                  ? `Already ${formatPriorityTierLabel(priorityChangeOptions.decreaseTarget)}`
                  : `Change priority to ${formatPriorityTierLabel(priorityChangeOptions.decreaseTarget)}`
              }
              onClick={() =>
                onFeedback(
                  task.canonical_task_id,
                  "WRONG_PRIORITY",
                  "too_high",
                  task.priority_tier
                )
              }
              type="button"
            >
              Change priority to {formatPriorityTierLabel(priorityChangeOptions.decreaseTarget)}
            </button>
            <button
              className="inline-button task-remove-link"
              disabled={isBusy}
              onClick={() => onRemove(task.canonical_task_id)}
              type="button"
            >
              Remove task
            </button>
          </div>
        </>
      )}
    </>
  );
}

function FocusCard({ task, feedbackState, isBusy, onFeedback, onRemove }) {
  return (
    <article className={`task-card task-card-focus task-card-tier-${task.priority_tier.toLowerCase()}`}>
      <div className="task-card-top">
        <span className={`task-tier task-tier-${task.priority_tier.toLowerCase()}`}>
          {task.priority_tier}
        </span>
        {formatDeadline(task.deadline_hours) ? (
          <span className="task-deadline-badge">{formatDeadline(task.deadline_hours)}</span>
        ) : null}
      </div>
      <h2 className="task-focus-title">{cleanPreviewText(task.task_title) || "Untitled task"}</h2>
      <p className="task-focus-window">{formatActionWindow(task.action_window)}</p>
      {task.task_description ? (
        <p className="task-description task-description-focus">
          {truncateText(task.task_description, 280)}
        </p>
      ) : null}
      <TaskSource task={task} />
      <p className="task-rationale">
        <span>Why now:</span> {cleanPreviewText(task.rationale)}
      </p>
      <div className="task-meta">
        <span>Confidence {Math.round((task.confidence ?? 0) * 100)}%</span>
        <span>{task.platforms_seen?.join(", ") || "email"}</span>
      </div>
      <TaskActions
        feedbackState={feedbackState}
        isBusy={isBusy}
        onFeedback={onFeedback}
        onRemove={onRemove}
        task={task}
      />
    </article>
  );
}

function QueueCard({
  task,
  feedbackState,
  isBusy,
  onFeedback,
  onRemove,
  index,
  expanded,
  onToggle,
}) {
  return (
    <article className={`task-card task-card-queue${expanded ? " task-card-queue-expanded" : ""}`}>
      <div className="task-card-top task-card-top-queue">
        <div className="task-queue-heading">
          <span className="task-queue-index">{String(index + 2).padStart(2, "0")}</span>
          <div>
            <h3 className="task-title">{cleanPreviewText(task.task_title) || "Untitled task"}</h3>
            <p className="task-queue-window">{formatActionWindow(task.action_window)}</p>
          </div>
        </div>
        <div className="task-queue-controls">
          {formatDeadline(task.deadline_hours) ? (
            <span className="task-queue-deadline">{formatDeadline(task.deadline_hours)}</span>
          ) : null}
          <button className="inline-button task-expand-button" onClick={() => onToggle(task.canonical_task_id)} type="button">
            {expanded ? "Hide details" : "Expand"}
          </button>
        </div>
      </div>
      <p className="task-queue-summary">{buildQueueSummary(task)}</p>
      <div className="task-meta task-meta-compact">
        <span>{task.platforms_seen?.join(", ") || "email"}</span>
        <span>Confidence {Math.round((task.confidence ?? 0) * 100)}%</span>
      </div>
      {expanded ? (
        <div className="task-card-details">
          <TaskSource compact task={task} />
          <p className="task-rationale task-rationale-queue">
            <span>Why now:</span> {cleanPreviewText(task.rationale)}
          </p>
          <TaskActions
            feedbackState={feedbackState}
            isBusy={isBusy}
            onFeedback={onFeedback}
            onRemove={onRemove}
            task={task}
          />
        </div>
      ) : null}
    </article>
  );
}

export default function Home() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [pipelineProfile, setPipelineProfile] = useState(null);
  const [taskFeedbackStates, setTaskFeedbackStates] = useState({});
  const [taskError, setTaskError] = useState("");
  const [taskStatus, setTaskStatus] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);
  const [feedbackQueue, setFeedbackQueue] = useState([]);
  const [isProcessingFeedbackQueue, setIsProcessingFeedbackQueue] = useState(false);
  const [removingTaskId, setRemovingTaskId] = useState(null);
  const [expandedTaskIds, setExpandedTaskIds] = useState({});
  const [isManualFormOpen, setIsManualFormOpen] = useState(false);
  const [isCreatingManualTask, setIsCreatingManualTask] = useState(false);
  const [manualTask, setManualTask] = useState({
    title: "",
    description: "",
    taskType: "admin",
    deadlineAt: "",
    entityName: "",
  });

  useEffect(() => {
    async function loadDashboard() {
      const cachedUserId = getStoredUserId();
      const cached = readDashboardCache(cachedUserId);
      if (cached) {
        if (cached.user) {
          setUser(cached.user);
        }
        setTasks(cached.tasks ?? []);
        setPipelineProfile(cached.profile ?? null);
      }

      try {
        const dashboard = await fetchDashboardBootstrap();
        setUser(dashboard.user);
        setTasks(dashboard.items ?? []);
        setPipelineProfile(dashboard.profile ?? null);
      } catch {
        if (cached) {
          setTaskError("Using your last saved dashboard while fresh data is temporarily unavailable.");
          return;
        }
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    loadDashboard();
  }, [navigate]);

  const focusTask = tasks[0] ?? null;
  const queueTasks = useMemo(() => tasks.slice(1), [tasks]);
  const priorityCounts = useMemo(() => {
    const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    tasks.forEach((task) => {
      counts[task.priority_tier] = (counts[task.priority_tier] || 0) + 1;
    });
    return counts;
  }, [tasks]);

  useEffect(() => {
    if (!user?.userId) {
      return;
    }
    writeDashboardCache(user.userId, user, tasks, pipelineProfile);
  }, [pipelineProfile, tasks, user]);

  useEffect(() => {
    setExpandedTaskIds((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([canonicalTaskId]) =>
          tasks.some((task) => task.canonical_task_id === canonicalTaskId)
        )
      )
    );
  }, [tasks]);

  useEffect(() => {
    if (isProcessingFeedbackQueue || feedbackQueue.length === 0) {
      return;
    }

    const next = feedbackQueue[0];
    let cancelled = false;

    async function flushFeedback() {
      setIsProcessingFeedbackQueue(true);
      try {
        const result = await submitTaskFeedback(next.canonicalTaskId, {
          action: next.action,
          direction: next.direction,
        });
        if (cancelled) {
          return;
        }
        if (result.profile) {
          setPipelineProfile(result.profile);
        } else {
          const latestProfile = await fetchPipelineProfile();
          if (cancelled) {
            return;
          }
          setPipelineProfile(latestProfile);
        }
        if (result.items) {
          setTasks(result.items);
        }
        setTaskStatus(
          next.action === "RESCHEDULE"
            ? "Marked for later. Your profile was updated."
            : next.action === "WRONG_PRIORITY"
              ? "Priority updated. Your profile was updated."
              : "Feedback saved. Your profile was updated."
        );
      } catch (error) {
        if (cancelled) {
          return;
        }
        setTaskError(error.message);
        try {
          const [taskPayload, profilePayload] = await Promise.all([
            fetchPrioritizedTasks(),
            fetchPipelineProfile(),
          ]);
          if (cancelled) {
            return;
          }
          setTasks(taskPayload.items ?? []);
          setPipelineProfile(profilePayload);
        } catch {
          // Keep the optimistic state if recovery fetch also fails.
        }
        setTaskFeedbackStates((current) => {
          const updated = { ...current };
          delete updated[next.canonicalTaskId];
          return updated;
        });
      } finally {
        if (cancelled) {
          return;
        }
        setFeedbackQueue((current) => current.slice(1));
        setIsProcessingFeedbackQueue(false);
      }
    }

    flushFeedback();

    return () => {
      cancelled = true;
    };
  }, [feedbackQueue, isProcessingFeedbackQueue]);

  function handleLogout() {
    clearStoredToken();
    navigate("/", { replace: true });
  }

  function updateTaskListFromResponse(result) {
    if (result?.items) {
      setTasks(result.items);
    }
    if (result?.profile) {
      setPipelineProfile(result.profile);
    }
  }

  function applyLocalFeedback(canonicalTaskId, action, direction) {
    setTasks((current) => {
      const selectedTask = current.find((task) => task.canonical_task_id === canonicalTaskId);
      if (!selectedTask) {
        return current;
      }

      if (action === "ALREADY_DONE") {
        return current.filter((task) => task.canonical_task_id !== canonicalTaskId);
      }

      if (action === "RESCHEDULE") {
        return [
          ...current.filter((task) => task.canonical_task_id !== canonicalTaskId),
          selectedTask,
        ];
      }

      if (action === "WRONG_PRIORITY" && direction) {
        return sortTasks(
          current.map((task) =>
            task.canonical_task_id === canonicalTaskId
              ? { ...task, priority_tier: shiftPriorityTier(task.priority_tier, direction) }
              : task
          )
        );
      }

      return current;
    });
  }

  async function handleSyncTasks() {
    setIsSyncing(true);
    setTaskError("");
    setTaskStatus("");
    try {
      const result = await syncPrioritizedTasks();
      setTasks(result.items ?? []);
      setTaskFeedbackStates({});
      const latestProfile = await fetchPipelineProfile();
      setPipelineProfile(latestProfile);
      setTaskStatus(buildSyncStatus(result));
    } catch (error) {
      setTaskError(error.message);
    } finally {
      setIsSyncing(false);
    }
  }

  function handleFeedback(canonicalTaskId, action, direction, currentPriorityTier = null) {
    setTaskError("");
    setTaskFeedbackStates((current) => ({
      ...current,
      [canonicalTaskId]: createFeedbackState(action, direction, currentPriorityTier),
    }));
    applyLocalFeedback(canonicalTaskId, action, direction);
    setTaskStatus(
      action === "RESCHEDULE"
        ? "Marked for later. Saving feedback in the background."
        : action === "WRONG_PRIORITY"
          ? "Updating priority and profile in the background."
          : "Feedback saved. Updating your profile in the background."
    );
    setFeedbackQueue((current) => [
      ...current,
      { canonicalTaskId, action, direction: direction ?? null },
    ]);
  }

  async function handleRemoveTask(canonicalTaskId) {
    setRemovingTaskId(canonicalTaskId);
    setTaskError("");
    setTaskStatus("");
    try {
      await removePrioritizedTask(canonicalTaskId);
      setTasks((current) =>
        current.filter((task) => task.canonical_task_id !== canonicalTaskId)
      );
      setTaskFeedbackStates((current) => {
        const next = { ...current };
        delete next[canonicalTaskId];
        return next;
      });
      setTaskStatus("Task removed from your active queue.");
    } catch (error) {
      setTaskError(error.message);
    } finally {
      setRemovingTaskId(null);
    }
  }

  async function handleCreateManualTask(event) {
    event.preventDefault();
    setTaskError("");
    setTaskStatus("");
    setIsCreatingManualTask(true);
    try {
      const result = await createManualTask({
        title: manualTask.title,
        description: manualTask.description || null,
        taskType: manualTask.taskType,
        deadlineAt: manualTask.deadlineAt || null,
        entityName: manualTask.entityName || null,
      });
      updateTaskListFromResponse(result);
      if (!result.profile) {
        const latestProfile = await fetchPipelineProfile();
        setPipelineProfile(latestProfile);
      }
      setManualTask({
        title: "",
        description: "",
        taskType: "admin",
        deadlineAt: "",
        entityName: "",
      });
      setIsManualFormOpen(false);
      setTaskStatus("Manual task added and queued for prioritization.");
    } catch (error) {
      setTaskError(error.message);
    } finally {
      setIsCreatingManualTask(false);
    }
  }

  function updateManualTask(field, value) {
    setManualTask((current) => ({
      ...current,
      [field]: value,
    }));
  }

  function toggleTaskExpansion(canonicalTaskId) {
    setExpandedTaskIds((current) => ({
      ...current,
      [canonicalTaskId]: !current[canonicalTaskId],
    }));
  }

  if (!user) {
    return <main className="simple-shell">Loading your dashboard...</main>;
  }

  return (
    <main className="simple-shell">
      <PageNav />
      <section className="simple-hero">
        <p className="auth-eyebrow">Priority Queue</p>
        <h1 className="simple-title">Focus</h1>
        <p className="simple-copy">
          This page is meant to answer one question: what should you do first?
        </p>
      </section>

      <section className="simple-card">
        <div className="summary-grid summary-grid-wide">
          <article className="summary-card">
            <p className="summary-label">Signed in as</p>
            <p className="summary-value">{user.email}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Current focus</p>
            <p className="summary-value">{getPreferenceLabel(user.preferences)}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Profile confidence</p>
            <p className="summary-value">
              {pipelineProfile ? `${Math.round((pipelineProfile.confidence ?? 0) * 100)}%` : "0%"}
            </p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Queue snapshot</p>
            <p className="summary-value summary-value-stack">
              <span>{priorityCounts.CRITICAL} critical</span>
              <span>{priorityCounts.HIGH} high</span>
              <span>{tasks.length} active</span>
            </p>
          </article>
        </div>

        <div className="home-actions">
          <button
            className="auth-button home-link"
            disabled={isSyncing}
            onClick={handleSyncTasks}
            type="button"
          >
            {isSyncing ? "Refreshing priorities..." : "Refresh task priorities"}
          </button>
          <button
            className="secondary-button home-link"
            onClick={() => setIsManualFormOpen((current) => !current)}
            type="button"
          >
            {isManualFormOpen ? "Close manual task" : "Add manual task"}
          </button>
          <Link className="secondary-button home-link" to="/linking">
            Manage linked accounts
          </Link>
          <Link className="secondary-button home-link" to="/onboarding">
            Update preference
          </Link>
          <button
            className="inline-button danger-button"
            disabled={!user}
            onClick={handleLogout}
            type="button"
          >
            Log out
          </button>
        </div>

        {isManualFormOpen ? (
          <form className="manual-task-form" onSubmit={handleCreateManualTask}>
            <div className="manual-task-grid">
              <label className="field-group">
                <span>Task title</span>
                <input
                  className="auth-input"
                  onChange={(event) => updateManualTask("title", event.target.value)}
                  placeholder="e.g. Submit CS2103T reflection"
                  required
                  type="text"
                  value={manualTask.title}
                />
              </label>
              <label className="field-group">
                <span>Task type</span>
                <select
                  className="auth-input"
                  onChange={(event) => updateManualTask("taskType", event.target.value)}
                  value={manualTask.taskType}
                >
                  {TASK_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-group">
                <span>Deadline</span>
                <input
                  className="auth-input"
                  onChange={(event) => updateManualTask("deadlineAt", event.target.value)}
                  type="datetime-local"
                  value={manualTask.deadlineAt}
                />
              </label>
              <label className="field-group">
                <span>Related topic</span>
                <input
                  className="auth-input"
                  onChange={(event) => updateManualTask("entityName", event.target.value)}
                  placeholder="Optional course, club, or topic"
                  type="text"
                  value={manualTask.entityName}
                />
              </label>
            </div>
            <label className="field-group">
              <span>Details</span>
              <textarea
                className="auth-input auth-textarea"
                onChange={(event) => updateManualTask("description", event.target.value)}
                placeholder="Add any context you want the system to remember."
                rows={4}
                value={manualTask.description}
              />
            </label>
            <div className="manual-task-actions">
              <button className="auth-button" disabled={isCreatingManualTask} type="submit">
                {isCreatingManualTask ? "Adding task..." : "Save manual task"}
              </button>
              <p className="panel-copy">
                Manual tasks are written into the same pipeline flow and also update your learned profile.
              </p>
            </div>
          </form>
        ) : null}

        {taskStatus ? <p className="success-text">{taskStatus}</p> : null}
        {taskError ? <p className="error-text">{taskError}</p> : null}

        <section className="tasks-section">
          <div className="tasks-heading">
            <div>
              <p className="panel-title">Focus on this first</p>
              <p className="panel-copy">
                One top-priority card gets the most space. Everything else stays in the queue below.
              </p>
            </div>
          </div>

          {focusTask ? (
            <FocusCard
              feedbackState={taskFeedbackStates[focusTask.canonical_task_id]}
              isBusy={removingTaskId === focusTask.canonical_task_id}
              onFeedback={handleFeedback}
              onRemove={handleRemoveTask}
              task={focusTask}
            />
          ) : (
            <div className="task-card task-card-empty">
              <p className="summary-value">No prioritized tasks yet.</p>
              <p className="panel-copy">
                Run the pipeline after syncing email, or add a manual task to seed your queue.
              </p>
            </div>
          )}

          {queueTasks.length ? (
            <div className="queue-section">
              <div className="tasks-heading">
                <div>
                  <p className="panel-title">Up next</p>
                  <p className="panel-copy">
                    These items stay visible, but they are intentionally less prominent than the focus card.
                  </p>
                </div>
              </div>
              <div className="task-card-list task-card-list-queue">
                {queueTasks.map((task, index) => (
                  <QueueCard
                    expanded={Boolean(expandedTaskIds[task.canonical_task_id])}
                    feedbackState={taskFeedbackStates[task.canonical_task_id]}
                    index={index}
                    isBusy={removingTaskId === task.canonical_task_id}
                    key={task.canonical_task_id}
                    onFeedback={handleFeedback}
                    onRemove={handleRemoveTask}
                    onToggle={toggleTaskExpansion}
                    task={task}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </section>
      </section>
    </main>
  );
}
