from __future__ import annotations

import copy
import logging
import sys
from pathlib import Path
from threading import RLock, Thread
from time import monotonic
from typing import Any, cast
from uuid import uuid4

from dotenv import load_dotenv

from config import Config
from .calendar_service import clear_calendar_context, parse_calendar_context
from .db import (
    get_gmail_link,
    get_outlook_link,
    get_user_by_id,
    list_stored_messages,
    save_messages,
)
from .gmail_service import list_new_messages, list_recent_messages
from .outlook_service import list_new_outlook_messages, list_recent_outlook_messages
from .telegram_service import send_instant_telegram_alerts
from .time_utils import now_sgt, parse_iso_to_sgt

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = PROJECT_ROOT / "pipeline"
PIPELINE_SRC = PIPELINE_ROOT / "src"

if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))

load_dotenv(PIPELINE_ROOT / ".env", override=False)

from pipeline.config import PipelineSettings
from pipeline.models import (
    EntityType,
    FeedbackAction,
    FeedbackDirection,
    FeedbackEvent,
    OnboardingContext,
    RawMessage,
    TaskType,
    BehaviorProfile,
)
from pipeline.services.pipeline import PriorityPipeline
from pipeline.storage.db import create_engine_from_url, create_schema
from pipeline.storage.repositories import SqlAlchemyPipelineRepository, compute_priority_adjustment
from pipeline.utils.tags import dedupe_tags, merge_tag_catalog

logger = logging.getLogger(__name__)

_PIPELINE_LOCK = RLock()
_PIPELINE_REPOSITORY = None
_PRIORITY_PIPELINE = None
_RECOMPUTE_LOCK = RLock()
_RECOMPUTE_STATES: dict[int, dict] = {}
_DASHBOARD_CACHE_LOCK = RLock()
_TASK_CACHE: dict[int, dict] = {}
_PROFILE_CACHE: dict[int, dict] = {}
_DASHBOARD_CACHE_TTL_SECONDS = 60.0
_ALLOWED_TASK_PATCH_FIELDS = {"title", "description", "deadlineAt", "priorityTier", "status", "tags"}
_ALLOWED_PRIORITY_TIERS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
_ALLOWED_TASK_STATUSES = {"OPEN", "COMPLETED"}
_LEARNING_PRIORITY_INDEX = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _state_now_iso() -> str:
    return now_sgt().isoformat()


def _get_cached_value(cache: dict[int, dict], user_id: int):
    with _DASHBOARD_CACHE_LOCK:
        entry = cache.get(user_id)
        if entry is None:
            return None
        if monotonic() - entry["stored_at"] > _DASHBOARD_CACHE_TTL_SECONDS:
            cache.pop(user_id, None)
            return None
        return copy.deepcopy(entry["value"])


def _set_cached_value(cache: dict[int, dict], user_id: int, value) -> None:
    with _DASHBOARD_CACHE_LOCK:
        cache[user_id] = {"stored_at": monotonic(), "value": copy.deepcopy(value)}


def _invalidate_dashboard_cache(user_id: int) -> None:
    with _DASHBOARD_CACHE_LOCK:
        _TASK_CACHE.pop(user_id, None)
        _PROFILE_CACHE.pop(user_id, None)


def clear_user_runtime_state(user_id: int) -> None:
    _invalidate_dashboard_cache(user_id)
    with _RECOMPUTE_LOCK:
        _RECOMPUTE_STATES.pop(user_id, None)


def _update_cached_tasks_after_remove(user_id: int, canonical_task_id: str) -> None:
    with _DASHBOARD_CACHE_LOCK:
        entry = _TASK_CACHE.get(user_id)
        if entry is None:
            return
        items = [
            item
            for item in entry["value"]
            if item.get("canonical_task_id") != canonical_task_id
        ]
        entry["stored_at"] = monotonic()
        entry["value"] = items


def _get_recompute_state(user_id: int) -> dict:
    state = _RECOMPUTE_STATES.get(user_id)
    if state is None:
        state = {
            "userId": user_id,
            "running": False,
            "pending": False,
            "refreshSources": False,
            "limit": None,
            "lastScheduledAt": None,
            "lastStartedAt": None,
            "lastCompletedAt": None,
            "lastRunId": None,
            "lastTaskCardCount": None,
            "lastError": None,
            "lastReason": None,
        }
        _RECOMPUTE_STATES[user_id] = state
    return state


