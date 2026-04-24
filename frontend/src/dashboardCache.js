const DASHBOARD_CACHE_VERSION = 5;

function getDashboardCacheKey(userId) {
  return `task-priority-dashboard:v${DASHBOARD_CACHE_VERSION}:${userId}`;
}

export function readDashboardCache(userId) {
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
      allTasks: Array.isArray(parsed.allTasks) ? parsed.allTasks : null,
      profile: parsed.profile ?? null,
      availableTags: Array.isArray(parsed.availableTags) ? parsed.availableTags : [],
    };
  } catch {
    return null;
  }
}

export function writeDashboardCache(userId, payload = {}) {
  if (!userId) {
    return;
  }

  try {
    const existing = readDashboardCache(userId) ?? {};
    const nextPayload = {
      cachedAt: new Date().toISOString(),
      user: payload.user ?? existing.user ?? null,
      tasks: Array.isArray(payload.tasks) ? payload.tasks : (existing.tasks ?? []),
      profile: payload.profile ?? existing.profile ?? null,
      availableTags: Array.isArray(payload.availableTags)
        ? payload.availableTags
        : (existing.availableTags ?? []),
    };
    const nextAllTasks = Array.isArray(payload.allTasks)
      ? payload.allTasks
      : (Array.isArray(existing.allTasks) ? existing.allTasks : undefined);
    if (nextAllTasks !== undefined) {
      nextPayload.allTasks = nextAllTasks;
    }
    localStorage.setItem(
      getDashboardCacheKey(userId),
      JSON.stringify(nextPayload)
    );
  } catch {
    // Ignore cache write failures and keep the live UI responsive.
  }
}
