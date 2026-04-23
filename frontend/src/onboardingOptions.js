export const PERFORMANCE_TIME_OPTIONS = [
  "Morning",
  "Afternoon",
  "Evening",
  "It depends",
];

export const IMPORTANT_TOPIC_OPTIONS = [
  "Classes and assignments",
  "External meetings and events",
  "Personal goals",
  "A mix of these",
];

export const PRIORITISE_BY_OPTIONS = [
  "Urgency",
  "Overall importance",
  "Who it's from",
  "A mix of these",
];

const ONBOARDING_ACCESS_KEY = "task-priority-onboarding-access";

export function isOnboardingComplete(user) {
  return Boolean(
    user?.onboardingComplete
      || (user?.performanceTime && user?.importantTopic && user?.prioritiseBy)
  );
}

export function normalizeOnboardingAnswer(options, value) {
  if (!value) {
    return "";
  }

  const exactMatch = options.find((option) => option === value);
  if (exactMatch) {
    return exactMatch;
  }

  const lowered = value.trim().toLowerCase();
  return options.find((option) => option.toLowerCase() === lowered) ?? value;
}

export function getOnboardingAnswerLabel(options, value) {
  const normalized = normalizeOnboardingAnswer(options, value);
  return options.includes(normalized) ? normalized : "Not set yet";
}

export function grantOnboardingAccess(userId) {
  if (!userId) {
    return;
  }

  try {
    localStorage.setItem(
      ONBOARDING_ACCESS_KEY,
      JSON.stringify({
        userId,
        grantedAt: new Date().toISOString(),
      })
    );
  } catch {
    // Ignore storage failures and keep auth flow usable.
  }
}

export function hasOnboardingAccess(userId) {
  if (!userId) {
    return false;
  }

  try {
    const raw = localStorage.getItem(ONBOARDING_ACCESS_KEY);
    if (!raw) {
      return false;
    }

    const parsed = JSON.parse(raw);
    return parsed?.userId === userId;
  } catch {
    return false;
  }
}

export function revokeOnboardingAccess() {
  try {
    localStorage.removeItem(ONBOARDING_ACCESS_KEY);
  } catch {
    // Ignore storage failures and keep auth flow usable.
  }
}
