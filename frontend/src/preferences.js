export const PREFERENCE_OPTIONS = [
  {
    value: "School",
    title: "School",
    description: "Keep classes, deadlines, and group updates easier to spot.",
  },
  {
    value: "Work",
    title: "Work",
    description: "Stay focused on priorities, follow-ups, and team communication.",
  },
  {
    value: "Personal",
    title: "Personal",
    description: "Organize everyday messages, reminders, and life admin.",
  },
  {
    value: "Unsure",
    title: "Still figuring it out",
    description: "Start simple for now and update your preference later.",
  },
];

export function getPreferenceLabel(value) {
  return PREFERENCE_OPTIONS.find((option) => option.value === value)?.title ?? "Not set yet";
}