def get_pipeline_recompute_status(user_id: int) -> dict:
    with _RECOMPUTE_LOCK:
        return dict(_get_recompute_state(user_id))


def schedule_pipeline_recompute(
    user_id: int,
    *,
    refresh_sources: bool = False,
    limit: int | None = None,
    reason: str = "feedback",
) -> dict:
    with _RECOMPUTE_LOCK:
        state = _get_recompute_state(user_id)
        state["lastScheduledAt"] = _state_now_iso()
        state["lastReason"] = reason
        state["refreshSources"] = bool(state["refreshSources"] or refresh_sources)
        if limit is not None:
            current_limit = state["limit"]
            state["limit"] = limit if current_limit is None else max(current_limit, limit)
        if state["running"]:
            state["pending"] = True
            return dict(state)

        state["running"] = True
        thread = Thread(
            target=_pipeline_recompute_worker,
            args=(user_id,),
            name=f"pipeline-recompute-{user_id}",
            daemon=True,
        )
        thread.start()
        return dict(state)


def _pipeline_recompute_worker(user_id: int) -> None:
    while True:
        with _RECOMPUTE_LOCK:
            state = _get_recompute_state(user_id)
            refresh_sources = bool(state["refreshSources"])
            limit = state["limit"]
            state["refreshSources"] = False
            state["limit"] = None
            state["pending"] = False
            state["lastStartedAt"] = _state_now_iso()

        try:
            result = _run_pipeline_from_stored_messages(user_id, limit=limit, refresh_sources=refresh_sources)
        except Exception as exc:  # pragma: no cover - exercised in live integration
            logger.exception("Background pipeline recompute failed for user_id=%s", user_id)
            with _RECOMPUTE_LOCK:
                state = _get_recompute_state(user_id)
                state["lastError"] = str(exc)
                state["lastCompletedAt"] = _state_now_iso()
                should_continue = bool(state["pending"] or state["refreshSources"] or state["limit"] is not None)
                if not should_continue:
                    state["running"] = False
            if should_continue:
                continue
            return

        with _RECOMPUTE_LOCK:
            state = _get_recompute_state(user_id)
            state["lastError"] = None
            state["lastCompletedAt"] = _state_now_iso()
            state["lastRunId"] = result.get("runId")
            state["lastTaskCardCount"] = result.get("taskCardCount")
            should_continue = bool(state["pending"] or state["refreshSources"] or state["limit"] is not None)
            if not should_continue:
                state["running"] = False

        if not should_continue:
            return


def get_pipeline_repository() -> SqlAlchemyPipelineRepository:
    global _PIPELINE_REPOSITORY

    with _PIPELINE_LOCK:
        if _PIPELINE_REPOSITORY is None:
            if not Config.DATABASE_URL:
                raise RuntimeError("DATABASE_URL is missing from backend/.env")
            engine = create_engine_from_url(Config.DATABASE_URL)
            create_schema(engine)
            _PIPELINE_REPOSITORY = SqlAlchemyPipelineRepository(engine)
        return _PIPELINE_REPOSITORY


def get_priority_pipeline() -> PriorityPipeline:
    global _PRIORITY_PIPELINE

    with _PIPELINE_LOCK:
        if _PRIORITY_PIPELINE is None:
            settings = PipelineSettings(sender_hash_pepper=Config.SECRET_KEY)
            _PRIORITY_PIPELINE = PriorityPipeline(get_pipeline_repository(), settings=settings)
        return _PRIORITY_PIPELINE


def _build_static_onboarding_preferences(user: dict | None) -> dict:
    if not user:
        return {}

    static_preferences = {}
    if user.get("performance_time"):
        static_preferences["performance_time"] = user["performance_time"]
    if user.get("important_topic"):
        static_preferences["important_topic"] = user["important_topic"]
    if user.get("prioritise_by"):
        static_preferences["prioritise_by"] = user["prioritise_by"]
    return static_preferences


def _get_profile_seed_context(
    repository: SqlAlchemyPipelineRepository,
    user_id: int,
    *,
    user: dict[str, Any] | None = None,
) -> OnboardingContext:
    pipeline_user_id = str(user_id)
    context = repository.get_onboarding_context(pipeline_user_id) or OnboardingContext(user_id=pipeline_user_id)
    expected_static_preferences = {
        **dict(context.static_preferences),
        **_build_static_onboarding_preferences(user or get_user_by_id(user_id)),
    }
    if expected_static_preferences != dict(context.static_preferences):
        context = context.model_copy(update={"static_preferences": expected_static_preferences})
    return context


