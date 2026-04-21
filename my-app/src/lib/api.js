import { getToken } from "./session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:5000";

async function request(path, options = {}) {
    const headers = new Headers(options.headers ?? {});
    headers.set("Content-Type", "application/json");

    const token = getToken();
    if (token) {
        headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(`${API_BASE_URL}${path}`, {
        ...options,
        headers,
    });

    let payload = {};
    try {
        payload = await response.json();
    } catch {
        payload = {};
    }

    if (!response.ok) {
        throw new Error(payload.message || "Something went wrong.");
    }

    return payload;
}

export function signupUser({ name, email, password }) {
    return request("/api/auth/signup", {
        method: "POST",
        body: JSON.stringify({ name, email, password }),
    });
}

export function loginUser({ email, password }) {
    return request("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
    });
}

export function getCurrentUser() {
    return request("/api/auth/me", { method: "GET" });
}

export function saveOnboardingPreference(preference) {
    return request("/api/onboarding", {
        method: "PUT",
        body: JSON.stringify({ preference }),
    });
}
