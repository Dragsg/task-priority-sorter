const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:5000/api";
const OUTLOOK_AUTH_BASE_URL =
  import.meta.env.VITE_OUTLOOK_AUTH_BASE_URL ?? "http://localhost:5000/api";

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

export async function signUp({ email, password, name }) {
  return sendJson("/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name }),
  });
}

export async function signIn({ email, password }) {
  return sendJson("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function fetchCurrentUser() {
  return sendJson("/user", {
    headers: getAuthHeaders(),
  });
}

export async function fetchDashboardBootstrap() {
  const response = await fetch(`${API_BASE_URL}/dashboard`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function fetchStatisticsSnapshot() {
  const response = await fetch(`${API_BASE_URL}/statistics`, {
    headers: getAuthHeaders(),
  });
  return readJson(response);
}

export async function saveOnboardingPreferences(preferences) {
  return sendJson("/onboarding", {
    method: "PUT",
    headers: getAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ preferences }),
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

export async function removePrioritizedTask(canonicalTaskId) {
  return sendJson(`/tasks/${canonicalTaskId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
}