def sync_onboarding_context(user_id: int) -> dict:
    repository = get_pipeline_repository()
    pipeline_user_id = str(user_id)
    current = repository.get_onboarding_context(pipeline_user_id) or OnboardingContext(user_id=pipeline_user_id)
    user = get_user_by_id(user_id)
    static_preferences = {
        **dict(current.static_preferences),
        **_build_static_onboarding_preferences(user),
    }

    updated = current.model_copy(
        update={
            "user_id": pipeline_user_id,
            "timezone": current.timezone or "Asia/Singapore",
            "static_preferences": static_preferences,
        }
    )
    repository.save_onboarding_context(updated)
    return updated.model_dump(mode="json")


def get_onboarding_context_snapshot(user_id: int, *, user: dict[str, Any] | None = None) -> dict:
    repository = get_pipeline_repository()
    context = _get_profile_seed_context(repository, user_id, user=user)
    persisted = repository.get_onboarding_context(str(user_id))
    if persisted is None or dict(persisted.static_preferences) != dict(context.static_preferences):
        repository.save_onboarding_context(context)
    return context.model_dump(mode="json")


def save_calendar_context(user_id: int, *, filename: str, file_bytes: bytes) -> dict:
    repository = get_pipeline_repository()
    pipeline_user_id = str(user_id)
    current = repository.get_onboarding_context(pipeline_user_id) or OnboardingContext(user_id=pipeline_user_id)
    parsed = parse_calendar_context(
        filename=filename,
        file_bytes=file_bytes,
        timezone_name=current.timezone or "Asia/Singapore",
    )
    updated = current.model_copy(
        update={
            "busy_windows": parsed["busy_windows"],
            "recurring_task_notes": parsed["recurring_task_notes"],
            "timetable_summary": parsed["timetable_summary"],
            "calendar_source": parsed["calendar_source"],
        }
    )
    repository.save_onboarding_context(updated)
    _invalidate_dashboard_cache(user_id)
    return updated.model_dump(mode="json")


def remove_calendar_context(user_id: int) -> dict:
    repository = get_pipeline_repository()
    pipeline_user_id = str(user_id)
    current = repository.get_onboarding_context(pipeline_user_id) or OnboardingContext(user_id=pipeline_user_id)
    cleared = clear_calendar_context()
    updated = current.model_copy(
        update={
            "busy_windows": cleared["busy_windows"],
            "recurring_task_notes": cleared["recurring_task_notes"],
            "timetable_summary": cleared["timetable_summary"],
            "calendar_source": cleared["calendar_source"],
        }
    )
    repository.save_onboarding_context(updated)
    _invalidate_dashboard_cache(user_id)
    return updated.model_dump(mode="json")


def get_available_tags(user_id: int) -> list[str]:
    repository = get_pipeline_repository()
    return merge_tag_catalog(repository.get_custom_tags(str(user_id)))


def _list_dashboard_task_cards(repository: SqlAlchemyPipelineRepository, user_id: str):
    return [
        *repository.get_current_task_cards(user_id),
        *repository.get_completed_task_cards(user_id),
    ]


def _build_dashboard_items(repository: SqlAlchemyPipelineRepository, user_id: int) -> list[dict]:
    items = [
        card.model_dump(mode="json")
        for card in _list_dashboard_task_cards(repository, str(user_id))
    ]
    _set_cached_value(_TASK_CACHE, user_id, items)
    return items


def _task_payload_is_completed(task: dict) -> bool:
    return str(task.get("status") or "").lower() == "completed"


def list_prioritized_tasks(user_id: int) -> list[dict]:
    cached = _get_cached_value(_TASK_CACHE, user_id)
    if cached is not None:
        return cached
    repository = get_pipeline_repository()
    return _build_dashboard_items(repository, user_id)


def _resolve_feedback_profile_inputs(
    user_id: int,
    feedback_context,
) -> tuple[PriorityPipeline, str, BehaviorProfile, str | None]:
    pipeline = get_priority_pipeline()
    repository = get_pipeline_repository()
    pipeline_user_id = str(user_id)
    onboarding = _get_profile_seed_context(repository, user_id)
    profile = feedback_context.profile or pipeline.profile_service.create_default_profile(
        pipeline_user_id,
        onboarding,
    )
    sender_hash = None
    for sender_id in feedback_context.task.sender_ids:
        if sender_id:
            sender_hash = pipeline.profile_service.hash_identity(
                user_salt=profile.user_salt,
                identifier=sender_id,
            )
            break
    return pipeline, pipeline_user_id, profile, sender_hash


