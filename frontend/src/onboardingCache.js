const ONBOARDING_CACHE_VERSION = 2;

function getOnboardingCacheKey(userId) {
  return `task-priority-onboarding:v${ONBOARDING_CACHE_VERSION}:${userId}`;
}

export function readOnboardingCache(userId) {
  if (!userId) {
    return null;
  }

  try {
    const raw = localStorage.getItem(getOnboardingCacheKey(userId));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    return {
      user: parsed.user ?? null,
      onboarding: parsed.onboarding ?? null,
    };
  } catch {
    return null;
  }
}

export function writeOnboardingCache(userId, user, onboarding) {
  if (!userId) {
    return;
  }

  try {
    localStorage.setItem(
      getOnboardingCacheKey(userId),
      JSON.stringify({
        cachedAt: new Date().toISOString(),
        user: user ?? null,
        onboarding: onboarding ?? null,
      })
    );
  } catch {
    // Ignore cache write failures and keep the page usable.
  }
}

export function clearOnboardingCache(userId) {
  if (!userId) {
    return;
  }

  try {
    localStorage.removeItem(getOnboardingCacheKey(userId));
  } catch {
    // Ignore cache clear failures and let auth continue.
  }
}
