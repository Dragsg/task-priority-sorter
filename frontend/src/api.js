const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:5000/api";
const OUTLOOK_AUTH_BASE_URL =
  import.meta.env.VITE_OUTLOOK_AUTH_BASE_URL ?? "http://localhost:5000/api";
const STORED_USER_KEY = "task-priority-user";
export const LIVE_REFRESH_INTERVAL_MS = 30000;

export function getStoredToken() {
  return localStorage.getItem("token");
}

export function getStoredUserId() {
  const token = getStoredToken();
  if (!token) {
    return null;
  }

  try {
    const [, payload] = token.split(".");
    if (!payload) {
      return null;
    }
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return decoded.user_id ?? null;
  } catch {
    return null;
  }
}

export function clearStoredToken() {
  localStorage.removeItem("token");
  localStorage.removeItem(STORED_USER_KEY);
}

export function getStoredUser() {
  const storedUserId = getStoredUserId();
  if (!storedUserId) {
    return null;
  }

  try {
    const raw = localStorage.getItem(STORED_USER_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw);
    if (!parsed || parsed.userId !== storedUserId) {
      return null;
    }

    return parsed;
  } catch {
    return null;
  }
}

export function storeUser(user) {
  if (!user?.userId) {
    return;
  }

  try {
    localStorage.setItem(STORED_USER_KEY, JSON.stringify(user));
  } catch {
    // Ignore cache write failures so auth flows still work.
  }
}

function getAuthHeaders(extraHeaders = {}) {
  const token = getStoredToken();

  if (!token) {
    return extraHeaders;
  }

  return {
    ...extraHeaders,
    Authorization: `Bearer ${token}`,
  };
}

async function readJson(response) {
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error ?? "Request failed");
  }

  return payload;
}

async function sendJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  return readJson(response);
}

export async function signUp({ username, password, name }) {
  return sendJson("/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, name }),
  });
}

export async function signIn({ username, password }) {
  return sendJson("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export async function fetchCurrentUser() {
  const user = await sendJson("/user", {
    headers: getAuthHeaders(),
  });
  storeUser(user);
  return user;
}

export async function fetchDashboardBootstrap() {
  const response = await fetch(`${API_BASE_URL}/dashboard`, {
    headers: getAuthHeaders(),
  });
  const payload = await readJson(response);
  storeUser(payload.user);
  return payload;
}

export async function fetchStatisticsSnapshot() {
  const response = await fetch(`${API_BASE_URL}/statistics`, {
    headers: getAuthHeaders(),
  });
  const payload = await readJson(response);
  storeUser(payload.user);
  return payload;
}

export async function saveOnboardingAnswers({
  performanceTime,
  importantTopic,
  prioritiseBy,
}) {
  return sendJson("/onboarding", {
    method: "PUT",
    headers: getAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ performanceTime, importantTopic, prioritiseBy }),
  });
}

export async function fetchOnboardingContext() {
  const response = await fetch(`${API_BASE_URL}/onboarding/context`, {
    headers: getAuthHeaders(),
  });
  const payload = await readJson(response);
  storeUser(payload.user);
  return payload;
}

export async function uploadOnboardingCalendar(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/onboarding/calendar`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: formData,
  });
  return readJson(response);
}

export async function deleteOnboardingCalendar() {
  return sendJson("/onboarding/calendar", {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
}

export function getGmailLinkUrl(userId) {
  return `${API_BASE_URL}/gmail/link?user_id=${userId}`;
}

export function getOutlookLinkUrl(userId) {
  return `${OUTLOOK_AUTH_BASE_URL}/outlook/link?user_id=${userId}`;
}

export async function fetchGmailStatus() {
  const response = await fetch(`${API_BASE_URL}/gmail/status`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function fetchRecentEmails(limit = 5) {
  const response = await fetch(`${API_BASE_URL}/gmail/messages/recent?limit=${limit}`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function fetchNewEmails() {
  const response = await fetch(`${API_BASE_URL}/gmail/messages/new`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function fetchOutlookStatus() {
  const response = await fetch(`${API_BASE_URL}/outlook/status`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function fetchRecentOutlookEmails(limit = 5) {
  const response = await fetch(`${API_BASE_URL}/outlook/messages/recent?limit=${limit}`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function fetchNewOutlookEmails() {
  const response = await fetch(`${API_BASE_URL}/outlook/messages/new`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function fetchBackgroundSyncStatus() {
  const response = await fetch(`${API_BASE_URL}/background-sync/status`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function syncPrioritizedTasks(limit) {
  const query = limit ? `?limit=${limit}` : "";
  return sendJson(`/tasks/sync${query}`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
}

export async function createManualTask(payload) {
  return sendJson("/tasks/manual", {
    method: "POST",
    headers: getAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}

export async function fetchPrioritizedTasks() {
  const response = await fetch(`${API_BASE_URL}/tasks`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function fetchPipelineProfile() {
  const response = await fetch(`${API_BASE_URL}/tasks/profile`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function submitTaskFeedback(canonicalTaskId, { action, direction } = {}) {
  return sendJson(`/tasks/${canonicalTaskId}/feedback`, {
    method: "POST",
    headers: getAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ action, direction }),
  });
}

export async function updateTaskTags(canonicalTaskId, tags = []) {
  return sendJson(`/tasks/${canonicalTaskId}/tags`, {
    method: "PATCH",
    headers: getAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ tags }),
  });
}

export async function updatePrioritizedTask(canonicalTaskId, payload) {
  return sendJson(`/tasks/${canonicalTaskId}`, {
    method: "PATCH",
    headers: getAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}

export async function removePrioritizedTask(canonicalTaskId) {
  return sendJson(`/tasks/${canonicalTaskId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
}