def _apply_profile_feedback(
    user_id: int,
    feedback_context,
    *,
    action: FeedbackAction,
    direction: FeedbackDirection | None = None,
    priority_after=None,
    incremental_priority_delta: int = 0,
    profile: BehaviorProfile | None = None,
):
    pipeline, pipeline_user_id, current_profile, sender_hash = _resolve_feedback_profile_inputs(
        user_id,
        feedback_context,
    )
    if profile is not None:
        current_profile = profile

    task_context = feedback_context.task
    event = FeedbackEvent(
        user_id=pipeline_user_id,
        canonical_task_id=task_context.canonical_task_id,
        action=action,
        direction=direction,
        task_type=task_context.task_type,
        entity_key=task_context.entity_key,
        entity_name=task_context.entity_name,
        entity_type=task_context.entity_type,
        sender_hash=sender_hash,
        deadline_hours=task_context.deadline_hours,
        task_tags=task_context.task_tags,
        priority_before=task_context.effective_priority_tier,
        priority_after=priority_after or task_context.effective_priority_tier,
        incremental_priority_delta=incremental_priority_delta,
    )
    updated_profile = pipeline.apply_feedback_to_profile(current_profile, event)
    _set_cached_value(_PROFILE_CACHE, user_id, updated_profile.model_dump(mode="json"))
    return updated_profile, event


def _priority_feedback_change(task_context, target_priority_tier: str):
    current_priority = task_context.effective_priority_tier.value
    if target_priority_tier == current_priority:
        return None

    current_index = _LEARNING_PRIORITY_INDEX[current_priority]
    target_index = _LEARNING_PRIORITY_INDEX[target_priority_tier]
    suggested_index = _LEARNING_PRIORITY_INDEX[task_context.suggested_priority_tier.value]
    direction = (
        FeedbackDirection.TOO_LOW
        if target_index > current_index
        else FeedbackDirection.TOO_HIGH
    )
    new_delta = target_index - suggested_index
    incremental_delta = new_delta - task_context.applied_priority_delta
    return {
        "direction": direction,
        "priority_after": task_context.effective_priority_tier.__class__(target_priority_tier),
        "incremental_priority_delta": incremental_delta,
    }


def remove_prioritized_task(user_id: int, canonical_task_id: str) -> dict:
    repository = get_pipeline_repository()
    feedback_context = repository.get_feedback_update_context(str(user_id), canonical_task_id)
    if feedback_context is None:
        return {"success": False, "canonicalTaskId": canonical_task_id}
    action = (
        FeedbackAction.REJECT
        if feedback_context.task.status.value == "pending_review"
        else FeedbackAction.DELETE
    )
    updated_profile, _ = _apply_profile_feedback(
        user_id,
        feedback_context,
        action=action,
    )
    repository.apply_task_action(str(user_id), canonical_task_id, action=action)
    _invalidate_dashboard_cache(user_id)
    return {
        "success": True,
        "canonicalTaskId": canonical_task_id,
        "action": action.value,
        "profile": updated_profile.model_dump(mode="json"),
    }


def update_prioritized_task_tags(
    user_id: int,
    canonical_task_id: str,
    *,
    tags: list[str] | None = None,
) -> dict:
    repository = get_pipeline_repository()
    if tags is not None and not isinstance(tags, list):
        raise ValueError("tags must be a list.")

    normalized_tags = dedupe_tags(tags or [])
    updated_card = repository.replace_task_tags(
        str(user_id),
        canonical_task_id,
        tags=normalized_tags,
    )
    if updated_card is None:
        raise LookupError("Task card not found for this user.")

    if normalized_tags:
        repository.upsert_custom_tags(str(user_id), normalized_tags)

    items = _build_dashboard_items(repository, user_id)
    return {
        "success": True,
        "canonicalTaskId": canonical_task_id,
        "task": updated_card.model_dump(mode="json"),
        "items": items,
        "availableTags": get_available_tags(user_id),
    }


