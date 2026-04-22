from __future__ import annotations

import re
from collections.abc import Iterable

from pipeline.models.enums import TaskType


FIXED_TAG_CATALOG = [
    "action_required",
    "urgent",
    "deadline",
    "follow_up",
    "waiting_for_reply",
    "optional",
    "assignment",
    "exam",
    "project",
    "lecture",
    "group_work",
    "admin",
    "finance",
    "career",
    "newsletter",
    "announcement",
    "promotion",
]

_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")
_TAG_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("urgent", ("urgent", "asap", "immediately", "tonight")),
    ("deadline", ("deadline", "due", "by ", "before ", "submit by")),
    ("follow_up", ("follow up", "reminder", "check in", "circle back")),
    ("waiting_for_reply", ("reply", "respond", "response", "waiting on")),
    ("optional", ("optional", "if interested", "nice to have")),
    ("assignment", ("assignment", "homework", "worksheet", "submission", "quiz")),
    ("exam", ("exam", "midterm", "final", "test")),
    ("project", ("project", "milestone", "deliverable", "proposal")),
    ("lecture", ("lecture", "class", "seminar", "tutorial")),
    ("group_work", ("group", "team", "committee", "collab")),
    ("admin", ("register", "admin", "form", "verification", "confirm")),
    ("finance", ("invoice", "payment", "billing", "reimbursement", "claim")),
    ("career", ("interview", "career", "recruit", "internship", "resume")),
    ("newsletter", ("newsletter", "digest", "roundup")),
    ("announcement", ("announcement", "notice", "update", "released")),
    ("promotion", ("promotion", "offer", "sale", "discount")),
    ("action_required", ("action required", "please", "need to", "required")),
]


def normalize_tag(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _NORMALIZE_PATTERN.sub("_", value.strip().lower()).strip("_")
    return normalized or None


def dedupe_tags(tags: Iterable[str | None]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in tags:
        normalized = normalize_tag(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def merge_tag_catalog(custom_tags: Iterable[str] | None = None) -> list[str]:
    return dedupe_tags([*FIXED_TAG_CATALOG, *(custom_tags or [])])


def filter_allowed_tags(tags: Iterable[str], available_tags: Iterable[str], *, max_count: int | None = None) -> list[str]:
    allowed = set(dedupe_tags(available_tags))
    filtered = [tag for tag in dedupe_tags(tags) if tag in allowed]
    if max_count is not None:
        return filtered[:max_count]
    return filtered


def infer_tags_from_text(
    *,
    text: str,
    task_type: TaskType | None = None,
    available_tags: Iterable[str] | None = None,
    manual_tags: Iterable[str] | None = None,
    max_count: int = 3,
) -> list[str]:
    allowed = set(dedupe_tags(available_tags or FIXED_TAG_CATALOG))
    lowered = (text or "").lower()
    suggestions: list[str] = []

    for tag in dedupe_tags(manual_tags or []):
        if tag in allowed:
            suggestions.append(tag)

    if task_type == TaskType.SUBMISSION and "assignment" in allowed:
        suggestions.append("assignment")
    elif task_type == TaskType.MEETING and "lecture" in allowed:
        suggestions.append("lecture")
    elif task_type == TaskType.ADMIN and "admin" in allowed:
        suggestions.append("admin")

    for tag, hints in _TAG_HINTS:
        if tag not in allowed:
            continue
        if any(hint in lowered for hint in hints):
            suggestions.append(tag)

    return filter_allowed_tags(suggestions, allowed, max_count=max_count)
