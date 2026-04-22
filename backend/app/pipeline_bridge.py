from __future__ import annotations

import copy
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from threading import RLock, Thread
from time import monotonic
from uuid import uuid4

from dotenv import load_dotenv

from config import Config
from .db import get_gmail_link, get_outlook_link, get_user_by_id, list_stored_messages, save_messages
from .gmail_service import list_new_messages, list_recent_messages
from .outlook_service import list_new_outlook_messages, list_recent_outlook_messages

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
)
from pipeline.services.pipeline import PriorityPipeline
from pipeline.storage.db import create_engine_from_url, create_schema
from pipeline.storage.repositories import SqlAlchemyPipelineRepository
from pipeline.utils.text import normalize_entity_name

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


def _state_now_iso() -> str:
    return datetime.now().isoformat()


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


def sync_onboarding_context(user_id: int, preferences: str | None = None) -> dict:
    repository = get_pipeline_repository()
    pipeline_user_id = str(user_id)
    current = repository.get_onboarding_context(pipeline_user_id) or OnboardingContext(user_id=pipeline_user_id)
    static_preferences = dict(current.static_preferences)

    if preferences is None:
        user = get_user_by_id(user_id)
        preferences = user["preferences"] if user else None

    if preferences:
        static_preferences["focus_preference"] = preferences

    updated = current.model_copy(
        update={
            "user_id": pipeline_user_id,
            "timezone": current.timezone or "Asia/Singapore",
            "static_preferences": static_preferences,
        }
    )
    repository.save_onboarding_context(updated)
    return updated.model_dump(mode="json")


def list_prioritized_tasks(user_id: int) -> list[dict]:
    cached = _get_cached_value(_TASK_CACHE, user_id)
    if cached is not None:
        return cached
    repository = get_pipeline_repository()
    cards = repository.get_current_task_cards(str(user_id))
    payload = [card.model_dump(mode="json") for card in cards]
    _set_cached_value(_TASK_CACHE, user_id, payload)
    return payload


def remove_prioritized_task(user_id: int, canonical_task_id: str) -> dict:
    repository = get_pipeline_repository()
    removed = repository.dismiss_task_card(str(user_id), canonical_task_id)
    if removed:
        _update_cached_tasks_after_remove(user_id, canonical_task_id)
    return {"success": removed, "canonicalTaskId": canonical_task_id}


def get_profile_snapshot(user_id: int) -> dict:
    cached = _get_cached_value(_PROFILE_CACHE, user_id)
    if cached is not None:
        return cached
    repository = get_pipeline_repository()
    pipeline = get_priority_pipeline()
    profile = repository.get_behavior_profile(str(user_id)) or pipeline.profile_service.create_default_profile(str(user_id))
    payload = profile.model_dump(mode="json")
    _set_cached_value(_PROFILE_CACHE, user_id, payload)
    return payload


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
                result = list_new_messages(user_id)
                summary["gmail"]["mode"] = "new"
            else:
                result = list_recent_messages(user_id, limit=recent_limit)
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


def run_prioritization_for_user(user_id: int, limit: int | None = None) -> dict:
    return _run_pipeline_from_stored_messages(user_id, limit=limit, refresh_sources=True)


def create_manual_task(
    user_id: int,
    *,
    title: str,
    description: str | None = None,
    task_type: str | None = None,
    deadline_at: str | None = None,
    entity_name: str | None = None,
) -> dict:
    pipeline = get_priority_pipeline()
    cleaned_title = title.strip()
    if not cleaned_title:
        raise ValueError("title is required")
    cleaned_description = (description or "").strip()
    parsed_task_type = TaskType(task_type or TaskType.ADMIN.value)
    resolved_entity_name = (entity_name or cleaned_title).strip()
    deadline_iso = _normalize_manual_deadline(deadline_at)

    user = get_user_by_id(user_id)
    source_id = f"manual-{uuid4().hex}"
    save_messages(
        user_id,
        [
            {
                "platform": "manual",
                "source_id": source_id,
                "thread_id": source_id,
                "timestamp_iso": datetime.now().isoformat(),
                "sender_display": user["name"] if user else "You",
                "sender_email": user["email"] if user else None,
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
                        }
                    }
                },
            }
        ],
    )
    pipeline.register_manual_task(
        user_id=str(user_id),
        task_type=parsed_task_type,
        entity_key=normalize_entity_name(resolved_entity_name),
        entity_name=resolved_entity_name,
        entity_type=EntityType.TOPIC,
        deadline_hours=_deadline_hours_from_iso(deadline_iso),
    )
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
    card_payloads = [card.model_dump(mode="json") for card in current_cards]
    _set_cached_value(_TASK_CACHE, user_id, card_payloads)
    if bundle.profile is not None:
        _set_cached_value(_PROFILE_CACHE, user_id, bundle.profile.model_dump(mode="json"))

    logger.info(
        "Ran prioritization pipeline for user_id=%s emails=%s cards=%s run_id=%s",
        user_id,
        len(raw_messages),
        len(bundle.task_cards),
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
    }


def submit_task_feedback(
    user_id: int,
    canonical_task_id: str,
    *,
    action: str,
    direction: str | None = None,
) -> dict:
    pipeline = get_priority_pipeline()
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
    profile = feedback_context.profile or pipeline.profile_service.create_default_profile(pipeline_user_id)
    sender_hash = None
    for sender_id in task_context.sender_ids:
        if sender_id:
            sender_hash = pipeline.profile_service.hash_identity(
                user_salt=profile.user_salt,
                identifier=sender_id,
            )
            break

    event = FeedbackEvent(
        user_id=pipeline_user_id,
        canonical_task_id=canonical_task_id,
        action=feedback_action,
        direction=feedback_direction,
        task_type=task_context.task_type,
        entity_key=task_context.entity_key,
        entity_name=task_context.entity_name,
        entity_type=task_context.entity_type,
        sender_hash=sender_hash,
        deadline_hours=task_context.deadline_hours,
    )
    updated_profile = pipeline.apply_feedback_to_profile(profile, event)
    _set_cached_value(_PROFILE_CACHE, user_id, updated_profile.model_dump(mode="json"))
    if feedback_action == FeedbackAction.ALREADY_DONE:
        repository.dismiss_task_card(pipeline_user_id, canonical_task_id)
        _update_cached_tasks_after_remove(user_id, canonical_task_id)
    return {
        "success": True,
        "feedbackEvent": event.model_dump(mode="json"),
        "profile": updated_profile.model_dump(mode="json"),
        "canonicalTaskId": canonical_task_id,
        "action": feedback_action.value,
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
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError as exc:
        raise ValueError("deadlineAt must be a valid ISO datetime") from exc


def _deadline_hours_from_iso(value: str | None) -> float | None:
    if not value:
        return None
    deadline = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    delta = deadline - datetime.now()
    return max(0.0, delta.total_seconds() / 3600)