def update_prioritized_task(
    user_id: int,
    canonical_task_id: str,
    *,
    updates: dict,
) -> dict:
    if not isinstance(updates, dict):
        raise ValueError("Task updates must be a JSON object.")

    unknown_fields = sorted(set(updates) - _ALLOWED_TASK_PATCH_FIELDS)
    if unknown_fields:
        raise ValueError(f"Unsupported task fields: {', '.join(unknown_fields)}")
    if not updates:
        raise ValueError("At least one editable field is required.")

    normalized_updates: dict[str, object] = {}

    if "title" in updates:
        title = updates.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title cannot be blank.")
        normalized_updates["title"] = title.strip()

    if "description" in updates:
        description = updates.get("description")
        if not isinstance(description, str):
            raise ValueError("description must be a string.")
        normalized_updates["description"] = description

    if "deadlineAt" in updates:
        deadline_at = updates.get("deadlineAt")
        if deadline_at in {None, ""}:
            normalized_updates["deadline_at"] = None
        elif not isinstance(deadline_at, str):
            raise ValueError("deadlineAt must be a valid ISO datetime or null.")
        else:
            normalized_updates["deadline_at"] = _normalize_manual_deadline(deadline_at)

    if "priorityTier" in updates:
        priority_tier = updates.get("priorityTier")
        if not isinstance(priority_tier, str):
            raise ValueError("priorityTier must be a string.")
        normalized_priority = priority_tier.strip().upper()
        if normalized_priority not in _ALLOWED_PRIORITY_TIERS:
            raise ValueError("priorityTier must be one of CRITICAL, HIGH, MEDIUM, or LOW.")
        normalized_updates["priority_tier"] = normalized_priority

    if "status" in updates:
        status = updates.get("status")
        if not isinstance(status, str):
            raise ValueError("status must be a string.")
        normalized_status = status.strip().upper()
        if normalized_status not in _ALLOWED_TASK_STATUSES:
            raise ValueError("status must be OPEN or COMPLETED.")
        normalized_updates["status"] = normalized_status

    if "tags" in updates:
        tags = updates.get("tags")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError("tags must be an array of strings.")
        normalized_updates["tags"] = dedupe_tags(tags)

    repository = get_pipeline_repository()
    feedback_context = repository.get_feedback_update_context(str(user_id), canonical_task_id)
    if feedback_context is None:
        raise LookupError("Task card not found for this user.")

    updated_profile = None
    if "priority_tier" in normalized_updates:
        priority_feedback = _priority_feedback_change(
            feedback_context.task,
            str(normalized_updates["priority_tier"]),
        )
        if priority_feedback is not None:
            updated_profile, _ = _apply_profile_feedback(
                user_id,
                feedback_context,
                action=FeedbackAction.WRONG_PRIORITY,
                direction=priority_feedback["direction"],
                priority_after=priority_feedback["priority_after"],
                incremental_priority_delta=priority_feedback["incremental_priority_delta"],
                profile=updated_profile,
            )

    if (
        normalized_updates.get("status") == "COMPLETED"
        and feedback_context.task.status.value != "completed"
    ):
        updated_profile, _ = _apply_profile_feedback(
            user_id,
            feedback_context,
            action=FeedbackAction.COMPLETED,
            profile=updated_profile,
        )

    updated_card = repository.update_task(
        str(user_id),
        canonical_task_id,
        updates=normalized_updates,
    )
    if updated_card is None:
        raise LookupError("Task card not found for this user.")

    tags_update = cast(list[str] | None, normalized_updates.get("tags"))
    if tags_update:
        repository.upsert_custom_tags(str(user_id), tags_update)

    items = _build_dashboard_items(repository, user_id)
    profile = (
        updated_profile.model_dump(mode="json")
        if updated_profile is not None
        else get_profile_snapshot(user_id)
    )
    return {
        "success": True,
        "taskId": canonical_task_id,
        "task": updated_card.model_dump(mode="json"),
        "items": items,
        "profile": profile,
        "availableTags": get_available_tags(user_id),
    }


def get_profile_snapshot(user_id: int) -> dict:
    cached = _get_cached_value(_PROFILE_CACHE, user_id)
    if cached is not None:
        return cached
    repository = get_pipeline_repository()
    pipeline = get_priority_pipeline()
    onboarding = _get_profile_seed_context(repository, user_id)
    profile = repository.get_behavior_profile(str(user_id)) or pipeline.profile_service.create_default_profile(
        str(user_id),
        onboarding,
    )
    payload = profile.model_dump(mode="json")
    _set_cached_value(_PROFILE_CACHE, user_id, payload)
    return payload


