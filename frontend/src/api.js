const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:5000/api";
const OUTLOOK_AUTH_BASE_URL =
  import.meta.env.VITE_OUTLOOK_AUTH_BASE_URL ?? "http://localhost:5000/api";

export function getStoredToken() {
  return localStorage.getItem("token");
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

export async function fetchRecentEmails() {
  const response = await fetch(`${API_BASE_URL}/gmail/messages/recent`, {
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

export async function fetchRecentOutlookEmails() {
  const response = await fetch(`${API_BASE_URL}/outlook/messages/recent`, {
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
