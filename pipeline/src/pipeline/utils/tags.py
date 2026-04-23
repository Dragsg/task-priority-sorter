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
    "lab",
    "group_work",
    "attendance",
    "admin",
    "registration",
    "finance",
    "career",
    "event",
    "newsletters",
    "announcement",
    "promotion",
]

_TAG_ALIASES = {
    "newsletter": "newsletters",
}

_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")
_TAG_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("urgent", ("urgent", "asap", "immediately", "tonight", "today", "right away")),
    ("deadline", ("deadline", "due", "by ", "before ", "submit by", "expires", "closing date")),
    ("follow_up", ("follow up", "reminder", "check in", "circle back")),
    ("waiting_for_reply", ("reply", "respond", "response", "waiting on", "get back to", "revert")),
    ("optional", ("optional", "if interested", "nice to have")),
    ("assignment", ("assignment", "homework", "worksheet", "submission", "quiz", "canvas")),
    ("exam", ("exam", "midterm", "final", "test")),
    ("project", ("project", "milestone", "deliverable", "proposal")),
    ("lecture", ("lecture", "class", "seminar", "tutorial")),
    ("lab", ("lab", "practical", "experiment", "studio")),
    ("group_work", ("group", "team", "committee", "collab")),
    ("attendance", ("attendance", "attend", "presence", "roll call", "check-in")),
    ("admin", ("admin", "form", "verification", "confirm", "declaration", "document")),
    ("registration", ("register", "registration", "enrol", "enroll", "sign up", "apply")),
    ("finance", ("invoice", "payment", "billing", "reimbursement", "claim", "fee")),
    ("career", ("interview", "career", "recruit", "internship", "resume")),
    ("event", ("event", "webinar", "workshop", "orientation", "fair", "session", "talk")),
    ("newsletters", ("newsletter", "newsletters", "digest", "roundup")),
    ("announcement", ("announcement", "notice", "update", "released")),
    ("promotion", ("promotion", "offer", "sale", "discount")),
    ("action_required", ("action required", "please", "need to", "required", "complete", "submit")),
]


def normalize_tag(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _NORMALIZE_PATTERN.sub("_", value.strip().lower()).strip("_")
    normalized = _TAG_ALIASES.get(normalized, normalized)
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
    elif task_type == TaskType.MEETING:
        if "attendance" in allowed:
            suggestions.append("attendance")
        if "lecture" in allowed:
            suggestions.append("lecture")
    elif task_type == TaskType.ADMIN and "admin" in allowed:
        suggestions.append("admin")
    elif task_type == TaskType.SOCIAL and "event" in allowed:
        suggestions.append("event")

    for tag, hints in _TAG_HINTS:
        if tag not in allowed:
            continue
        if any(hint in lowered for hint in hints):
            suggestions.append(tag)

    return filter_allowed_tags(suggestions, allowed, max_count=max_count)


def build_tag_text(*parts: str | None, score_reasons: Iterable[str] | None = None) -> str:
    text_parts = [value.strip() for value in parts if isinstance(value, str) and value.strip()]
    if score_reasons:
        text_parts.extend(reason.strip() for reason in score_reasons if isinstance(reason, str) and reason.strip())
    return " ".join(text_parts)


def synthesize_task_tags(
    *,
    task_type: TaskType | None = None,
    text_parts: Iterable[str | None] | None = None,
    score_reasons: Iterable[str] | None = None,
    manual_tags: Iterable[str] | None = None,
    llm_tags: Iterable[str] | None = None,
    available_tags: Iterable[str] | None = None,
    max_count: int = 3,
) -> list[str]:
    allowed = merge_tag_catalog(available_tags)
    manual = filter_allowed_tags(manual_tags or [], allowed)
    llm = filter_allowed_tags(llm_tags or [], allowed)
    inferred = infer_tags_from_text(
        text=build_tag_text(*(text_parts or []), score_reasons=score_reasons),
        task_type=task_type,
        available_tags=allowed,
        manual_tags=manual,
        max_count=max_count,
    )

    if len(manual) >= max_count:
        return manual

    merged = list(manual)
    for tag in dedupe_tags([*llm, *inferred]):
        if tag in merged:
            continue
        if len(merged) >= max_count:
            break
        merged.append(tag)
    return merged