def get_task_statistics_snapshot(user_id: int) -> dict:
    task_cards = [task for task in list_prioritized_tasks(user_id) if not _task_payload_is_completed(task)]
    profile = get_profile_snapshot(user_id)

    total_task_cards = len(task_cards)
    critical_tasks = sum(
        1 for task in task_cards if task.get("priority_tier") == "CRITICAL"
    )
    high_priority_tasks = sum(
        1 for task in task_cards if task.get("priority_tier") == "HIGH"
    )
    due_within_24h = sum(
        1
        for task in task_cards
        if isinstance(task.get("deadline_hours"), (int, float))
        and task["deadline_hours"] <= 24
    )
    confidence_values = [
        float(task["confidence"])
        for task in task_cards
        if isinstance(task.get("confidence"), (int, float))
    ]
    average_confidence = (
        sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    )

    priority_distribution = _build_distribution_rows(
        task_cards,
        lambda task: task.get("priority_tier"),
    )
    action_window_distribution = _build_distribution_rows(
        task_cards,
        lambda task: task.get("action_window"),
    )
    platform_distribution = _build_platform_distribution(task_cards)

    nearest_deadlines = sorted(
        [
            task
            for task in task_cards
            if isinstance(task.get("deadline_hours"), (int, float))
        ],
        key=lambda task: task["deadline_hours"],
    )[:4]
    strongest_signals = sorted(
        task_cards,
        key=lambda task: float(task.get("confidence") or 0),
        reverse=True,
    )[:4]

    return {
        "summary": {
            "totalTaskCards": total_task_cards,
            "criticalTasks": critical_tasks,
            "highPriorityTasks": high_priority_tasks,
            "dueWithin24Hours": due_within_24h,
            "averageConfidence": average_confidence,
            "profileConfidence": float(profile.get("confidence") or 0),
        },
        "distributions": {
            "priorityTiers": priority_distribution,
            "actionWindows": action_window_distribution,
            "platformMix": platform_distribution,
        },
        "nearestDeadlines": nearest_deadlines,
        "strongestSignals": strongest_signals,
        "profile": profile,
    }


def refresh_linked_email_sources(user_id: int, *, recent_limit: int = 20) -> dict:
    summary = {
        "gmail": {"linked": False, "mode": None, "fetchedCount": 0, "error": None},
        "outlook": {"linked": False, "mode": None, "fetchedCount": 0, "error": None},
    }

    gmail_link = get_gmail_link(user_id)
    if gmail_link:
        summary["gmail"]["linked"] = True
        try:
            if gmail_link.get("history_id"):
                result = list_new_messages(user_id, link=gmail_link)
                summary["gmail"]["mode"] = "new"
            else:
                result = list_recent_messages(user_id, limit=recent_limit, link=gmail_link)
                summary["gmail"]["mode"] = "recent"
            summary["gmail"]["fetchedCount"] = len(result.get("messages", []))
        except Exception as exc:
            logger.exception("Gmail refresh failed for user_id=%s", user_id)
            summary["gmail"]["error"] = str(exc)

    outlook_link = get_outlook_link(user_id)
    if outlook_link:
        summary["outlook"]["linked"] = True
        try:
            if outlook_link.get("last_received_at"):
                result = list_new_outlook_messages(user_id)
                summary["outlook"]["mode"] = "new"
            else:
                result = list_recent_outlook_messages(user_id, limit=recent_limit)
                summary["outlook"]["mode"] = "recent"
            summary["outlook"]["fetchedCount"] = len(result.get("messages", []))
        except Exception as exc:
            logger.exception("Outlook refresh failed for user_id=%s", user_id)
            summary["outlook"]["error"] = str(exc)

    return summary


def _email_sync_has_new_messages(summary: dict) -> bool:
    for provider in ("gmail", "outlook"):
        provider_summary = summary.get(provider) or {}
        if int(provider_summary.get("fetchedCount") or 0) > 0:
            return True
    return False


def _build_distribution_rows(items: list[dict], get_label) -> list[dict]:
    counts: dict[str, int] = {}
    for item in items:
        label = get_label(item)
        if not label:
            continue
        counts[str(label)] = counts.get(str(label), 0) + 1

    return [
        {"label": label, "count": count}
        for label, count in sorted(
            counts.items(),
            key=lambda entry: (-entry[1], entry[0]),
        )
    ]


