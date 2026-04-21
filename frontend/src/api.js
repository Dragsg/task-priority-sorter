const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:5000/api";

async function readJson(response) {
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error ?? "Request failed");
  }

  return payload;
}

export function getGmailLinkUrl() {
  return `${API_BASE_URL}/gmail/link`;
}

export async function fetchGmailStatus() {
  const response = await fetch(`${API_BASE_URL}/gmail/status`);
  return readJson(response);
}

export async function fetchRecentEmails() {
  const response = await fetch(`${API_BASE_URL}/gmail/messages/recent`);
  return readJson(response);
}

export async function fetchNewEmails() {
  const response = await fetch(`${API_BASE_URL}/gmail/messages/new`);
  return readJson(response);
}
