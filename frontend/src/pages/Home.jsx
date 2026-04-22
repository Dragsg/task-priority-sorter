import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  createManualTask,
  fetchDashboardBootstrap,
  fetchPipelineProfile,
  fetchPrioritizedTasks,
  getStoredUser,
  getStoredUserId,
  submitTaskFeedback,
  syncPrioritizedTasks,
  updateTaskTags,
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
const DASHBOARD_CACHE_VERSION = 3;
const PRIORITY_TIERS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

function normalizeManualTag(value) {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function dedupeManualTags(values) {
  const seen = new Set();
  const ordered = [];
  values.forEach((value) => {
    const normalized = normalizeManualTag(value);
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    ordered.push(normalized);
  });
  return ordered;
}

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
  if (action === "ACCEPT") {
    return "Accepted";
  }
  if (action === "REJECT") {
    return "Rejected";
  }
  if (action === "COMPLETED") {
    return "Marked as completed";
  }
  if (action === "DELETE") {
    return "Deleted";
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

function getVisibleTaskTags(task) {
  if (!Array.isArray(task?.tags)) {
    return [];
  }

  const seen = new Set();
  return task.tags.filter((tag) => {
    if (typeof tag !== "string") {
      return false;
    }
    const normalized = tag.trim().toLowerCase();
    if (!normalized || seen.has(normalized)) {
      return false;
    }
    seen.add(normalized);
    return true;
  });
}

function TaskTags({ task, isBusy = false, onRemoveTag }) {
  const tags = getVisibleTaskTags(task);
  if (!tags.length) {
    return null;
  }

  return (
    <div className="task-tag-block">
      <span className="task-tag-label">Tags</span>
      <div className="task-tag-list">
        {tags.map((tag) => (
          <span className="task-tag-chip task-tag-chip-editable" key={tag}>
            <span className="task-tag-chip-text">{tag.replace(/_/g, " ")}</span>
            {onRemoveTag ? (
              <button
                aria-label={`Remove ${tag} tag`}
                className="task-tag-chip-remove"
                disabled={isBusy}
                onClick={() => onRemoveTag(tag)}
                type="button"
              >
                ×
              </button>
            ) : null}
          </span>
        ))}
      </div>
    </div>
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
}) {
  const feedbackLabel = feedbackState?.label ?? null;
  const priorityChangeOptions = getPriorityChangeOptions(task.priority_tier);

  return (
    <>
      {feedbackLabel ? (
        <p className="task-feedback-note">Updated: {feedbackLabel}</p>
      ) : null}
      <div className="task-actions">
        <button
          className="primary-button"
          disabled={isBusy}
          onClick={() => onFeedback(task.canonical_task_id, "ACCEPT")}
          type="button"
        >
          Accept
        </button>
        <button
          className="secondary-button"
          disabled={isBusy}
          onClick={() => onFeedback(task.canonical_task_id, "REJECT")}
          type="button"
        >
          Reject
        </button>
      </div>
      <div className="task-secondary-actions">
        <span className="task-secondary-label">Adjust ranking:</span>
        <button
          className="inline-button"
          disabled={isBusy || priorityChangeOptions.increaseDisabled}
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
          disabled={isBusy || priorityChangeOptions.decreaseDisabled}
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
      </div>
    </>
  );
}

function TaskCard({ task, feedbackState, isBusy, onFeedback, onRemoveTag, index = 0 }) {
  return (
    <article className={`task-card task-card-queue task-card-tier-${task.priority_tier.toLowerCase()}`}>
      <div className="task-card-top task-card-top-queue">
        <div className="task-queue-heading">
          <span className="task-queue-index">{String(index + 1).padStart(2, "0")}</span>
          <div>
            <span className={`task-tier task-tier-${task.priority_tier.toLowerCase()}`}>
              {formatPriorityTierLabel(task.priority_tier)}
            </span>
            <h3 className="task-title">{cleanPreviewText(task.task_title) || "Untitled task"}</h3>
            <p className="task-queue-window">{formatActionWindow(task.action_window)}</p>
          </div>
        </div>
        <div className="task-queue-controls">
          {formatDeadline(task.deadline_hours) ? (
            <span className="task-queue-deadline">{formatDeadline(task.deadline_hours)}</span>
          ) : null}
        </div>
      </div>
      <p className="task-queue-summary">
        {buildQueueSummary(task)}
      </p>
      <TaskTags
        isBusy={isBusy}
        onRemoveTag={onRemoveTag ? (tag) => onRemoveTag(task.canonical_task_id, tag) : null}
        task={task}
      />
      <div className="task-meta task-meta-compact">
        <span>Confidence {Math.round((task.confidence ?? 0) * 100)}%</span>
        <span>{task.platforms_seen?.join(", ") || "email"}</span>
      </div>
      <div className="task-card-details">
        <TaskSource compact task={task} />
        <p className="task-rationale task-rationale-queue">
          <span>Why now:</span> {cleanPreviewText(task.rationale)}
        </p>
        <TaskActions
          feedbackState={feedbackState}
          isBusy={isBusy}
          onFeedback={onFeedback}
          task={task}
        />
      </div>
    </article>
  );
}

function QueueCard({
  task,
  feedbackState,
  isBusy,
  onFeedback,
  onRemoveTag,
  index,
}) {
  return (
    <TaskCard
      feedbackState={feedbackState}
      index={index}
      isBusy={isBusy}
      onFeedback={onFeedback}
      onRemoveTag={onRemoveTag}
      task={task}
    />
  );
}

export default function Home() {
  const navigate = useNavigate();
  const cachedUserId = getStoredUserId();
  const cachedDashboard = readDashboardCache(cachedUserId);
  const [user, setUser] = useState(() => cachedDashboard?.user ?? getStoredUser());
  const [tasks, setTasks] = useState(() => cachedDashboard?.tasks ?? []);
  const [pipelineProfile, setPipelineProfile] = useState(() => cachedDashboard?.profile ?? null);
  const [availableTags, setAvailableTags] = useState([]);
  const [taskFeedbackStates, setTaskFeedbackStates] = useState({});
  const [taskTagUpdateStates, setTaskTagUpdateStates] = useState({});
  const [taskError, setTaskError] = useState("");
  const [taskStatus, setTaskStatus] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);
  const [feedbackQueue, setFeedbackQueue] = useState([]);
  const [isProcessingFeedbackQueue, setIsProcessingFeedbackQueue] = useState(false);
  const [isManualFormOpen, setIsManualFormOpen] = useState(false);
  const [isCreatingManualTask, setIsCreatingManualTask] = useState(false);
  const [isManualTagInputFocused, setIsManualTagInputFocused] = useState(false);
  const [manualTask, setManualTask] = useState({
    title: "",
    description: "",
    taskType: "admin",
    deadlineAt: "",
    entityName: "",
    tags: [],
    tagInput: "",
  });

  useEffect(() => {
    async function loadDashboard() {
      const currentUserId = getStoredUserId();
      const cached = readDashboardCache(currentUserId);
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
        setAvailableTags(dashboard.availableTags ?? []);
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
          next.action === "WRONG_PRIORITY"
            ? "Priority updated. Your profile was updated."
            : next.action === "ACCEPT"
              ? "Task accepted and removed from review."
              : next.action === "REJECT"
                ? "Task rejected and removed from review."
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
    if (result?.availableTags) {
      setAvailableTags(result.availableTags);
    }
  }

  function applyLocalFeedback(canonicalTaskId, action, direction) {
    setTasks((current) => {
      const selectedTask = current.find((task) => task.canonical_task_id === canonicalTaskId);
      if (!selectedTask) {
        return current;
      }

      if (action === "ACCEPT" || action === "REJECT") {
        return [
          ...current.filter((task) => task.canonical_task_id !== canonicalTaskId),
        ];
      }

      if (action === "WRONG_PRIORITY" && direction) {
        return current.map((task) =>
          task.canonical_task_id === canonicalTaskId
            ? { ...task, priority_tier: shiftPriorityTier(task.priority_tier, direction) }
            : task
        );
      }

      return current;
    });
  }

  function applyLocalTagUpdate(canonicalTaskId, nextTags) {
    setTasks((current) =>
      current.map((task) =>
        task.canonical_task_id === canonicalTaskId
          ? { ...task, tags: nextTags }
          : task
      )
    );
  }

  async function handleSyncTasks() {
    setIsSyncing(true);
    setTaskError("");
    setTaskStatus("");
    try {
      const result = await syncPrioritizedTasks();
      setTasks(result.items ?? []);
      setAvailableTags(result.availableTags ?? []);
      setTaskFeedbackStates({});
      setTaskTagUpdateStates({});
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
      action === "WRONG_PRIORITY"
        ? "Updating priority and profile in the background."
        : action === "ACCEPT"
          ? "Accepting task and updating your profile in the background."
          : action === "REJECT"
            ? "Rejecting task and updating your profile in the background."
            : "Feedback saved. Updating your profile in the background."
    );
    setFeedbackQueue((current) => [
      ...current,
      { canonicalTaskId, action, direction: direction ?? null },
    ]);
  }

  async function handleRemoveTaskTag(canonicalTaskId, tagToRemove) {
    const selectedTask = tasks.find((task) => task.canonical_task_id === canonicalTaskId);
    if (!selectedTask) {
      return;
    }

    const nextTags = getVisibleTaskTags(selectedTask).filter((tag) => tag !== tagToRemove);
    setTaskError("");
    setTaskStatus("Saving your tag correction.");
    setTaskTagUpdateStates((current) => ({
      ...current,
      [canonicalTaskId]: tagToRemove,
    }));
    applyLocalTagUpdate(canonicalTaskId, nextTags);

    try {
      const result = await updateTaskTags(canonicalTaskId, nextTags);
      updateTaskListFromResponse(result);
      setTaskStatus(`Removed tag "${tagToRemove.replace(/_/g, " ")}".`);
    } catch (error) {
      setTaskError(error.message);
      try {
        const taskPayload = await fetchPrioritizedTasks();
        setTasks(taskPayload.items ?? []);
      } catch {
        // Keep the optimistic tag state if refresh fails.
      }
    } finally {
      setTaskTagUpdateStates((current) => {
        const updated = { ...current };
        delete updated[canonicalTaskId];
        return updated;
      });
    }
  }

  async function handleCreateManualTask(event) {
    event.preventDefault();
    setTaskError("");
    setTaskStatus("");
    setIsCreatingManualTask(true);
    const finalTags = dedupeManualTags([
      ...manualTask.tags,
      manualTask.tagInput,
    ]);
    try {
      const result = await createManualTask({
        title: manualTask.title,
        description: manualTask.description || null,
        taskType: manualTask.taskType,
        deadlineAt: manualTask.deadlineAt || null,
        entityName: manualTask.entityName || null,
        tags: finalTags,
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
        tags: [],
        tagInput: "",
      });
      setIsManualTagInputFocused(false);
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

  function commitManualTag(rawValue) {
    const normalized = normalizeManualTag(rawValue);
    if (!normalized) {
      setManualTask((current) => ({
        ...current,
        tagInput: "",
      }));
      return;
    }

    setManualTask((current) => ({
      ...current,
      tags: dedupeManualTags([...current.tags, normalized]),
      tagInput: "",
    }));
  }

  function removeManualTag(tagToRemove) {
    setManualTask((current) => ({
      ...current,
      tags: current.tags.filter((tag) => tag !== tagToRemove),
    }));
  }

  function handleManualTagInputChange(event) {
    const nextValue = event.target.value;
    const segments = nextValue.split(",");
    if (segments.length > 1) {
      const completedTags = segments.slice(0, -1);
      setManualTask((current) => ({
        ...current,
        tags: dedupeManualTags([...current.tags, ...completedTags]),
        tagInput: segments[segments.length - 1],
      }));
      return;
    }

    updateManualTask("tagInput", nextValue);
  }

  function handleManualTagKeyDown(event) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commitManualTag(manualTask.tagInput);
      return;
    }

    if (event.key === "Backspace" && !manualTask.tagInput && manualTask.tags.length) {
      event.preventDefault();
      const lastTag = manualTask.tags[manualTask.tags.length - 1];
      removeManualTag(lastTag);
    }
  }

  const filteredAvailableTags = useMemo(() => {
    const selected = new Set(manualTask.tags);
    const query = normalizeManualTag(manualTask.tagInput);
    return availableTags
      .map((tag) => normalizeManualTag(tag))
      .filter((tag) => tag && !selected.has(tag))
      .filter((tag) => !query || tag.includes(query))
      .sort((left, right) => {
        const leftStarts = query && left.startsWith(query) ? 0 : 1;
        const rightStarts = query && right.startsWith(query) ? 0 : 1;
        if (leftStarts !== rightStarts) {
          return leftStarts - rightStarts;
        }
        return left.localeCompare(right);
      })
      .slice(0, query ? 8 : 12);
  }, [availableTags, manualTask.tagInput, manualTask.tags]);

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
            <p className="summary-value">{user?.email ?? "Refreshing your account..."}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Current focus</p>
            <p className="summary-value">
              {getPreferenceLabel(user?.preferences) ?? "Loading preference..."}
            </p>
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
          <Link className="auth-button home-link" to="/statistics">
            Open statistics
          </Link>
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
              <span>Tags</span>
              <div className="manual-tag-field">
                <div className="manual-tag-input-shell">
                  {manualTask.tags.map((tag) => (
                    <span className="manual-tag-chip" key={tag}>
                      {tag.replace(/_/g, " ")}
                      <button
                        aria-label={`Remove ${tag}`}
                        className="manual-tag-remove"
                        onClick={() => removeManualTag(tag)}
                        type="button"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  <input
                    className="manual-tag-input"
                    onBlur={() => {
                      commitManualTag(manualTask.tagInput);
                      setIsManualTagInputFocused(false);
                    }}
                    onChange={handleManualTagInputChange}
                    onFocus={() => setIsManualTagInputFocused(true)}
                    onKeyDown={handleManualTagKeyDown}
                    placeholder={manualTask.tags.length ? "Add another tag" : "Type a tag and press Enter"}
                    type="text"
                    value={manualTask.tagInput}
                  />
                </div>
                {isManualTagInputFocused && filteredAvailableTags.length ? (
                  <div className="manual-tag-autocomplete">
                    <p className="manual-tag-autocomplete-label">Suggested tags</p>
                    <div className="manual-tag-suggestions">
                      {filteredAvailableTags.map((tag) => (
                        <button
                          className="manual-tag-suggestion"
                          key={tag}
                          onMouseDown={(event) => event.preventDefault()}
                          onClick={() => commitManualTag(tag)}
                          type="button"
                        >
                          {tag.replace(/_/g, " ")}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </label>
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
            {availableTags.length ? (
              <p className="panel-copy">
                Press `Enter` or type a comma to turn a tag into a chip. Fixed and custom tags appear as suggestions while you type.
              </p>
            ) : null}
          </form>
        ) : null}

        {taskStatus ? <p className="success-text">{taskStatus}</p> : null}
        {taskError ? <p className="error-text">{taskError}</p> : null}

        <section className="tasks-section">
          {tasks.length ? (
            <div className="task-card-list">
              {tasks.map((task, index) => (
                <QueueCard
                  feedbackState={taskFeedbackStates[task.canonical_task_id]}
                  index={index}
                  isBusy={Boolean(taskTagUpdateStates[task.canonical_task_id])}
                  key={task.canonical_task_id}
                  onFeedback={handleFeedback}
                  onRemoveTag={handleRemoveTaskTag}
                  task={task}
                />
              ))}
            </div>
          ) : (
            <div className="task-card task-card-empty">
              <p className="summary-value">No prioritized tasks yet.</p>
              <p className="panel-copy">
                Run the pipeline after syncing email, or add a manual task to seed your queue.
              </p>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}
