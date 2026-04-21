const TOKEN_KEY = "task-priority-sorter-token";
const USER_KEY = "task-priority-sorter-user";

export function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser() {
    const value = localStorage.getItem(USER_KEY);
    if (!value) {
        return null;
    }

    try {
        return JSON.parse(value);
    } catch {
        return null;
    }
}

export function persistSession(payload) {
    localStorage.setItem(TOKEN_KEY, payload.token);
    localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
}

export function persistUser(user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}