def _build_platform_distribution(task_cards: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for task in task_cards:
        platforms = task.get("platforms_seen")
        if isinstance(platforms, list) and platforms:
            for platform in platforms:
                if not platform:
                    continue
                counts[str(platform)] = counts.get(str(platform), 0) + 1
        else:
            counts["email"] = counts.get("email", 0) + 1

    return [
        {"label": label, "count": count}
        for label, count in sorted(
            counts.items(),
            key=lambda entry: (-entry[1], entry[0]),
        )
    ]


def _summarize_llm_provider(decisions) -> str:
    providers = sorted(
        {
            str(getattr(decision, "provider", "")).strip().lower()
            for decision in decisions
            if getattr(decision, "provider", None)
        }
    )
    if not providers:
        return "unknown"
    if len(providers) == 1:
        return providers[0]
    return ",".join(providers)


def run_prioritization_for_user(user_id: int, limit: int | None = None) -> dict:
    return _run_pipeline_from_stored_messages(user_id, limit=limit, refresh_sources=True)


def run_background_refresh_for_user(user_id: int, limit: int | None = None) -> dict:
    email_sync = refresh_linked_email_sources(user_id, recent_limit=limit or 20)
    if not _email_sync_has_new_messages(email_sync):
        return {
            "pipelineRan": False,
            "skipReason": "no_new_messages",
            "runId": None,
            "rawMessageCount": 0,
            "signalCount": 0,
            "canonicalTaskCount": 0,
            "taskCardCount": 0,
            "emailSync": email_sync,
            "items": list_prioritized_tasks(user_id),
            "availableTags": get_available_tags(user_id),
        }

    result = _run_pipeline_from_stored_messages(
        user_id,
        limit=limit,
        refresh_sources=False,
    )
    result["pipelineRan"] = True
    result["emailSync"] = email_sync
    return result


def create_manual_task(
    user_id: int,
    *,
    title: str,
    description: str | None = None,
    task_type: str | None = None,
    deadline_at: str | None = None,
    entity_name: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    repository = get_pipeline_repository()
    cleaned_title = title.strip()
    if not cleaned_title:
        raise ValueError("title is required")
    cleaned_description = (description or "").strip()
    parsed_task_type = TaskType(task_type or TaskType.ADMIN.value)
    resolved_entity_name = (entity_name or cleaned_title).strip()
    deadline_iso = _normalize_manual_deadline(deadline_at)
    normalized_tags = dedupe_tags(tags or [])

    user = get_user_by_id(user_id)
    source_id = f"manual-{uuid4().hex}"
    save_messages(
        user_id,
        [
            {
                "platform": "manual",
                "source_id": source_id,
                "thread_id": source_id,
                "timestamp_iso": now_sgt().isoformat(),
                "sender_display": user["username"] if user else "You",
                "sender_email": None,
                "subject": cleaned_title,
                "snippet": cleaned_description or cleaned_title,
                "body_text": "\n".join(part for part in [cleaned_title, cleaned_description] if part),
                "provider_metadata": {
                    "extra": {
                        "manual_task": {
                            "task_type": parsed_task_type.value,
                            "entity_name": resolved_entity_name,
                            "entity_type": EntityType.TOPIC.value,
                            "deadline_iso": deadline_iso,
                            "tags": normalized_tags,
                        }
                    }
                },
            }
        ],
    )
    if normalized_tags:
        repository.upsert_custom_tags(str(user_id), normalized_tags)
    result = _run_pipeline_from_stored_messages(user_id, refresh_sources=False)
    result["manualTaskSourceId"] = source_id
    result["profile"] = get_profile_snapshot(user_id)
    return result


def _run_pipeline_from_stored_messages(
    user_id: int,
    *,
    limit: int | None = None,
    refresh_sources: bool,
) -> dict:
    pipeline = get_priority_pipeline()
    repository = get_pipeline_repository()
    previous_task_ids = {
        card.canonical_task_id
        for card in repository.get_current_task_cards(str(user_id))
    }
    sync_onboarding_context(user_id)
    email_sync = (
        refresh_linked_email_sources(user_id, recent_limit=limit or 20)
        if refresh_sources
        else {
            "gmail": {"linked": False, "mode": None, "fetchedCount": 0, "error": None},
            "outlook": {"linked": False, "mode": None, "fetchedCount": 0, "error": None},
        }
    )

    stored_rows = list_stored_messages(user_id, limit=limit)
    raw_messages = [_row_to_raw_message(user_id, row) for row in stored_rows]
    bundle = pipeline.run_messages(str(user_id), raw_messages)
    current_cards = repository.get_current_task_cards(str(user_id))
    card_payloads = _build_dashboard_items(repository, user_id)
    new_task_payloads = [
        card.model_dump(mode="json")
        for card in current_cards
        if card.canonical_task_id not in previous_task_ids
    ]
    if bundle.profile is not None:
        _set_cached_value(_PROFILE_CACHE, user_id, bundle.profile.model_dump(mode="json"))

    if new_task_payloads:
        try:
            send_instant_telegram_alerts(user_id, new_task_payloads)
        except Exception:  # pragma: no cover - defensive guard for live failures
            logger.exception(
                "Telegram alert dispatch failed after pipeline run for user_id=%s",
                user_id,
            )

    logger.info(
        "Ran prioritization pipeline for user_id=%s emails=%s cards=%s provider=%s run_id=%s",
        user_id,
        len(raw_messages),
        len(bundle.task_cards),
        _summarize_llm_provider(bundle.decisions),
        bundle.run_id,
    )
    return {
        "runId": bundle.run_id,
        "rawMessageCount": len(raw_messages),
        "signalCount": len(bundle.signals),
        "canonicalTaskCount": len(bundle.canonical_tasks),
        "taskCardCount": len(bundle.task_cards),
        "emailSync": email_sync,
        "items": card_payloads,
        "availableTags": get_available_tags(user_id),
    }


def submit_task_feedback(
    user_id: int,
    canonical_task_id: str,
    *,
    action: str,
    direction: str | None = None,
) -> dict:
    repository = get_pipeline_repository()
    pipeline_user_id = str(user_id)

    feedback_action = FeedbackAction(action)
    feedback_direction = FeedbackDirection(direction) if direction else None
    if feedback_action == FeedbackAction.WRONG_PRIORITY and feedback_direction is None:
        raise ValueError("direction is required when action is WRONG_PRIORITY")

    feedback_context = repository.get_feedback_update_context(pipeline_user_id, canonical_task_id)
    if feedback_context is None:
        raise LookupError("Task card not found for this user.")

    task_context = feedback_context.task
    if feedback_action == FeedbackAction.WRONG_PRIORITY and feedback_direction is not None:
        priority_after, _, incremental_delta = compute_priority_adjustment(
            suggested_priority_tier=task_context.suggested_priority_tier,
            effective_priority_tier=task_context.effective_priority_tier,
            applied_priority_delta=task_context.applied_priority_delta,
            direction=feedback_direction,
        )
        updated_profile, event = _apply_profile_feedback(
            user_id,
            feedback_context,
            action=feedback_action,
            direction=feedback_direction,
            priority_after=priority_after,
            incremental_priority_delta=incremental_delta,
        )
    else:
        updated_profile, event = _apply_profile_feedback(
            user_id,
            feedback_context,
            action=feedback_action,
            direction=feedback_direction,
        )
    repository.apply_task_action(
        pipeline_user_id,
        canonical_task_id,
        action=feedback_action,
        direction=feedback_direction,
    )
    items = _build_dashboard_items(repository, user_id)
    return {
        "success": True,
        "feedbackEvent": event.model_dump(mode="json"),
        "profile": updated_profile.model_dump(mode="json"),
        "canonicalTaskId": canonical_task_id,
        "action": feedback_action.value,
        "items": items,
    }


def _row_to_raw_message(user_id: int, row: dict) -> RawMessage:
    payload = dict(row)
    payload["user_id"] = str(user_id)
    payload["timestamp_iso"] = payload["timestamp_iso"].isoformat() if payload.get("timestamp_iso") else None
    return RawMessage.model_validate(payload)


def _normalize_manual_deadline(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parse_iso_to_sgt(value)
        return parsed.isoformat() if parsed else None
    except ValueError as exc:
        raise ValueError("deadlineAt must be a valid ISO datetime") from exc


def _deadline_hours_from_iso(value: str | None) -> float | None:
    if not value:
        return None
    deadline = parse_iso_to_sgt(value)
    if deadline is None:
        return None
    delta = deadline - now_sgt()
    return max(0.0, delta.total_seconds() / 3600)
