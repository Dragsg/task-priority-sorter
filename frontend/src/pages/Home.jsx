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
  LIVE_REFRESH_INTERVAL_MS,
  submitTaskFeedback,
  syncPrioritizedTasks,
  updatePrioritizedTask,
  updateTaskTags,
} from "../api";
import PageNav from "../components/PageNav";

const TASK_TYPE_OPTIONS = [
  { value: "submission", label: "Submission" },
  { value: "meeting", label: "Meeting" },
  { value: "reading", label: "Reading" },
  { value: "admin", label: "Admin" },
  { value: "social", label: "Social" },
];
const DASHBOARD_CACHE_VERSION = 4;
const PRIORITY_TIERS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const TASK_STATUS_OPTIONS = ["OPEN", "COMPLETED"];

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

function buildTagSuggestions(availableTags, selectedTags, inputValue, limit = 8) {
  const selected = new Set((selectedTags || []).map((tag) => normalizeManualTag(tag)));
  const query = normalizeManualTag(inputValue);
  return (availableTags || [])
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
    .slice(0, limit);
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

function buildSyncStatus(result, previousTasks = []) {
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

  const previousIds = new Set(
    (previousTasks || [])
      .map((task) => task?.canonical_task_id)
      .filter(Boolean)
  );
  const currentItems = Array.isArray(result.items) ? result.items : [];
  const addedCount = currentItems.filter(
    (task) => task?.canonical_task_id && !previousIds.has(task.canonical_task_id)
  ).length;

  let cardSummary = "Queue refreshed with no new visible task cards added.";
  if (addedCount > 0) {
    cardSummary = `Added ${addedCount} new prioritized task card${addedCount === 1 ? "" : "s"} to your queue.`;
  } else if (!currentItems.length) {
    cardSummary = "Queue refreshed, but there are still no visible task cards in your queue.";
  }

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

function getTaskWorkflowStatus(task) {
  return String(task?.status || "").toLowerCase() === "completed" ? "COMPLETED" : "OPEN";
}

function formatDateTimeLocalInput(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  const offsetMilliseconds = parsed.getTimezoneOffset() * 60 * 1000;
  return new Date(parsed.getTime() - offsetMilliseconds).toISOString().slice(0, 16);
}

function createTaskEditDraft(task) {
  return {
    title: cleanPreviewText(task.task_title) || "",
    description: task.task_description || "",
    deadlineAt: formatDateTimeLocalInput(task.deadline_at_iso),
    priorityTier: task.priority_tier || "MEDIUM",
    status: getTaskWorkflowStatus(task),
    tags: getVisibleTaskTags(task),
  };
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

function TaskTags({ task, isBusy = false, availableTags = [], onChangeTags }) {
  const tags = getVisibleTaskTags(task);
  const [tagInput, setTagInput] = useState("");
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const suggestions = useMemo(
    () => buildTagSuggestions(availableTags, tags, tagInput),
    [availableTags, tags, tagInput]
  );

  useEffect(() => {
    setTagInput("");
  }, [task.canonical_task_id, task.tags]);

  function commitTag(rawValue) {
    const normalized = normalizeManualTag(rawValue);
    if (!normalized) {
      setTagInput("");
      return;
    }
    setTagInput("");
    setIsComposerOpen(false);
    onChangeTags?.(task.canonical_task_id, dedupeManualTags([...tags, normalized]), {
      type: "add",
      tag: normalized,
    });
  }

  function removeTag(tagToRemove) {
    onChangeTags?.(
      task.canonical_task_id,
      tags.filter((tag) => tag !== tagToRemove),
      { type: "remove", tag: tagToRemove }
    );
  }

  function handleInputChange(event) {
    const nextValue = event.target.value;
    const segments = nextValue.split(",");
    if (segments.length > 1) {
      const completedTags = dedupeManualTags(segments.slice(0, -1));
      const nextTags = dedupeManualTags([...tags, ...completedTags]);
      const lastAdded = completedTags[completedTags.length - 1];
      setTagInput(segments[segments.length - 1]);
      if (nextTags.length !== tags.length) {
        onChangeTags?.(task.canonical_task_id, nextTags, {
          type: "add",
          tag: lastAdded ?? null,
        });
      }
      return;
    }
    setTagInput(nextValue);
  }

  function handleInputKeyDown(event) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commitTag(tagInput);
      return;
    }

    if (event.key === "Backspace" && !tagInput && tags.length) {
      event.preventDefault();
      removeTag(tags[tags.length - 1]);
    }
  }

  if (!tags.length && !onChangeTags) {
    return null;
  }

  return (
    <div className="task-tag-block">
      <div className="task-tag-header">
        <span className="task-tag-label">Tags</span>
      </div>
      <div className="task-tag-row">
        {tags.length ? (
          <div className="task-tag-list">
            {tags.map((tag) => (
              <span className="task-tag-chip task-tag-chip-editable" key={tag}>
                <span className="task-tag-chip-text">{tag.replace(/_/g, " ")}</span>
                {onChangeTags ? (
                  <button
                    aria-label={`Remove ${tag} tag`}
                    className="task-tag-chip-remove"
                    disabled={isBusy}
                    onClick={() => removeTag(tag)}
                    type="button"
                  >
                    &times;
                  </button>
                ) : null}
              </span>
            ))}
          </div>
        ) : (
          <p className="task-tag-empty">No tags yet.</p>
        )}
        {onChangeTags ? (
          <button
            className="task-tag-inline-action task-tag-inline-action-near"
            disabled={isBusy}
            onClick={() => setIsComposerOpen((current) => !current)}
            type="button"
          >
            {isComposerOpen ? "Close" : "Add tag"}
          </button>
        ) : null}
      </div>
      {isComposerOpen ? (
        <div className="task-tag-editor">
          <div className="manual-tag-input-shell task-tag-input-shell">
            <input
              autoFocus
              className="manual-tag-input"
              disabled={isBusy}
              onBlur={() => {
                commitTag(tagInput);
                setIsComposerOpen(false);
              }}
              onChange={handleInputChange}
              onKeyDown={handleInputKeyDown}
              placeholder="Type a tag and press Enter"
              type="text"
              value={tagInput}
            />
          </div>
          {suggestions.length ? (
            <div className="task-tag-autocomplete">
              <div className="task-tag-suggestions">
                {suggestions.map((tag) => (
                  <button
                    className="task-tag-suggestion"
                    disabled={isBusy}
                    key={tag}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => commitTag(tag)}
                    type="button"
                  >
                    {tag.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
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

  const previewLabel = task.source_snippet ? "Original email:" : "Email:";

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
          <span>{previewLabel}</span> {preview}
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

function TaskEditForm({
  task,
  availableTags,
  editState,
  onCancel,
  onSave,
}) {
  const [draft, setDraft] = useState(() => createTaskEditDraft(task));
  const [tagInput, setTagInput] = useState("");
  const suggestions = useMemo(
    () => buildTagSuggestions(availableTags, draft.tags, tagInput),
    [availableTags, draft.tags, tagInput]
  );

  useEffect(() => {
    setDraft(createTaskEditDraft(task));
    setTagInput("");
  }, [task]);

  function updateDraft(field, value) {
    setDraft((current) => ({
      ...current,
      [field]: value,
    }));
  }

  function commitTag(rawValue) {
    const normalized = normalizeManualTag(rawValue);
    if (!normalized) {
      setTagInput("");
      return;
    }
    setDraft((current) => ({
      ...current,
      tags: dedupeManualTags([...current.tags, normalized]),
    }));
    setTagInput("");
  }

  function removeTag(tagToRemove) {
    setDraft((current) => ({
      ...current,
      tags: current.tags.filter((tag) => tag !== tagToRemove),
    }));
  }

  function handleTagInputChange(event) {
    const nextValue = event.target.value;
    const segments = nextValue.split(",");
    if (segments.length > 1) {
      const completedTags = dedupeManualTags(segments.slice(0, -1));
      setDraft((current) => ({
        ...current,
        tags: dedupeManualTags([...current.tags, ...completedTags]),
      }));
      setTagInput(segments[segments.length - 1]);
      return;
    }
    setTagInput(nextValue);
  }

  function handleTagInputKeyDown(event) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commitTag(tagInput);
      return;
    }
    if (event.key === "Backspace" && !tagInput && draft.tags.length) {
      event.preventDefault();
      removeTag(draft.tags[draft.tags.length - 1]);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    await onSave(task.canonical_task_id, {
      title: draft.title,
      description: draft.description,
      deadlineAt: draft.deadlineAt || null,
      priorityTier: draft.priorityTier,
      status: draft.status,
      tags: draft.tags,
    });
  }

  return (
    <form className="task-edit-form" onSubmit={handleSubmit}>
      <div className="task-edit-grid">
        <label className="field-group">
          <span>Title</span>
          <input
            className="auth-input"
            disabled={editState?.isSaving}
            onChange={(event) => updateDraft("title", event.target.value)}
            type="text"
            value={draft.title}
          />
        </label>
        <label className="field-group">
          <span>Priority tier</span>
          <select
            className="auth-input"
            disabled={editState?.isSaving}
            onChange={(event) => updateDraft("priorityTier", event.target.value)}
            value={draft.priorityTier}
          >
            {PRIORITY_TIERS.map((priorityTier) => (
              <option key={priorityTier} value={priorityTier}>
                {formatPriorityTierLabel(priorityTier)}
              </option>
            ))}
          </select>
        </label>
        <label className="field-group">
          <span>Deadline</span>
          <input
            className="auth-input"
            disabled={editState?.isSaving}
            onChange={(event) => updateDraft("deadlineAt", event.target.value)}
            type="datetime-local"
            value={draft.deadlineAt}
          />
        </label>
        <label className="field-group">
          <span>Status</span>
          <select
            className="auth-input"
            disabled={editState?.isSaving}
            onChange={(event) => updateDraft("status", event.target.value)}
            value={draft.status}
          >
            {TASK_STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {status === "COMPLETED" ? "Completed" : "Open"}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="field-group">
        <span>Description</span>
        <textarea
          className="auth-input auth-textarea task-edit-textarea"
          disabled={editState?.isSaving}
          onChange={(event) => updateDraft("description", event.target.value)}
          rows={4}
          value={draft.description}
        />
      </label>
      <label className="field-group">
        <span>Tags</span>
        <div className="manual-tag-field">
          <div className="manual-tag-input-shell">
            {draft.tags.map((tag) => (
              <span className="manual-tag-chip" key={tag}>
                {tag.replace(/_/g, " ")}
                <button
                  aria-label={`Remove ${tag}`}
                  className="manual-tag-remove"
                  disabled={editState?.isSaving}
                  onClick={() => removeTag(tag)}
                  type="button"
                >
                  ×
                </button>
              </span>
            ))}
            <input
              className="manual-tag-input"
              disabled={editState?.isSaving}
              onBlur={() => commitTag(tagInput)}
              onChange={handleTagInputChange}
              onKeyDown={handleTagInputKeyDown}
              placeholder={draft.tags.length ? "Add another tag" : "Type a tag and press Enter"}
              type="text"
              value={tagInput}
            />
          </div>
          {suggestions.length ? (
            <div className="manual-tag-autocomplete task-edit-tag-autocomplete">
              <div className="manual-tag-suggestions">
                {suggestions.map((tag) => (
                  <button
                    className="manual-tag-suggestion"
                    disabled={editState?.isSaving}
                    key={tag}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => commitTag(tag)}
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
      {editState?.error ? <p className="error-text task-edit-message">{editState.error}</p> : null}
      <div className="task-edit-actions">
        <button className="auth-button" disabled={editState?.isSaving} type="submit">
          {editState?.isSaving ? "Saving..." : "Save changes"}
        </button>
        <button
          className="secondary-button"
          disabled={editState?.isSaving}
          onClick={onCancel}
          type="button"
        >
          Cancel
        </button>
      </div>
    </form>
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
  const isCompleted = getTaskWorkflowStatus(task) === "COMPLETED";

  return (
    <>
      {feedbackLabel ? (
        <p className="task-feedback-note">Updated: {feedbackLabel}</p>
      ) : null}
      {isCompleted ? (
        <p className="task-feedback-note">This task is completed. Use Edit if you want to reopen it.</p>
      ) : null}
      {!isCompleted ? (
        <>
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
      ) : null}
    </>
  );
}

function TaskCard({
  task,
  feedbackState,
  isBusy,
  onFeedback,
  onChangeTags,
  onOpenEdit,
  onCloseEdit,
  onSaveEdit,
  isEditing,
  editState,
  availableTags,
  index = 0,
}) {
  const taskStatus = getTaskWorkflowStatus(task);
  return (
    <article className={`task-card task-card-queue task-card-tier-${task.priority_tier.toLowerCase()}`}>
      <div className="task-card-top task-card-top-queue">
        <div className="task-queue-heading">
          <span className="task-queue-index">{String(index + 1).padStart(2, "0")}</span>
          <div>
            <span className={`task-tier task-tier-${task.priority_tier.toLowerCase()}`}>
              {formatPriorityTierLabel(task.priority_tier)}
            </span>
            {taskStatus === "COMPLETED" ? <span className="task-status-badge">Completed</span> : null}
            <h3 className="task-title">{cleanPreviewText(task.task_title) || "Untitled task"}</h3>
            <p className="task-queue-window">{formatActionWindow(task.action_window)}</p>
          </div>
        </div>
        <div className="task-queue-controls">
          {formatDeadline(task.deadline_hours) ? (
            <span className="task-queue-deadline">{formatDeadline(task.deadline_hours)}</span>
          ) : null}
          <button
            className="secondary-button task-edit-toggle"
            disabled={isBusy}
            onClick={() => (isEditing ? onCloseEdit(task.canonical_task_id) : onOpenEdit(task.canonical_task_id))}
            type="button"
          >
            {isEditing ? "Close edit" : "Edit"}
          </button>
        </div>
      </div>
      <div className="task-summary-block">
        <p className="task-summary-label">Summary</p>
        <p className="task-queue-summary">
          {buildQueueSummary(task)}
        </p>
      </div>
      <TaskTags
        availableTags={availableTags}
        isBusy={isBusy}
        onChangeTags={onChangeTags}
        task={task}
      />
      <div className="task-meta task-meta-compact">
        <span>Confidence {Math.round((task.confidence ?? 0) * 100)}%</span>
        <span>{task.platforms_seen?.join(", ") || "email"}</span>
      </div>
      <div className="task-card-details">
        <p className="task-summary-label">Source email</p>
        <TaskSource compact task={task} />
        {isEditing ? (
          <TaskEditForm
            availableTags={availableTags}
            editState={editState}
            onCancel={() => onCloseEdit(task.canonical_task_id)}
            onSave={onSaveEdit}
            task={task}
          />
        ) : null}
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
  onChangeTags,
  onOpenEdit,
  onCloseEdit,
  onSaveEdit,
  isEditing,
  editState,
  availableTags,
  index,
}) {
  return (
    <TaskCard
      feedbackState={feedbackState}
      index={index}
      isBusy={isBusy}
      onFeedback={onFeedback}
      onChangeTags={onChangeTags}
      onOpenEdit={onOpenEdit}
      onCloseEdit={onCloseEdit}
      onSaveEdit={onSaveEdit}
      isEditing={isEditing}
      editState={editState}
      availableTags={availableTags}
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
  const [taskEditStates, setTaskEditStates] = useState({});
  const [editingTaskId, setEditingTaskId] = useState(null);
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
    tasks
      .filter((task) => getTaskWorkflowStatus(task) === "OPEN")
      .forEach((task) => {
      counts[task.priority_tier] = (counts[task.priority_tier] || 0) + 1;
      });
    return counts;
  }, [tasks]);

  const hasPendingTaskTagUpdates = Object.keys(taskTagUpdateStates).length > 0;
  const hasTaskEditInFlight = Object.values(taskEditStates).some((state) => state?.isSaving);
  const isLiveRefreshPaused =
    isSyncing ||
    isProcessingFeedbackQueue ||
    feedbackQueue.length > 0 ||
    isCreatingManualTask ||
    editingTaskId !== null ||
    hasPendingTaskTagUpdates ||
    hasTaskEditInFlight;

  useEffect(() => {
    if (!user?.userId) {
      return;
    }
    writeDashboardCache(user.userId, user, tasks, pipelineProfile);
  }, [pipelineProfile, tasks, user]);

  useEffect(() => {
    let isCancelled = false;
    let refreshInFlight = false;

    async function refreshDashboardQuietly() {
      if (document.hidden || refreshInFlight || isLiveRefreshPaused) {
        return;
      }

      refreshInFlight = true;
      try {
        const dashboard = await fetchDashboardBootstrap();
        if (isCancelled) {
          return;
        }
        setUser(dashboard.user);
        setTasks(dashboard.items ?? []);
        setPipelineProfile(dashboard.profile ?? null);
        setAvailableTags(dashboard.availableTags ?? []);
      } catch {
        // Keep the current UI steady if the background refresh misses a cycle.
      } finally {
        refreshInFlight = false;
      }
    }

    const intervalId = window.setInterval(refreshDashboardQuietly, LIVE_REFRESH_INTERVAL_MS);

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
    };
  }, [isLiveRefreshPaused]);

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

  function openTaskEditor(canonicalTaskId) {
    setEditingTaskId(canonicalTaskId);
    setTaskEditStates((current) => ({
      ...current,
      [canonicalTaskId]: { isSaving: false, error: "" },
    }));
  }

  function closeTaskEditor(canonicalTaskId) {
    setEditingTaskId((current) => (current === canonicalTaskId ? null : current));
    setTaskEditStates((current) => {
      const updated = { ...current };
      delete updated[canonicalTaskId];
      return updated;
    });
  }

  async function handleSyncTasks() {
    setIsSyncing(true);
    setTaskError("");
    setTaskStatus("");
    const previousTasks = tasks;
    try {
      const result = await syncPrioritizedTasks();
      setTasks(result.items ?? []);
      setAvailableTags(result.availableTags ?? []);
      setTaskFeedbackStates({});
      setTaskTagUpdateStates({});
      setTaskEditStates({});
      setEditingTaskId(null);
      const latestProfile = await fetchPipelineProfile();
      setPipelineProfile(latestProfile);
      setTaskStatus(buildSyncStatus(result, previousTasks));
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

  async function handleTaskTagChange(canonicalTaskId, nextTags, changeMeta = null) {
    const selectedTask = tasks.find((task) => task.canonical_task_id === canonicalTaskId);
    if (!selectedTask) {
      return;
    }

    const sanitizedTags = dedupeManualTags(nextTags);
    const currentTags = getVisibleTaskTags(selectedTask);
    if (JSON.stringify(sanitizedTags) === JSON.stringify(currentTags)) {
      return;
    }
    setTaskError("");
    setTaskStatus("Saving your tag changes.");
    setTaskTagUpdateStates((current) => ({
      ...current,
      [canonicalTaskId]: changeMeta ?? true,
    }));
    applyLocalTagUpdate(canonicalTaskId, sanitizedTags);

    try {
      const result = await updateTaskTags(canonicalTaskId, sanitizedTags);
      updateTaskListFromResponse(result);
      if (changeMeta?.type === "remove" && changeMeta?.tag) {
        setTaskStatus(`Removed tag "${changeMeta.tag.replace(/_/g, " ")}".`);
      } else if (changeMeta?.type === "add" && changeMeta?.tag) {
        setTaskStatus(`Added tag "${changeMeta.tag.replace(/_/g, " ")}".`);
      } else {
        setTaskStatus("Updated task tags.");
      }
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

  async function handleTaskEditSave(canonicalTaskId, payload) {
    setTaskError("");
    setTaskStatus("");
    setTaskEditStates((current) => ({
      ...current,
      [canonicalTaskId]: { isSaving: true, error: "" },
    }));

    try {
      const result = await updatePrioritizedTask(canonicalTaskId, payload);
      updateTaskListFromResponse(result);
      if (result.profile) {
        setPipelineProfile(result.profile);
      }
      setTaskStatus("Task details updated.");
      closeTaskEditor(canonicalTaskId);
    } catch (error) {
      setTaskError(error.message);
      setTaskEditStates((current) => ({
        ...current,
        [canonicalTaskId]: { isSaving: false, error: error.message },
      }));
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

  const filteredAvailableTags = useMemo(
    () => buildTagSuggestions(availableTags, manualTask.tags, manualTask.tagInput, manualTask.tagInput ? 8 : 12),
    [availableTags, manualTask.tagInput, manualTask.tags]
  );

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
            <p className="summary-value">{user?.username ?? "Refreshing your account..."}</p>
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
              <span>{tasks.filter((task) => getTaskWorkflowStatus(task) === "OPEN").length} active</span>
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
          <Link className="secondary-button home-link" to="/preferences">
            Open preferences
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
                  availableTags={availableTags}
                  editState={taskEditStates[task.canonical_task_id]}
                  feedbackState={taskFeedbackStates[task.canonical_task_id]}
                  index={index}
                  isBusy={Boolean(taskTagUpdateStates[task.canonical_task_id] || taskEditStates[task.canonical_task_id]?.isSaving)}
                  isEditing={editingTaskId === task.canonical_task_id}
                  key={task.canonical_task_id}
                  onCloseEdit={closeTaskEditor}
                  onFeedback={handleFeedback}
                  onChangeTags={handleTaskTagChange}
                  onOpenEdit={openTaskEditor}
                  onSaveEdit={handleTaskEditSave}
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
