import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  clearStoredToken,
  fetchDashboardBootstrap,
  getStoredUser,
  getStoredUserId,
  LIVE_REFRESH_INTERVAL_MS,
  removePrioritizedTask,
  updatePrioritizedTask,
} from "../api";
import { readDashboardCache, writeDashboardCache } from "../dashboardCache";
import PageNav from "../components/PageNav";
const PRIORITY_COLUMNS = [
  { value: "CRITICAL", label: "Critical" },
  { value: "HIGH", label: "High" },
  { value: "MEDIUM", label: "Medium" },
  { value: "LOW", label: "Low" },
];
const PRIORITY_SORT_ORDER = {
  CRITICAL: 0,
  HIGH: 1,
  MEDIUM: 2,
  LOW: 3,
};

const DEADLINE_FILTER_OPTIONS = [
  { value: "all", label: "All deadlines" },
  { value: "none", label: "No deadline" },
  { value: "24h", label: "Due within 24 hours" },
  { value: "3d", label: "Due within 3 days" },
  { value: "7d", label: "Due within 7 days" },
  { value: "urgent", label: "Overdue / urgent" },
];

const TASK_STATUS_OPTIONS = ["OPEN", "COMPLETED"];

function normalizeTag(value) {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function dedupeTags(values) {
  const seen = new Set();
  const ordered = [];
  values.forEach((value) => {
    const normalized = normalizeTag(value);
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    ordered.push(normalized);
  });
  return ordered;
}

function buildTagSuggestions(availableTags, selectedTags, inputValue, limit = 8) {
  const selected = new Set((selectedTags || []).map((tag) => normalizeTag(tag)));
  const query = normalizeTag(inputValue);
  return (availableTags || [])
    .map((tag) => normalizeTag(tag))
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

function formatPriorityTierLabel(priorityTier) {
  if (!priorityTier) {
    return "Unknown";
  }
  return `${priorityTier.charAt(0)}${priorityTier.slice(1).toLowerCase()}`;
}

function compareBoardTasks(left, right) {
  const leftPriority = PRIORITY_SORT_ORDER[left?.priority_tier] ?? 99;
  const rightPriority = PRIORITY_SORT_ORDER[right?.priority_tier] ?? 99;
  if (leftPriority !== rightPriority) {
    return leftPriority - rightPriority;
  }

  const leftDeadline =
    typeof left?.deadline_hours === "number" ? left.deadline_hours : Number.POSITIVE_INFINITY;
  const rightDeadline =
    typeof right?.deadline_hours === "number" ? right.deadline_hours : Number.POSITIVE_INFINITY;
  if (leftDeadline !== rightDeadline) {
    return leftDeadline - rightDeadline;
  }

  const leftTitle = cleanPreviewText(left?.task_title)?.toLowerCase() ?? "";
  const rightTitle = cleanPreviewText(right?.task_title)?.toLowerCase() ?? "";
  const titleComparison = leftTitle.localeCompare(rightTitle);
  if (titleComparison !== 0) {
    return titleComparison;
  }

  return String(left?.canonical_task_id ?? "").localeCompare(String(right?.canonical_task_id ?? ""));
}

function sortBoardTasks(items) {
  return [...(items ?? [])].sort(compareBoardTasks);
}

function calculateDeadlineHours(deadlineAt) {
  if (!deadlineAt) {
    return null;
  }
  const parsed = new Date(deadlineAt);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return Math.max(0, (parsed.getTime() - Date.now()) / (1000 * 60 * 60));
}

function applyTaskPatch(task, payload) {
  if (!task) {
    return task;
  }

  const updates = {};
  if ("title" in payload) {
    updates.task_title = payload.title;
  }
  if ("description" in payload) {
    updates.task_description = payload.description;
  }
  if ("deadlineAt" in payload) {
    updates.deadline_at_iso = payload.deadlineAt || null;
    updates.deadline_hours = calculateDeadlineHours(payload.deadlineAt);
  }
  if ("priorityTier" in payload) {
    updates.priority_tier = payload.priorityTier;
  }
  if ("status" in payload) {
    updates.status = payload.status === "COMPLETED" ? "completed" : "pending_review";
  }
  if ("tags" in payload) {
    updates.tags = dedupeTags(payload.tags);
  }

  return { ...task, ...updates };
}

function mergeTaskIntoBoard(currentTasks, updatedTask) {
  const hasTask = currentTasks.some(
    (task) => task.canonical_task_id === updatedTask.canonical_task_id
  );
  const nextTasks = hasTask
    ? currentTasks.map((task) =>
        task.canonical_task_id === updatedTask.canonical_task_id ? updatedTask : task
      )
    : [...currentTasks, updatedTask];
  return sortBoardTasks(nextTasks);
}

function formatPlatformLabel(task) {
  const platforms = Array.isArray(task?.platforms_seen) ? task.platforms_seen.filter(Boolean) : [];
  if (!platforms.length) {
    return "email";
  }
  return platforms.join(", ");
}

function formatDeadline(hours) {
  if (hours == null) {
    return "No deadline";
  }
  if (hours < 0) {
    return "Overdue";
  }
  if (hours < 1) {
    return "Under 1h left";
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

function getTaskWorkflowStatus(task) {
  return String(task?.status || "").toLowerCase() === "completed" ? "COMPLETED" : "OPEN";
}

function getVisibleTaskTags(task) {
  if (!Array.isArray(task?.tags)) {
    return [];
  }

  const seen = new Set();
  return task.tags.filter((tag) => {
    const normalized = normalizeTag(tag);
    if (!normalized || seen.has(normalized)) {
      return false;
    }
    seen.add(normalized);
    return true;
  });
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

function matchesSearch(task, query) {
  if (!query) {
    return true;
  }

  const haystack = [
    task.task_title,
    task.task_description,
    task.source_subject,
    task.source_sender,
    ...(Array.isArray(task.tags) ? task.tags : []),
  ]
    .map((value) => cleanPreviewText(value) || "")
    .join(" ")
    .toLowerCase();

  return haystack.includes(query.toLowerCase());
}

function matchesDeadlineFilter(task, filterValue) {
  const deadlineHours = typeof task.deadline_hours === "number" ? task.deadline_hours : null;

  if (filterValue === "all") {
    return true;
  }
  if (filterValue === "none") {
    return deadlineHours == null;
  }
  if (filterValue === "24h") {
    return deadlineHours != null && deadlineHours <= 24;
  }
  if (filterValue === "3d") {
    return deadlineHours != null && deadlineHours <= 72;
  }
  if (filterValue === "7d") {
    return deadlineHours != null && deadlineHours <= 168;
  }
  if (filterValue === "urgent") {
    return deadlineHours != null && deadlineHours <= 0;
  }
  return true;
}

function TaskEditModal({
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
    const normalized = normalizeTag(rawValue);
    if (!normalized) {
      setTagInput("");
      return;
    }
    setDraft((current) => ({
      ...current,
      tags: dedupeTags([...current.tags, normalized]),
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
      setDraft((current) => ({
        ...current,
        tags: dedupeTags([...current.tags, ...segments.slice(0, -1)]),
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
              Update the details here without shifting the rest of the board.
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
                {PRIORITY_COLUMNS.map((column) => (
                  <option key={column.value} value={column.value}>
                    {column.label}
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
              rows={5}
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

          {editState?.error ? <p className="error-text">{editState.error}</p> : null}

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

function KanbanCard({
  isExpanded,
  task,
  isDragging,
  isMovePending,
  isSaving,
  onDragStart,
  onDragEnd,
  onEditOpen,
  onDelete,
  onToggleExpanded,
  onToggleCompleted,
}) {
  const visibleTags = getVisibleTaskTags(task);
  const preview = truncateText(
    task.task_description || task.source_snippet || task.source_subject,
    150
  );
  const sourcePreview = truncateText(task.source_snippet, 110);
  const sourceContext = cleanPreviewText(task.source_subject || task.source_sender);
  const isCompleted = getTaskWorkflowStatus(task) === "COMPLETED";

  return (
    <article
      className={`kanban-card task-card task-card-tier-${task.priority_tier.toLowerCase()}${isCompleted ? " kanban-card-completed" : ""}${isDragging ? " kanban-card-dragging" : ""}${isMovePending ? " kanban-card-moving" : ""}${isExpanded ? " kanban-card-expanded" : ""}`}
      draggable={!isSaving && !isMovePending}
      onDragEnd={onDragEnd}
      onDragStart={(event) => onDragStart(event, task)}
    >
      <div className="kanban-card-top">
        <div className="kanban-card-badges">
          <span className={`task-tier task-tier-${task.priority_tier.toLowerCase()}`}>
            {formatPriorityTierLabel(task.priority_tier)}
          </span>
          {isCompleted ? <span className="task-status-badge kanban-status-badge">Completed</span> : null}
        </div>
        <span className="kanban-card-platform">{formatPlatformLabel(task)}</span>
      </div>

      <div className="kanban-card-content">
        <h3 className="task-title kanban-card-title">
          {cleanPreviewText(task.task_title) || "Untitled task"}
        </h3>
        {preview ? (
          <div className="kanban-card-summary-block">
            <p className="task-summary-label">Summary</p>
            <p className="kanban-card-preview">{preview}</p>
          </div>
        ) : null}
        {isExpanded ? (
          <div className="kanban-card-expanded-content">
            {sourceContext ? <p className="kanban-card-context">{sourceContext}</p> : null}
            {sourcePreview && sourcePreview !== preview ? (
              <p className="kanban-card-email-note">
                <span>Original email:</span> {sourcePreview}
              </p>
            ) : null}
            {visibleTags.length ? (
              <div className="task-tag-list kanban-tag-list">
                {visibleTags.map((tag) => (
                  <span className="task-tag-chip" key={tag}>
                    {tag.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="kanban-card-footer">
        <div className="kanban-card-meta">
          <span>{formatDeadline(task.deadline_hours)}</span>
          {typeof task.confidence === "number" ? (
            <span>{Math.round(task.confidence * 100)}% confidence</span>
          ) : null}
        </div>

        <div className="kanban-card-actions">
          <button
            aria-expanded={isExpanded}
            className="kanban-action-button kanban-action-button-quiet"
            disabled={isSaving}
            onClick={() => onToggleExpanded(task.canonical_task_id)}
            type="button"
          >
            {isExpanded ? "Collapse" : "Expand"}
          </button>
          <button
            className="kanban-action-button"
            disabled={isSaving}
            onClick={() => onEditOpen(task.canonical_task_id)}
            type="button"
          >
            Edit
          </button>
          <button
            className="kanban-action-button"
            disabled={isSaving}
            onClick={() => onToggleCompleted(task)}
            type="button"
          >
            {isCompleted ? "Reopen" : "Complete"}
          </button>
          <button
            className="kanban-action-button kanban-action-danger"
            disabled={isSaving}
            onClick={() => onDelete(task)}
            type="button"
          >
            Delete
          </button>
        </div>
      </div>
    </article>
  );
}

function KanbanColumn({
  column,
  tasks,
  dragState,
  onDragOver,
  onDrop,
  ...cardProps
}) {
  const isDropTarget = dragState.overTier === column.value;
  const isDragging = dragState.taskId !== null;

  return (
    <section
      className={`kanban-column${isDropTarget ? " kanban-column-active" : ""}`}
      onDragOver={(event) => onDragOver(event, column.value)}
      onDrop={(event) => onDrop(event, column.value)}
    >
      <div className="kanban-column-header">
        <div>
          <p className="panel-title">{column.label}</p>
          <p className="kanban-column-copy">{tasks.length} task{tasks.length === 1 ? "" : "s"}</p>
        </div>
        <span className={`task-tier task-tier-${column.value.toLowerCase()}`}>
          {column.label}
        </span>
      </div>

      <div className="kanban-column-body">
        {tasks.length ? (
          tasks.map((task) => (
            <KanbanCard
              isExpanded={Boolean(cardProps.expandedTaskIds[task.canonical_task_id])}
              isDragging={dragState.taskId === task.canonical_task_id}
              isMovePending={Boolean(cardProps.movingStates[task.canonical_task_id])}
              isSaving={Boolean(cardProps.savingStates[task.canonical_task_id])}
              key={task.canonical_task_id}
              onDelete={cardProps.onDelete}
              onDragEnd={cardProps.onDragEnd}
              onDragStart={cardProps.onDragStart}
              onEditOpen={cardProps.onEditOpen}
              onToggleExpanded={cardProps.onToggleExpanded}
              onToggleCompleted={cardProps.onToggleCompleted}
              task={task}
            />
          ))
        ) : (
          <div className="kanban-column-empty">
            <p className="summary-value">No matching tasks.</p>
            <p className="panel-copy">Drag a card here or adjust the filters above.</p>
          </div>
        )}
        <div
          aria-hidden="true"
          className={`kanban-column-dropzone${isDropTarget ? " kanban-column-dropzone-active" : ""}${isDragging ? " kanban-column-dropzone-visible" : ""}`}
        >
          Drop task here
        </div>
      </div>
    </section>
  );
}

export default function Kanban() {
  const navigate = useNavigate();
  const storedUserId = getStoredUserId();
  const storedUser = getStoredUser();
  const [cachedDashboard] = useState(() => readDashboardCache(storedUserId));
  const [user, setUser] = useState(() => cachedDashboard?.user ?? storedUser);
  const [tasks, setTasks] = useState(() => sortBoardTasks(cachedDashboard?.tasks ?? []));
  const [availableTags, setAvailableTags] = useState(() => cachedDashboard?.availableTags ?? []);
  const [loading, setLoading] = useState(() => !cachedDashboard && !storedUser);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTags, setSelectedTags] = useState([]);
  const [deadlineFilter, setDeadlineFilter] = useState("all");
  const [showCompleted, setShowCompleted] = useState(false);
  const [editingTaskId, setEditingTaskId] = useState(null);
  const [editStates, setEditStates] = useState({});
  const [savingStates, setSavingStates] = useState({});
  const [movingStates, setMovingStates] = useState({});
  const [dragState, setDragState] = useState({
    taskId: null,
    fromTier: null,
    overTier: null,
  });
  const [expandedTaskIds, setExpandedTaskIds] = useState({});
  const dragPreviewRef = useRef(null);

  useEffect(() => {
    let isCancelled = false;

    async function loadBoard() {
      try {
        if (!cachedDashboard && !storedUser) {
          setLoading(true);
        }
        const dashboard = await fetchDashboardBootstrap();
        if (isCancelled) {
          return;
        }
        setUser(dashboard.user);
        setTasks(sortBoardTasks(dashboard.items ?? []));
        setAvailableTags(dashboard.availableTags ?? []);
        setError("");
      } catch (loadError) {
        if (isCancelled) {
          return;
        }
        if (cachedDashboard || getStoredUser()) {
          setError(loadError.message || "Unable to load the latest board right now.");
        } else {
          clearStoredToken();
          navigate("/", { replace: true });
        }
      } finally {
        setLoading(false);
      }
    }

    loadBoard();

    return () => {
      isCancelled = true;
    };
  }, [cachedDashboard, navigate, storedUser]);

  useEffect(() => {
    if (!user?.userId) {
      return;
    }
    writeDashboardCache(user.userId, {
      user,
      tasks,
      availableTags,
    });
  }, [availableTags, tasks, user]);

  const hasEditInFlight = Object.values(editStates).some((state) => state?.isSaving);
  const hasTaskSaveInFlight = Object.keys(savingStates).length > 0;
  const hasTaskMoveInFlight = Object.keys(movingStates).length > 0;
  const isLiveRefreshPaused =
    editingTaskId !== null ||
    dragState.taskId !== null ||
    hasEditInFlight ||
    hasTaskSaveInFlight ||
    hasTaskMoveInFlight;

  useEffect(() => {
    let isCancelled = false;
    let refreshInFlight = false;

    async function refreshBoardQuietly() {
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
        setTasks(sortBoardTasks(dashboard.items ?? []));
        setAvailableTags(dashboard.availableTags ?? []);
      } catch {
        // Keep the current board visible if an automatic refresh misses a cycle.
      } finally {
        refreshInFlight = false;
      }
    }

    const intervalId = window.setInterval(refreshBoardQuietly, LIVE_REFRESH_INTERVAL_MS);

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
    };
  }, [isLiveRefreshPaused]);

  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      const isCompleted = getTaskWorkflowStatus(task) === "COMPLETED";
      if (!showCompleted && isCompleted) {
        return false;
      }
      if (!matchesSearch(task, searchQuery)) {
        return false;
      }
      if (selectedTags.length) {
        const taskTags = new Set(getVisibleTaskTags(task));
        if (!selectedTags.every((tag) => taskTags.has(tag))) {
          return false;
        }
      }
      if (!matchesDeadlineFilter(task, deadlineFilter)) {
        return false;
      }
      return true;
    });
  }, [deadlineFilter, searchQuery, selectedTags, showCompleted, tasks]);

  const groupedTasks = useMemo(() => {
    const grouped = {
      CRITICAL: [],
      HIGH: [],
      MEDIUM: [],
      LOW: [],
    };
    filteredTasks.forEach((task) => {
      const bucket = grouped[task.priority_tier] || grouped.LOW;
      bucket.push(task);
    });
    return grouped;
  }, [filteredTasks]);

  const activeEditingTask = useMemo(
    () => tasks.find((task) => task.canonical_task_id === editingTaskId) ?? null,
    [editingTaskId, tasks]
  );

  function updateBoardFromResult(result) {
    if (result?.task) {
      setTasks((current) => mergeTaskIntoBoard(current, result.task));
    } else if (result?.items) {
      setTasks(sortBoardTasks(result.items));
    }
    if (result?.availableTags) {
      setAvailableTags(result.availableTags);
    }
  }

  function markTaskBusy(canonicalTaskId, nextState = true) {
    setSavingStates((current) => ({
      ...current,
      [canonicalTaskId]: nextState,
    }));
  }

  function clearTaskBusy(canonicalTaskId) {
    setSavingStates((current) => {
      const updated = { ...current };
      delete updated[canonicalTaskId];
      return updated;
    });
  }

  function markTaskMoving(canonicalTaskId, nextState = true) {
    setMovingStates((current) => ({
      ...current,
      [canonicalTaskId]: nextState,
    }));
  }

  function clearTaskMoving(canonicalTaskId) {
    setMovingStates((current) => {
      const updated = { ...current };
      delete updated[canonicalTaskId];
      return updated;
    });
  }

  function openTaskEditor(canonicalTaskId) {
    setEditingTaskId(canonicalTaskId);
    setEditStates((current) => ({
      ...current,
      [canonicalTaskId]: { isSaving: false, error: "" },
    }));
  }

  function closeTaskEditor(canonicalTaskId) {
    setEditingTaskId((current) => (current === canonicalTaskId ? null : current));
    setEditStates((current) => {
      const updated = { ...current };
      delete updated[canonicalTaskId];
      return updated;
    });
  }

  function handleTagFilterToggle(tag) {
    setSelectedTags((current) =>
      current.includes(tag) ? current.filter((value) => value !== tag) : [...current, tag]
    );
  }

  function createDragPreview(cardElement) {
    if (typeof document === "undefined" || !cardElement) {
      return null;
    }

    const preview = cardElement.cloneNode(true);
    preview.style.position = "fixed";
    preview.style.top = "-9999px";
    preview.style.left = "-9999px";
    preview.style.width = `${cardElement.offsetWidth}px`;
    preview.style.pointerEvents = "none";
    preview.style.margin = "0";
    preview.style.transform = "rotate(1.5deg) scale(1.02)";
    preview.style.boxShadow = "0 20px 42px rgba(92, 71, 46, 0.22)";
    preview.style.opacity = "0.98";
    preview.style.zIndex = "9999";
    preview.classList.add("kanban-card-drag-preview");
    document.body.appendChild(preview);
    dragPreviewRef.current = preview;
    return preview;
  }

  function cleanupDragPreview() {
    if (dragPreviewRef.current?.parentNode) {
      dragPreviewRef.current.parentNode.removeChild(dragPreviewRef.current);
    }
    dragPreviewRef.current = null;
  }

  function handleToggleExpanded(canonicalTaskId) {
    setExpandedTaskIds((current) => ({
      ...current,
      [canonicalTaskId]: !current[canonicalTaskId],
    }));
  }

  function handleDragStart(event, task) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", task.canonical_task_id);
    const preview = createDragPreview(event.currentTarget);
    if (preview) {
      event.dataTransfer.setDragImage(preview, 24, 24);
    }
    setDragState({
      taskId: task.canonical_task_id,
      fromTier: task.priority_tier,
      overTier: task.priority_tier,
    });
    setError("");
  }

  function handleDragEnd() {
    cleanupDragPreview();
    setDragState({ taskId: null, fromTier: null, overTier: null });
  }

  function handleDragOver(event, priorityTier) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDragState((current) =>
      current.overTier === priorityTier ? current : { ...current, overTier: priorityTier }
    );
  }

  async function handlePriorityDrop(event, priorityTier) {
    event.preventDefault();
    const canonicalTaskId = event.dataTransfer.getData("text/plain") || dragState.taskId;
    const selectedTask = tasks.find((task) => task.canonical_task_id === canonicalTaskId);
    const previousTasks = tasks;

    cleanupDragPreview();
    setDragState({ taskId: null, fromTier: null, overTier: null });

    if (!selectedTask || selectedTask.priority_tier === priorityTier) {
      return;
    }

    setError("");
    markTaskMoving(canonicalTaskId);
    setTasks((current) =>
      sortBoardTasks(
        current.map((task) =>
          task.canonical_task_id === canonicalTaskId
            ? { ...task, priority_tier: priorityTier }
            : task
        )
      )
    );

    try {
      const result = await updatePrioritizedTask(canonicalTaskId, { priorityTier });
      updateBoardFromResult(result);
    } catch (saveError) {
      setTasks(previousTasks);
      setError(saveError.message);
    } finally {
      clearTaskMoving(canonicalTaskId);
    }
  }

  async function handleTaskEditSave(canonicalTaskId, payload) {
    const previousTasks = tasks;
    setError("");
    setEditStates((current) => ({
      ...current,
      [canonicalTaskId]: { isSaving: true, error: "" },
    }));
    markTaskBusy(canonicalTaskId);
    setTasks((current) =>
      sortBoardTasks(
        current.map((task) =>
          task.canonical_task_id === canonicalTaskId ? applyTaskPatch(task, payload) : task
        )
      )
    );

    try {
      const result = await updatePrioritizedTask(canonicalTaskId, payload);
      updateBoardFromResult(result);
      closeTaskEditor(canonicalTaskId);
    } catch (saveError) {
      setTasks(previousTasks);
      setEditStates((current) => ({
        ...current,
        [canonicalTaskId]: { isSaving: false, error: saveError.message },
      }));
      setError(saveError.message);
    } finally {
      clearTaskBusy(canonicalTaskId);
    }
  }

  async function handleDelete(task) {
    const previousTasks = tasks;
    setError("");
    markTaskBusy(task.canonical_task_id);
    setTasks((current) =>
      sortBoardTasks(
        current.filter((item) => item.canonical_task_id !== task.canonical_task_id)
      )
    );

    try {
      await removePrioritizedTask(task.canonical_task_id);
      closeTaskEditor(task.canonical_task_id);
    } catch (removeError) {
      setTasks(previousTasks);
      setError(removeError.message);
    } finally {
      clearTaskBusy(task.canonical_task_id);
    }
  }

  async function handleToggleCompleted(task) {
    const nextStatus = getTaskWorkflowStatus(task) === "COMPLETED" ? "OPEN" : "COMPLETED";
    const previousTasks = tasks;

    setError("");
    markTaskBusy(task.canonical_task_id);
    setTasks((current) =>
      sortBoardTasks(
        current.map((item) =>
          item.canonical_task_id === task.canonical_task_id
            ? { ...item, status: nextStatus === "COMPLETED" ? "completed" : "pending_review" }
            : item
        )
      )
    );

    try {
      const result = await updatePrioritizedTask(task.canonical_task_id, { status: nextStatus });
      updateBoardFromResult(result);
    } catch (saveError) {
      setTasks(previousTasks);
      setError(saveError.message);
    } finally {
      clearTaskBusy(task.canonical_task_id);
    }
  }

  useEffect(() => cleanupDragPreview, []);

  if (!user && loading) {
    return <main className="simple-shell">Loading your Kanban board...</main>;
  }

  return (
    <main className="simple-shell">
      <PageNav />
      <section className="simple-hero">
        <p className="auth-eyebrow">Kanban</p>
        <h1 className="simple-title">Move work where it belongs</h1>
        <p className="simple-copy">
          Drag tasks across priority lanes, filter the board, and keep details up to date without leaving the app.
        </p>
      </section>

      <section className="simple-card">
        <div className="summary-grid summary-grid-wide">
          <article className="summary-card">
            <p className="summary-label">Signed in as</p>
            <p className="summary-value">{user?.username ?? "Refreshing your account..."}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Visible tasks</p>
            <p className="summary-value">{filteredTasks.length}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Completed shown</p>
            <p className="summary-value">{showCompleted ? "Yes" : "No"}</p>
          </article>
          <article className="summary-card">
            <p className="summary-label">Quick links</p>
            <p className="summary-value summary-value-stack">
              <span>
                <Link className="inline-button" to="/home">Dashboard</Link>
              </span>
              <span>
                <Link className="inline-button" to="/statistics">Statistics</Link>
              </span>
            </p>
          </article>
        </div>

        <section className="kanban-filter-bar">
          <label className="field-group kanban-filter-field">
            <span>Search</span>
            <input
              className="auth-input"
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search title, description, sender, subject, or tags"
              type="text"
              value={searchQuery}
            />
          </label>
          <label className="field-group kanban-filter-field">
            <span>Deadline</span>
            <select
              className="auth-input"
              onChange={(event) => setDeadlineFilter(event.target.value)}
              value={deadlineFilter}
            >
              {DEADLINE_FILTER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="kanban-toggle">
            <input
              checked={showCompleted}
              onChange={(event) => setShowCompleted(event.target.checked)}
              type="checkbox"
            />
            <span>Show completed tasks</span>
          </label>
        </section>

        {availableTags.length ? (
          <section className="kanban-tag-filter">
            <div className="task-tag-header">
              <span className="task-tag-label">Filter by tags</span>
              {selectedTags.length ? (
                <button
                  className="task-tag-inline-action"
                  onClick={() => setSelectedTags([])}
                  type="button"
                >
                  Clear filters
                </button>
              ) : null}
            </div>
            <div className="task-tag-list">
              {availableTags.map((tag) => {
                const normalizedTag = normalizeTag(tag);
                const isActive = selectedTags.includes(normalizedTag);
                return (
                  <button
                    className={`task-tag-chip kanban-filter-chip${isActive ? " kanban-filter-chip-active" : ""}`}
                    key={normalizedTag}
                    onClick={() => handleTagFilterToggle(normalizedTag)}
                    type="button"
                  >
                    {normalizedTag.replace(/_/g, " ")}
                  </button>
                );
              })}
            </div>
          </section>
        ) : null}

        {error ? <p className="error-text">{error}</p> : null}

        {filteredTasks.length ? (
          <section className="kanban-board">
            {PRIORITY_COLUMNS.map((column) => (
              <KanbanColumn
                column={column}
                dragState={dragState}
                key={column.value}
                onDelete={handleDelete}
                onDragEnd={handleDragEnd}
                onDragOver={handleDragOver}
                onDragStart={handleDragStart}
                onDrop={handlePriorityDrop}
                movingStates={movingStates}
                onEditOpen={openTaskEditor}
                onToggleExpanded={handleToggleExpanded}
                onToggleCompleted={handleToggleCompleted}
                expandedTaskIds={expandedTaskIds}
                savingStates={savingStates}
                tasks={groupedTasks[column.value]}
              />
            ))}
          </section>
        ) : (
          <div className="task-card task-card-empty">
            <p className="summary-value">No tasks match the current board filters.</p>
            <p className="panel-copy">
              Try clearing search or tag filters, or enable completed tasks to widen the board.
            </p>
          </div>
        )}
      </section>

      {activeEditingTask ? (
        <TaskEditModal
          availableTags={availableTags}
          editState={editStates[activeEditingTask.canonical_task_id]}
          onCancel={() => closeTaskEditor(activeEditingTask.canonical_task_id)}
          onSave={handleTaskEditSave}
          task={activeEditingTask}
        />
      ) : null}
    </main>
  );
}
