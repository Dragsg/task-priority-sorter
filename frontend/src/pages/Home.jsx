import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  createManualTask,
  fetchDashboardBootstrap,
  fetchPipelineProfile,
  fetchPipelineRecomputeStatus,
  fetchPrioritizedTasks,
  getStoredUser,
  getStoredUserId,
  LIVE_REFRESH_INTERVAL_MS,
  promoteFalseNegativeEmail,
  schedulePrioritizedTaskSync,
  submitTaskFeedback,
  updatePrioritizedTask,
  updateTaskTags,
} from "../api";
import { readDashboardCache, writeDashboardCache } from "../dashboardCache";
import PageNav from "../components/PageNav";

const TASK_TYPE_OPTIONS = [
  { value: "submission", label: "Submission" },
  { value: "meeting", label: "Meeting" },
  { value: "reading", label: "Reading" },
  { value: "admin", label: "Admin" },
  { value: "social", label: "Social" },
];
const PRIORITY_TIERS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const TASK_STATUS_OPTIONS = ["OPEN", "COMPLETED"];
const RECOMPUTE_STATUS_POLL_INTERVAL_MS = 2500;

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
  const currentItems = filterVisibleTaskItems(Array.isArray(result.items) ? result.items : []);
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

function buildAsyncSyncCompletionStatus(nextItems = [], previousTasks = []) {
  const previousIds = new Set(
    (previousTasks || [])
      .map((task) => task?.canonical_task_id)
      .filter(Boolean)
  );
  const visibleItems = filterVisibleTaskItems(nextItems);
  const addedCount = visibleItems.filter(
    (task) => task?.canonical_task_id && !previousIds.has(task.canonical_task_id)
  ).length;

  if (addedCount > 0) {
    return `Added ${addedCount} new prioritized task card${addedCount === 1 ? "" : "s"} to your queue.`;
  }
  if (!visibleItems.length) {
    return "Inbox check finished, but there are still no visible task cards in your queue.";
  }
  return "Task priorities refreshed in the background.";
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

function feedbackActionUpdatesProfile(action) {
  return action === "ACCEPT" || action === "REJECT";
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

function formatPlatformLabel(value) {
  if (!value) {
    return null;
  }

  const normalized = String(value).trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  if (normalized === "gmail") {
    return "Gmail";
  }
  if (normalized === "outlook") {
    return "Outlook";
  }
  if (normalized === "manual") {
    return "Manual";
  }
  return `${normalized.charAt(0).toUpperCase()}${normalized.slice(1)}`;
}

function getNormalizedTaskStatus(task) {
  return String(task?.status || "pending_review").toLowerCase();
}

function isManualTask(task) {
  if (String(task?.origin || "").toLowerCase() === "manual") {
    return true;
  }

  if (!Array.isArray(task?.platforms_seen)) {
    return false;
  }

  return task.platforms_seen.some((platform) => String(platform).toLowerCase() === "manual");
}

function filterVisibleTaskItems(items) {
  if (!Array.isArray(items)) {
    return [];
  }

  return items.filter((task) => {
    const status = getNormalizedTaskStatus(task);
    return status === "pending_review" && !isManualTask(task);
  });
}

function getTaskWorkflowStatus(task) {
  return getNormalizedTaskStatus(task) === "completed" ? "COMPLETED" : "OPEN";
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
    "Check the source email details below for more context."
  );
}

function buildFalseNegativePreview(item) {
  return (
    truncateText(item.preview, 220) ||
    truncateText(item.subject, 140) ||
    "No email preview was available for this message."
  );
}

function getFalseNegativeKey(item) {
  return `${String(item?.platform || "email").toLowerCase()}:${item?.sourceId || ""}`;
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
  const propTags = useMemo(() => getVisibleTaskTags(task), [task.canonical_task_id, task.tags]);
  const [displayTags, setDisplayTags] = useState(propTags);
  const [tagInput, setTagInput] = useState("");
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const tagBlockRef = useRef(null);
  const suggestions = useMemo(
    () => buildTagSuggestions(availableTags, displayTags, tagInput),
    [availableTags, displayTags, tagInput]
  );

  useEffect(() => {
    setDisplayTags(propTags);
  }, [propTags]);

  function applyTagChange(nextTags, changeMeta = null) {
    const sanitizedTags = dedupeManualTags(nextTags);
    setDisplayTags(sanitizedTags);
    onChangeTags?.(task.canonical_task_id, sanitizedTags, changeMeta);
  }

  function commitTag(rawValue, { closeComposer = true } = {}) {
    const normalized = normalizeManualTag(rawValue);
    if (!normalized) {
      setTagInput("");
      if (closeComposer) {
        setIsComposerOpen(false);
      }
      return;
    }

    const nextTags = dedupeManualTags([...displayTags, normalized]);
    setTagInput("");
    if (closeComposer) {
      setIsComposerOpen(false);
    }
    if (nextTags.length === displayTags.length) {
      return;
    }
    applyTagChange(nextTags, {
      type: "add",
      tag: normalized,
    });
  }

  function removeTag(tagToRemove) {
    applyTagChange(
      displayTags.filter((tag) => tag !== tagToRemove),
      { type: "remove", tag: tagToRemove }
    );
  }

  function handleInputChange(event) {
    const nextValue = event.target.value;
    const segments = nextValue.split(",");
    if (segments.length > 1) {
      const completedTags = dedupeManualTags(segments.slice(0, -1));
      const nextTags = dedupeManualTags([...displayTags, ...completedTags]);
      const lastAdded = completedTags[completedTags.length - 1];
      setTagInput(segments[segments.length - 1]);
      if (nextTags.length !== displayTags.length) {
        applyTagChange(nextTags, {
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

    if (event.key === "Escape") {
      event.preventDefault();
      setTagInput("");
      setIsComposerOpen(false);
      return;
    }

    if (event.key === "Backspace" && !tagInput && displayTags.length) {
      event.preventDefault();
      removeTag(displayTags[displayTags.length - 1]);
    }
  }

  function handleInputBlur(event) {
    const nextFocusedElement = event.relatedTarget;
    if (nextFocusedElement && tagBlockRef.current?.contains(nextFocusedElement)) {
      return;
    }
    commitTag(tagInput);
  }

  function handleComposerToggle() {
    if (isComposerOpen) {
      commitTag(tagInput);
      return;
    }
    setIsComposerOpen(true);
  }

  if (!displayTags.length && !onChangeTags) {
    return null;
  }

  return (
    <div className="task-tag-block" ref={tagBlockRef}>
      <div className="task-tag-header">
        <span className="task-tag-label">Tags</span>
      </div>
      <div className="task-tag-row">
        {displayTags.length ? (
          <div className="task-tag-list">
            {displayTags.map((tag) => (
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
            onClick={handleComposerToggle}
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
              onBlur={handleInputBlur}
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

function TaskEditDialog({
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

  useEffect(() => {
    function handleKeyDown(event) {
      if (event.key === "Escape" && !editState?.isSaving) {
        onCancel();
      }
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [editState?.isSaving, onCancel]);

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
    <div
      aria-modal="true"
      className="kanban-modal-backdrop"
      onClick={() => {
        if (!editState?.isSaving) {
          onCancel();
        }
      }}
      role="dialog"
    >
      <div className="kanban-modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="kanban-modal-header">
          <div>
            <p className="auth-eyebrow">Edit task</p>
            <h2 className="kanban-modal-title">
              {cleanPreviewText(task.task_title) || "Untitled task"}
            </h2>
            <p className="kanban-modal-copy">
              Update the details here without losing your place in the dashboard.
            </p>
          </div>
          <button
            aria-label="Close edit dialog"
            className="kanban-modal-close"
            disabled={editState?.isSaving}
            onClick={onCancel}
            type="button"
          >
            ×
          </button>
        </div>

        <form className="kanban-edit-panel" onSubmit={handleSubmit}>
          <div className="kanban-edit-grid">
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
              className="auth-input auth-textarea kanban-edit-textarea"
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
                <div className="manual-tag-autocomplete kanban-tag-autocomplete">
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
          <div className="kanban-edit-actions">
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
      </div>
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
  isEditing,
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
      <div className="task-card-details">
        <p className="task-summary-label">Source email</p>
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
  onChangeTags,
  onOpenEdit,
  onCloseEdit,
  isEditing,
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
      isEditing={isEditing}
      availableTags={availableTags}
      task={task}
    />
  );
}

function FalseNegativeCard({ item, index, isAdding = false, onAddToQueue }) {
  const subject = cleanPreviewText(item.subject) || "(No subject)";
  const sender = cleanPreviewText(item.sender || item.senderEmail);
  const preview = buildFalseNegativePreview(item);
  const received = formatSourceTimestamp(item.receivedAt);
  const platformLabel = formatPlatformLabel(item.platform);

  return (
    <article className="false-negative-card">
      <div className="false-negative-top">
        <div className="false-negative-heading">
          <span className="task-queue-index">{String(index + 1).padStart(2, "0")}</span>
          <div className="false-negative-copy">
            {platformLabel ? <span className="false-negative-platform">{platformLabel}</span> : null}
            <h3 className="task-title">{subject}</h3>
          </div>
        </div>
        <div className="false-negative-actions">
          {received ? <span className="false-negative-time">{received}</span> : null}
          <button
            className="secondary-button false-negative-button"
            disabled={isAdding}
            onClick={() => onAddToQueue?.(item)}
            type="button"
          >
            {isAdding ? "Adding..." : "Add to queue"}
          </button>
        </div>
      </div>
      {sender ? <p className="false-negative-meta">From {sender}</p> : null}
      <p className="false-negative-preview">{preview}</p>
    </article>
  );
}

export default function Home() {
  const navigate = useNavigate();
  const cachedUserId = getStoredUserId();
  const cachedDashboard = readDashboardCache(cachedUserId);
  const [user, setUser] = useState(() => cachedDashboard?.user ?? getStoredUser());
  const [tasks, setTasks] = useState(() =>
    filterVisibleTaskItems(cachedDashboard?.allTasks ?? cachedDashboard?.tasks ?? [])
  );
  const [allTaskItems, setAllTaskItems] = useState(() =>
    Array.isArray(cachedDashboard?.allTasks) ? cachedDashboard.allTasks : null
  );
  const [falseNegativeItems, setFalseNegativeItems] = useState(() => cachedDashboard?.falseNegativeItems ?? []);
  const [pipelineProfile, setPipelineProfile] = useState(() => cachedDashboard?.profile ?? null);
  const [availableTags, setAvailableTags] = useState(() => cachedDashboard?.availableTags ?? []);
  const [taskFeedbackStates, setTaskFeedbackStates] = useState({});
  const [taskTagUpdateStates, setTaskTagUpdateStates] = useState({});
  const [taskEditStates, setTaskEditStates] = useState({});
  const [editingTaskId, setEditingTaskId] = useState(null);
  const [taskError, setTaskError] = useState("");
  const [taskStatus, setTaskStatus] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);
  const [recomputeStatus, setRecomputeStatus] = useState(null);
  const [feedbackQueue, setFeedbackQueue] = useState([]);
  const [isProcessingFeedbackQueue, setIsProcessingFeedbackQueue] = useState(false);
  const [isFalseNegativePanelOpen, setIsFalseNegativePanelOpen] = useState(false);
  const [falseNegativePromotionStates, setFalseNegativePromotionStates] = useState({});
  const [isManualFormOpen, setIsManualFormOpen] = useState(false);
  const [isCreatingManualTask, setIsCreatingManualTask] = useState(false);
  const [isManualTagInputFocused, setIsManualTagInputFocused] = useState(false);
  const taskMutationVersionRef = useRef(0);
  const hasAttemptedAutoSyncRef = useRef(false);
  const syncBaselineTasksRef = useRef([]);
  const isAwaitingSyncCompletionRef = useRef(false);
  const [manualTask, setManualTask] = useState({
    title: "",
    description: "",
    taskType: "admin",
    deadlineAt: "",
    entityName: "",
    tags: [],
    tagInput: "",
  });

  function bumpTaskMutationVersion() {
    taskMutationVersionRef.current += 1;
  }

  function setVisibleTasks(items) {
    setTasks(filterVisibleTaskItems(items));
  }

  function applyDashboardSnapshot(dashboard) {
    setAllTaskItems(dashboard.items ?? []);
    setUser(dashboard.user);
    setVisibleTasks(dashboard.items ?? []);
    setFalseNegativeItems(dashboard.falseNegativeItems ?? []);
    setPipelineProfile(dashboard.profile ?? null);
    setAvailableTags(dashboard.availableTags ?? []);
  }

  useEffect(() => {
    let isCancelled = false;

    async function loadDashboard() {
      const currentUserId = getStoredUserId();
      const cached = readDashboardCache(currentUserId);
      if (cached) {
        const cachedItems = cached.allTasks ?? cached.tasks ?? [];
        if (cached.user) {
          setUser(cached.user);
        }
        setAllTaskItems(cached.allTasks ?? null);
        setVisibleTasks(cachedItems);
        setFalseNegativeItems(cached.falseNegativeItems ?? []);
        setPipelineProfile(cached.profile ?? null);
        setAvailableTags(cached.availableTags ?? []);
      }

      try {
        const requestVersion = taskMutationVersionRef.current;
        const [dashboard, latestRecomputeStatus] = await Promise.all([
          fetchDashboardBootstrap(),
          fetchPipelineRecomputeStatus(),
        ]);
        if (isCancelled || requestVersion !== taskMutationVersionRef.current) {
          return;
        }
        applyDashboardSnapshot(dashboard);
        setRecomputeStatus(latestRecomputeStatus);
        const backgroundSyncActive = Boolean(
          latestRecomputeStatus?.running || latestRecomputeStatus?.pending
        );
        setIsSyncing(backgroundSyncActive);
        if (backgroundSyncActive) {
          isAwaitingSyncCompletionRef.current = true;
          syncBaselineTasksRef.current = filterVisibleTaskItems(dashboard.items ?? []);
          return;
        }

        const visibleItems = filterVisibleTaskItems(dashboard.items ?? []);
        if (!visibleItems.length && !hasAttemptedAutoSyncRef.current) {
          hasAttemptedAutoSyncRef.current = true;
          syncBaselineTasksRef.current = visibleItems;
          isAwaitingSyncCompletionRef.current = true;
          setIsSyncing(true);
          setTaskStatus("Checking your inbox and rebuilding priorities in the background.");
          try {
            const scheduled = await schedulePrioritizedTaskSync();
            if (isCancelled || requestVersion !== taskMutationVersionRef.current) {
              return;
            }
            setRecomputeStatus(scheduled.status ?? null);
          } catch (error) {
            if (isCancelled || requestVersion !== taskMutationVersionRef.current) {
              return;
            }
            isAwaitingSyncCompletionRef.current = false;
            setIsSyncing(false);
            setTaskError(error.message);
          }
        }
      } catch {
        if (isCancelled) {
          return;
        }
        if (cached) {
          setTaskError("Using your last saved dashboard while fresh data is temporarily unavailable.");
          return;
        }
        clearStoredToken();
        navigate("/", { replace: true });
      }
    }

    loadDashboard();

    return () => {
      isCancelled = true;
    };
  }, [navigate]);

  const priorityCounts = useMemo(() => {
    const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    tasks.forEach((task) => {
      const tier = String(task.priority_tier || "LOW").toUpperCase();
      counts[tier] = (counts[tier] || 0) + 1;
    });
    return counts;
  }, [tasks]);
  const dueSoonCount = useMemo(
    () =>
      tasks.filter(
        (task) =>
          typeof task.deadline_hours === "number" &&
          task.deadline_hours >= 0 &&
          task.deadline_hours <= 24
      ).length,
    [tasks]
  );
  const hasPendingTaskTagUpdates = Object.keys(taskTagUpdateStates).length > 0;
  const hasTaskEditInFlight = Object.values(taskEditStates).some((state) => state?.isSaving);
  const isFalseNegativePromotionInFlight = Object.values(falseNegativePromotionStates).some(Boolean);
  const isLiveRefreshPaused =
    isSyncing ||
    isProcessingFeedbackQueue ||
    feedbackQueue.length > 0 ||
    isFalseNegativePromotionInFlight ||
    isCreatingManualTask ||
    editingTaskId !== null ||
    hasPendingTaskTagUpdates ||
    hasTaskEditInFlight;

  useEffect(() => {
    if (!user?.userId) {
      return;
    }
    writeDashboardCache(user.userId, {
      user,
      tasks,
      allTasks: allTaskItems ?? undefined,
      falseNegativeItems,
      profile: pipelineProfile,
      availableTags,
    });
  }, [allTaskItems, availableTags, falseNegativeItems, pipelineProfile, tasks, user]);

  useEffect(() => {
    let isCancelled = false;
    let refreshInFlight = false;

    async function refreshDashboardQuietly() {
      if (document.hidden || refreshInFlight || isLiveRefreshPaused) {
        return;
      }

      refreshInFlight = true;
      try {
        const requestVersion = taskMutationVersionRef.current;
        const dashboard = await fetchDashboardBootstrap();
        if (isCancelled || requestVersion !== taskMutationVersionRef.current) {
          return;
        }
        applyDashboardSnapshot(dashboard);
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
    if (!isSyncing && !recomputeStatus?.running && !recomputeStatus?.pending) {
      return undefined;
    }

    let pollInFlight = false;

    async function pollRecomputeStatus() {
      if (pollInFlight) {
        return;
      }

      pollInFlight = true;
      try {
        const status = await fetchPipelineRecomputeStatus();
        if (isCancelled) {
          return;
        }
        setRecomputeStatus(status);
        const backgroundSyncActive = Boolean(status?.running || status?.pending);
        setIsSyncing(backgroundSyncActive);
        if (backgroundSyncActive || !isAwaitingSyncCompletionRef.current) {
          return;
        }

        const dashboard = await fetchDashboardBootstrap();
        if (isCancelled) {
          return;
        }
        applyDashboardSnapshot(dashboard);
        setTaskStatus(buildAsyncSyncCompletionStatus(dashboard.items ?? [], syncBaselineTasksRef.current));
        isAwaitingSyncCompletionRef.current = false;
      } catch {
        // Keep the current UI steady if background recompute polling misses a cycle.
      } finally {
        pollInFlight = false;
      }
    }

    let isCancelled = false;
    const intervalId = window.setInterval(pollRecomputeStatus, RECOMPUTE_STATUS_POLL_INTERVAL_MS);
    pollRecomputeStatus();

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
    };
  }, [isSyncing, recomputeStatus]);

  useEffect(() => {
    if (!isFalseNegativePanelOpen) {
      return undefined;
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setIsFalseNegativePanelOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isFalseNegativePanelOpen]);

  useEffect(() => {
    if (isProcessingFeedbackQueue || feedbackQueue.length === 0) {
      return;
    }

    const next = feedbackQueue[0];
    let cancelled = false;

    async function flushFeedback() {
      setIsProcessingFeedbackQueue(true);
      try {
        const shouldRefreshProfile = feedbackActionUpdatesProfile(next.action);
        const result = await submitTaskFeedback(next.canonicalTaskId, {
          action: next.action,
          direction: next.direction,
        });
        if (cancelled) {
          return;
        }
        if (result.profile) {
          setPipelineProfile(result.profile);
        } else if (shouldRefreshProfile) {
          const latestProfile = await fetchPipelineProfile();
          if (cancelled) {
            return;
          }
          setPipelineProfile(latestProfile);
        }
        if (result.items) {
          updateTaskListFromResponse(result);
        }
        setTaskStatus(
          next.action === "WRONG_PRIORITY"
            ? "Priority updated."
            : next.action === "ACCEPT"
              ? "Task accepted and moved to Kanban. Your profile was updated."
              : next.action === "REJECT"
                ? "Task rejected and removed from review. Your profile was updated."
                : "Feedback saved."
        );
      } catch (error) {
        if (cancelled) {
          return;
        }
        setTaskError(error.message);
        try {
          const taskPayload = await fetchPrioritizedTasks();
          if (cancelled) {
            return;
          }
          updateTaskListFromResponse(taskPayload);
          if (feedbackActionUpdatesProfile(next.action)) {
            const profilePayload = await fetchPipelineProfile();
            if (cancelled) {
              return;
            }
            setPipelineProfile(profilePayload);
          }
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
      setAllTaskItems(result.items);
      setVisibleTasks(result.items);
    }
    if (Array.isArray(result?.falseNegativeItems)) {
      setFalseNegativeItems(result.falseNegativeItems);
    }
    if (result?.profile) {
      setPipelineProfile(result.profile);
    }
    if (result?.availableTags) {
      setAvailableTags(result.availableTags);
    }
  }

  async function handlePromoteFalseNegative(item) {
    const itemKey = getFalseNegativeKey(item);
    if (!item?.sourceId) {
      return;
    }

    let removedIndex = -1;
    bumpTaskMutationVersion();
    setTaskError("");
    setTaskStatus("");
    setFalseNegativePromotionStates((current) => ({
      ...current,
      [itemKey]: true,
    }));
    setFalseNegativeItems((current) => {
      removedIndex = current.findIndex((candidate) => getFalseNegativeKey(candidate) === itemKey);
      if (removedIndex === -1) {
        return current;
      }
      return current.filter((candidate) => getFalseNegativeKey(candidate) !== itemKey);
    });

    try {
      const result = await promoteFalseNegativeEmail({
        sourceId: item.sourceId,
        platform: item.platform,
      });
      updateTaskListFromResponse(result);
      setTaskStatus("Email added to the main queue.");
    } catch (error) {
      setFalseNegativeItems((current) => {
        if (current.some((candidate) => getFalseNegativeKey(candidate) === itemKey)) {
          return current;
        }
        const next = [...current];
        const insertIndex = removedIndex >= 0 ? Math.min(removedIndex, next.length) : next.length;
        next.splice(insertIndex, 0, item);
        return next;
      });
      setTaskError(error.message);
    } finally {
      setFalseNegativePromotionStates((current) => {
        const updated = { ...current };
        delete updated[itemKey];
        return updated;
      });
    }
  }

  function updateTaskCollections(mutateItems) {
    setTasks((current) => filterVisibleTaskItems(mutateItems(current)));
    setAllTaskItems((current) => (Array.isArray(current) ? mutateItems(current) : current));
  }

  function applyLocalFeedback(canonicalTaskId, action, direction) {
    updateTaskCollections((current) => {
      const selectedTask = current.find((task) => task.canonical_task_id === canonicalTaskId);
      if (!selectedTask) {
        return current;
      }

      if (action === "ACCEPT" || action === "REJECT") {
        if (action === "REJECT") {
          return current.filter((task) => task.canonical_task_id !== canonicalTaskId);
        }
        return current.map((task) =>
          task.canonical_task_id === canonicalTaskId
            ? { ...task, status: "accepted" }
            : task
        );
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
    updateTaskCollections((current) =>
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
    bumpTaskMutationVersion();
    setIsSyncing(true);
    setTaskError("");
    setTaskStatus("Refreshing task priorities in the background.");
    syncBaselineTasksRef.current = tasks;
    isAwaitingSyncCompletionRef.current = true;
    try {
      const result = await schedulePrioritizedTaskSync();
      setRecomputeStatus(result.status ?? null);
      setTaskFeedbackStates({});
      setTaskTagUpdateStates({});
      setTaskEditStates({});
      setEditingTaskId(null);
    } catch (error) {
      isAwaitingSyncCompletionRef.current = false;
      setIsSyncing(false);
      setTaskError(error.message);
    }
  }

  function handleFeedback(canonicalTaskId, action, direction, currentPriorityTier = null) {
    setTaskError("");
    setTaskFeedbackStates((current) => ({
      ...current,
      [canonicalTaskId]: createFeedbackState(action, direction, currentPriorityTier),
    }));
    bumpTaskMutationVersion();
    applyLocalFeedback(canonicalTaskId, action, direction);
    setTaskStatus(
      action === "WRONG_PRIORITY"
        ? "Updating task priority in the background."
        : action === "ACCEPT"
          ? "Accepting task and updating your profile in the background."
          : action === "REJECT"
            ? "Rejecting task and updating your profile in the background."
            : "Saving feedback in the background."
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
    bumpTaskMutationVersion();
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
        updateTaskListFromResponse(taskPayload);
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
    bumpTaskMutationVersion();
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
    bumpTaskMutationVersion();
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
      setTaskStatus("Manual task added to your Kanban board.");
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
  const activeEditingTask = useMemo(
    () => tasks.find((task) => task.canonical_task_id === editingTaskId) ?? null,
    [editingTaskId, tasks]
  );

  useEffect(() => {
    if (!editingTaskId || activeEditingTask) {
      return;
    }

    setEditingTaskId(null);
    setTaskEditStates((current) => {
      if (!current[editingTaskId]) {
        return current;
      }
      const updated = { ...current };
      delete updated[editingTaskId];
      return updated;
    });
  }, [activeEditingTask, editingTaskId]);

  if (!user) {
    return <main className="simple-shell">Loading your dashboard...</main>;
  }

  return (
    <main className="simple-shell">
      <PageNav />
      <section className="structured-page" aria-label="Dashboard">
        <section className="structured-overview workspace-overview" aria-label="Dashboard overview">
          <article className="structured-overview-item">
            <p className="overview-label">Logged in as</p>
            <p className="overview-value">{user.username}</p>
          </article>
          <article className="structured-overview-item">
            <p className="overview-label">Needs review</p>
            <p className="overview-value">{tasks.length}</p>
          </article>
          <article className="structured-overview-item">
            <p className="overview-label">Critical in queue</p>
            <p className="overview-value">{priorityCounts.CRITICAL}</p>
          </article>
          <article className="structured-overview-item">
            <p className="overview-label">Due within 24h</p>
            <p className="overview-value">{dueSoonCount}</p>
          </article>
        </section>

        <section className="structured-section">
          <div className="structured-section-header">
            <div className="structured-section-copy">
              <h2 className="structured-section-title">Queue</h2>
              <p className="panel-copy">
                Accept a task to move it to Kanban, reject it to clear it, or adjust the order when the ranking feels off.
              </p>
            </div>
            <div className="structured-section-side home-actions home-actions-compact">
              <span className="count-pill">{tasks.length}</span>
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
              <button
                className="secondary-button home-link"
                onClick={() => setIsFalseNegativePanelOpen(true)}
                type="button"
              >
                {`View false negatives (${falseNegativeItems.length})`}
              </button>
              <button
                className="inline-button danger-button"
                disabled={!user}
                onClick={handleLogout}
                type="button"
              >
                Log out
              </button>
            </div>
          </div>

          <div className="structured-section-body">
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
                    Manual tasks go straight to your Kanban board and still update your learned profile.
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

            {tasks.length ? (
              <div className="task-card-list">
                {tasks.map((task, index) => (
                  <QueueCard
                    availableTags={availableTags}
                    feedbackState={taskFeedbackStates[task.canonical_task_id]}
                    index={index}
                    isBusy={Boolean(taskTagUpdateStates[task.canonical_task_id] || taskEditStates[task.canonical_task_id]?.isSaving)}
                    isEditing={editingTaskId === task.canonical_task_id}
                    key={task.canonical_task_id}
                    onCloseEdit={closeTaskEditor}
                    onFeedback={handleFeedback}
                    onChangeTags={handleTaskTagChange}
                    onOpenEdit={openTaskEditor}
                    task={task}
                  />
                ))}
              </div>
            ) : (
              <div className="task-card task-card-empty">
                <p className="summary-value">
                  {isSyncing
                    ? "Your queue is being refreshed in the background."
                    : "There is nothing waiting for review right now."}
                </p>
                <p className="panel-copy">
                  {isSyncing
                    ? "We are checking your inbox and rebuilding task priorities. New task cards will appear here as soon as the refresh finishes."
                    : "Refresh the queue after new emails arrive, or use Connections if you still need to bring an inbox into the app."}
                </p>
              </div>
            )}
          </div>
        </section>
      </section>

      {activeEditingTask ? (
        <TaskEditDialog
          availableTags={availableTags}
          editState={taskEditStates[activeEditingTask.canonical_task_id]}
          onCancel={() => closeTaskEditor(activeEditingTask.canonical_task_id)}
          onSave={handleTaskEditSave}
          task={activeEditingTask}
        />
      ) : null}

      {isFalseNegativePanelOpen ? (
        <div
          aria-label="False negatives"
          aria-modal="true"
          className="modal-backdrop"
          onClick={() => setIsFalseNegativePanelOpen(false)}
          role="dialog"
        >
          <div
            className="false-negative-dialog"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="false-negative-dialog-header">
              <div className="false-negative-dialog-copy">
                <p className="task-summary-label">False negatives</p>
                <p className="panel-copy">
                  Emails that passed the hard filter but did not become task cards. Add any real miss back into the main queue.
                </p>
              </div>
              <div className="false-negative-dialog-controls">
                <span className="count-pill">{falseNegativeItems.length}</span>
                <button
                  aria-label="Close false negatives dialog"
                  className="false-negative-dialog-close"
                  onClick={() => setIsFalseNegativePanelOpen(false)}
                  type="button"
                >
                  ×
                </button>
              </div>
            </div>

            <div className="false-negative-dialog-body">
              {falseNegativeItems.length ? (
                <div className="false-negative-list">
                  {falseNegativeItems.map((item, index) => (
                    <FalseNegativeCard
                      index={index}
                      isAdding={Boolean(falseNegativePromotionStates[getFalseNegativeKey(item)])}
                      item={item}
                      key={item.sourceId || `${item.platform}-${index}`}
                      onAddToQueue={handlePromoteFalseNegative}
                    />
                  ))}
                </div>
              ) : (
                <div className="task-card task-card-empty false-negative-empty">
                  <p className="summary-value">No possible misses are sitting here right now.</p>
                  <p className="panel-copy">
                    Only emails that survive the hard filter and still do not become task cards will appear here.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
