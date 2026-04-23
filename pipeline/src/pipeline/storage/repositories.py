from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pipeline.config import PipelineSettings
from pipeline.models import (
    BehaviorProfile,
    CanonicalTask,
    EntityAlias,
    FeedbackAction,
    FeedbackDirection,
    FeedbackEvent,
    LlmDecision,
    OnboardingContext,
    PrioritizedTaskCard,
    RawMessage,
    TaskDecision,
    TaskOrigin,
    TaskStatus,
)
from pipeline.models.enums import EntityType, PriorityTier, TaskType
from pipeline.services.postprocess import PostProcessor
from pipeline.storage.tables import PipelineTaskRecord, PipelineUserStateRecord, StoredEmailRecord
from pipeline.utils.tags import dedupe_tags
from pipeline.utils.time import utc_now_naive


_SORT_PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_LEARNING_PRIORITY_INDEX = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_DISPLAY_POST_PROCESSOR = PostProcessor(PipelineSettings())


def _sort_task_cards(cards: list[PrioritizedTaskCard]) -> list[PrioritizedTaskCard]:
    return sorted(
        cards,
        key=lambda card: (
            _SORT_PRIORITY_ORDER.get(card.effective_priority_tier.value, 99),
            card.deadline_hours if card.deadline_hours is not None else float("inf"),
            card.task_title or "",
        ),
    )


def _shift_priority_tier(
    priority_tier: PriorityTier,
    direction: FeedbackDirection,
) -> PriorityTier:
    ordered_tiers = [
        PriorityTier.CRITICAL,
        PriorityTier.HIGH,
        PriorityTier.MEDIUM,
        PriorityTier.LOW,
    ]
    current_index = ordered_tiers.index(priority_tier)
    if direction == FeedbackDirection.TOO_LOW:
        next_index = max(0, current_index - 1)
    else:
        next_index = min(len(ordered_tiers) - 1, current_index + 1)
    return ordered_tiers[next_index]


def compute_priority_adjustment(
    *,
    suggested_priority_tier: PriorityTier,
    effective_priority_tier: PriorityTier,
    applied_priority_delta: int,
    direction: FeedbackDirection,
) -> tuple[PriorityTier, int, int]:
    new_effective = _shift_priority_tier(effective_priority_tier, direction)
    new_delta = _LEARNING_PRIORITY_INDEX[new_effective.value] - _LEARNING_PRIORITY_INDEX[suggested_priority_tier.value]
    incremental_delta = new_delta - applied_priority_delta
    return new_effective, new_delta, incremental_delta


def _enrich_canonical_task(task: CanonicalTask) -> CanonicalTask:
    return task


def _enrich_task_card(card: PrioritizedTaskCard, task: CanonicalTask) -> PrioritizedTaskCard:
    needs_title = not card.task_title or card.task_title.strip().lower() in {"untitled task", "untitled"}
    if (
        not needs_title
        and card.entity_name
        and card.task_title
        and card.task_title.strip().lower() == card.entity_name.strip().lower()
    ):
        needs_title = True

    task_title = card.task_title
    if needs_title:
        task_title = _DISPLAY_POST_PROCESSOR._build_task_title(task)

    needs_description = (
        not card.task_description
        or card.task_description.startswith("Related to ")
        or card.task_description.startswith("Signals:")
    )
    task_description = card.task_description
    if needs_description:
        task_description = _DISPLAY_POST_PROCESSOR._build_task_description(
            task,
            task_title=task_title,
        )
    source_snippet = card.source_snippet or _DISPLAY_POST_PROCESSOR._select_best_preview(task)
    source_subject = card.source_subject or task.representative_subject
    source_sender = card.source_sender or task.representative_sender_display
    source_timestamp_iso = (
        card.source_timestamp_iso
        or (task.representative_timestamp.isoformat() if task.representative_timestamp else None)
    )

    return card.model_copy(
        update={
            "task_title": task_title,
            "task_description": task_description,
            "source_subject": source_subject,
            "source_snippet": source_snippet,
            "source_sender": source_sender,
            "source_timestamp_iso": source_timestamp_iso,
        }
    )


def _task_card_needs_hydration(card: PrioritizedTaskCard) -> bool:
    title = (card.task_title or "").strip().lower()
    entity_name = (card.entity_name or "").strip().lower()
    description = (card.task_description or "").strip()

    if not title or title in {"untitled task", "untitled"}:
        return True
    if entity_name and title == entity_name:
        return True
    if not description or description.startswith("Related to ") or description.startswith("Signals:"):
        return True
    if not (card.source_subject or card.source_snippet or card.source_sender):
        return True
    return False


def _payload_for_task(
    *,
    task_card: PrioritizedTaskCard,
    canonical_task: CanonicalTask,
    llm_decision: LlmDecision | None,
) -> dict[str, Any]:
    return {
        "task_card": task_card.model_dump(mode="json"),
        "canonical_task": canonical_task.model_dump(mode="json"),
        "llm_decision": None if llm_decision is None else llm_decision.model_dump(mode="json"),
    }


def _get_tag_override_state(payload: dict[str, Any] | None) -> dict[str, list[str]]:
    if not isinstance(payload, dict):
        return {"added": [], "removed": [], "generated": []}
    overrides = payload.get("tag_overrides")
    if not isinstance(overrides, dict):
        return {"added": [], "removed": [], "generated": []}
    return {
        "added": dedupe_tags(overrides.get("added") or []),
        "removed": dedupe_tags(overrides.get("removed") or []),
        "generated": dedupe_tags(overrides.get("generated") or []),
    }


def _set_tag_override_state(
    payload: dict[str, Any],
    *,
    added_tags: list[str],
    removed_tags: list[str],
    generated_tags: list[str],
) -> dict[str, Any]:
    updated = dict(payload or {})
    if added_tags or removed_tags or generated_tags:
        updated["tag_overrides"] = {
            "added": dedupe_tags(added_tags),
            "removed": dedupe_tags(removed_tags),
            "generated": dedupe_tags(generated_tags),
        }
    else:
        updated.pop("tag_overrides", None)
    return updated


def _apply_tag_overrides(generated_tags: list[str], payload: dict[str, Any] | None) -> list[str]:
    overrides = _get_tag_override_state(payload)
    removed = set(overrides["removed"])
    effective = [
        tag
        for tag in dedupe_tags([*generated_tags, *overrides["added"]])
        if tag not in removed
    ]
    return effective


def _get_edit_override_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    overrides = payload.get("edit_overrides")
    if not isinstance(overrides, dict):
        return {}

    normalized: dict[str, Any] = {}
    title = overrides.get("title")
    if isinstance(title, str):
        cleaned_title = title.strip()
        if cleaned_title:
            normalized["title"] = cleaned_title

    if "description" in overrides:
        description = overrides.get("description")
        if isinstance(description, str):
            normalized["description"] = description
        elif description is None:
            normalized["description"] = ""

    if "deadline_at" in overrides:
        deadline_value = overrides.get("deadline_at")
        if deadline_value in {None, ""}:
            normalized["deadline_at"] = None
        elif isinstance(deadline_value, str):
            parsed_deadline = _parse_dt(deadline_value)
            if parsed_deadline is not None:
                normalized["deadline_at"] = parsed_deadline.isoformat()

    return normalized


def _set_edit_override_state(payload: dict[str, Any], *, overrides: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload or {})
    normalized = _get_edit_override_state({"edit_overrides": overrides})
    if normalized:
        updated["edit_overrides"] = normalized
    else:
        updated.pop("edit_overrides", None)
    return updated


def _deadline_hours_from_iso(value: str | None) -> float | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    delta = parsed.replace(tzinfo=None) - utc_now_naive()
    return max(0.0, delta.total_seconds() / 3600)


def _apply_edit_overrides_to_task(task: CanonicalTask, payload: dict[str, Any] | None) -> CanonicalTask:
    overrides = _get_edit_override_state(payload)
    if "deadline_at" not in overrides:
        return task
    deadline_at = _parse_dt(overrides["deadline_at"])
    return task.model_copy(
        update={
            "deadline_at": deadline_at,
            "deadline_hours": _deadline_hours_from_iso(overrides["deadline_at"]),
        }
    )


def _apply_edit_overrides_to_card(card: PrioritizedTaskCard, payload: dict[str, Any] | None) -> PrioritizedTaskCard:
    overrides = _get_edit_override_state(payload)
    if not overrides:
        return card

    update: dict[str, Any] = {}
    if "title" in overrides:
        update["task_title"] = overrides["title"]
    if "description" in overrides:
        update["task_description"] = overrides["description"]
    if "deadline_at" in overrides:
        update["deadline_at_iso"] = overrides["deadline_at"]
        update["deadline_hours"] = _deadline_hours_from_iso(overrides["deadline_at"])

    return card.model_copy(update=update) if update else card


def _priority_delta_for_tiers(*, suggested: PriorityTier, effective: PriorityTier) -> int:
    return _LEARNING_PRIORITY_INDEX[effective.value] - _LEARNING_PRIORITY_INDEX[suggested.value]


def _parse_payload_card(payload: dict[str, Any]) -> PrioritizedTaskCard | None:
    task_card_payload = payload.get("task_card") if isinstance(payload, dict) else None
    if not isinstance(task_card_payload, dict):
        return None
    return PrioritizedTaskCard.model_validate(task_card_payload)


def _parse_payload_task(payload: dict[str, Any]) -> CanonicalTask | None:
    task_payload = payload.get("canonical_task") if isinstance(payload, dict) else None
    if not isinstance(task_payload, dict):
        return None
    return CanonicalTask.model_validate(task_payload)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stored_email_to_raw_message(row: StoredEmailRecord) -> RawMessage:
    return RawMessage(
        user_id=str(row.user_id),
        platform=row.platform,
        source_id=row.source_id,
        thread_id=row.thread_id,
        timestamp_iso=row.timestamp_iso.isoformat() if row.timestamp_iso else None,
        label_ids=row.label_ids or [],
        sender_id=row.sender_id,
        sender_display=row.sender_display,
        sender_email=row.sender_email,
        sender_domain=row.sender_domain,
        subject=row.subject,
        snippet=row.snippet,
        body_text=row.body_text or "",
        body_html_present=bool(row.body_html_present),
        attachments_present=bool(row.attachments_present),
        mime_parts=row.mime_parts or [],
        provider_metadata=row.provider_metadata or {},
        from_raw=row.from_raw,
        to_raw=row.to_raw,
        cc_raw=row.cc_raw,
        bcc_raw=row.bcc_raw,
    )


def _row_to_card(row: PipelineTaskRecord) -> PrioritizedTaskCard | None:
    card = _parse_payload_card(row.payload or {})
    if card is None:
        return None
    card = _apply_edit_overrides_to_card(card, row.payload or {})
    return card.model_copy(
        update={
            "status": TaskStatus(row.status),
            "priority_tier": PriorityTier(row.effective_priority_tier),
            "suggested_priority_tier": PriorityTier(row.suggested_priority_tier),
            "effective_priority_tier": PriorityTier(row.effective_priority_tier),
            "applied_priority_delta": row.applied_priority_delta,
            "deadline_hours": row.deadline_hours,
            "tags": dedupe_tags(row.tags or card.tags),
            "confidence": row.confidence,
        }
    )


def _row_to_task(row: PipelineTaskRecord) -> CanonicalTask | None:
    task = _parse_payload_task(row.payload or {})
    if task is None:
        return None
    task = _apply_edit_overrides_to_task(task, row.payload or {})
    return _enrich_canonical_task(task)


def _has_user_priority_edit(row: PipelineTaskRecord) -> bool:
    if row.applied_priority_delta != 0:
        return True
    history = row.decision_history or []
    return any(entry.get("action") == FeedbackAction.WRONG_PRIORITY.value for entry in history if isinstance(entry, dict))


def _source_ids_for_match(
    *,
    canonical_task: CanonicalTask | None = None,
    task_card: PrioritizedTaskCard | None = None,
    payload: dict[str, Any] | None = None,
) -> set[str]:
    source_ids: list[str] = []

    if canonical_task is not None:
        source_ids.extend(str(source_id) for source_id in canonical_task.source_ids if source_id)
    if task_card is not None:
        source_ids.extend(str(source_id) for source_id in task_card.evidence_source_ids if source_id)

    if payload:
        payload_task = _parse_payload_task(payload)
        if payload_task is not None:
            source_ids.extend(str(source_id) for source_id in payload_task.source_ids if source_id)
        payload_card = _parse_payload_card(payload)
        if payload_card is not None:
            source_ids.extend(str(source_id) for source_id in payload_card.evidence_source_ids if source_id)

    return {source_id for source_id in source_ids if source_id}


def _task_rows_match_by_sources(
    *,
    canonical_task: CanonicalTask,
    task_card: PrioritizedTaskCard,
    existing_payload: dict[str, Any] | None,
) -> bool:
    new_source_ids = _source_ids_for_match(canonical_task=canonical_task, task_card=task_card)
    existing_source_ids = _source_ids_for_match(payload=existing_payload)
    if not new_source_ids or not existing_source_ids:
        return False
    return bool(new_source_ids & existing_source_ids)


@dataclass
class PipelineRunBundle:
    run_id: str
    signals: list
    canonical_tasks: list[CanonicalTask]
    decisions: list[LlmDecision]
    task_cards: list[PrioritizedTaskCard]
    profile: BehaviorProfile | None = None


@dataclass
class FeedbackTaskContext:
    user_id: str
    canonical_task_id: str
    task_type: TaskType
    entity_key: str
    entity_name: str
    entity_type: EntityType
    sender_ids: list[str]
    deadline_hours: float | None
    task_tags: list[str]
    status: TaskStatus
    suggested_priority_tier: PriorityTier
    effective_priority_tier: PriorityTier
    applied_priority_delta: int


@dataclass
class FeedbackUpdateContext:
    task: FeedbackTaskContext
    profile: BehaviorProfile | None


class PipelineRepository(Protocol):
    def create_run(self, user_id: str) -> str: ...

    def mark_run_finished(self, run_id: str, *, error_text: str | None = None) -> None: ...

    def get_raw_messages(self, user_id: str, *, limit: int | None = None) -> list[RawMessage]: ...

    def upsert_raw_messages(self, messages: list[RawMessage]) -> None: ...

    def get_behavior_profile(self, user_id: str) -> BehaviorProfile | None: ...

    def save_behavior_profile(self, profile: BehaviorProfile) -> None: ...

    def get_onboarding_context(self, user_id: str) -> OnboardingContext | None: ...

    def save_onboarding_context(self, context: OnboardingContext) -> None: ...

    def get_entity_aliases(self, user_id: str) -> dict[str, EntityAlias]: ...

    def upsert_entity_aliases(self, user_id: str, aliases: list[EntityAlias]) -> None: ...

    def get_custom_tags(self, user_id: str) -> list[str]: ...

    def upsert_custom_tags(self, user_id: str, tags: list[str]) -> list[str]: ...

    def get_current_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]: ...

    def get_completed_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]: ...

    def get_accepted_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]: ...

    def get_current_task_card(self, user_id: str, canonical_task_id: str) -> PrioritizedTaskCard | None: ...

    def get_current_canonical_task(self, user_id: str, canonical_task_id: str) -> CanonicalTask | None: ...

    def get_feedback_task_context(self, user_id: str, canonical_task_id: str) -> FeedbackTaskContext | None: ...

    def get_feedback_update_context(self, user_id: str, canonical_task_id: str) -> FeedbackUpdateContext | None: ...

    def replace_task_tags(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        tags: list[str],
    ) -> PrioritizedTaskCard | None: ...

    def update_task(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        updates: dict[str, Any],
    ) -> PrioritizedTaskCard | None: ...

    def apply_task_action(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        action: FeedbackAction,
        direction: FeedbackDirection | None = None,
    ) -> PrioritizedTaskCard | None: ...

    def shift_current_task_card_priority(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        direction: FeedbackDirection,
    ) -> PrioritizedTaskCard | None: ...

    def dismiss_task_card(self, user_id: str, canonical_task_id: str) -> bool: ...

    def save_feedback_event(self, event: FeedbackEvent) -> None: ...

    def save_feedback_profile_update(self, event: FeedbackEvent, profile: BehaviorProfile) -> None: ...

    def save_pipeline_results(self, bundle: PipelineRunBundle) -> None: ...


class InMemoryPipelineRepository:
    def __init__(self) -> None:
        self.raw_messages: dict[str, list[RawMessage]] = {}
        self.runs: dict[str, dict[str, str | None]] = {}
        self.profiles: dict[str, BehaviorProfile] = {}
        self.onboarding: dict[str, OnboardingContext] = {}
        self.aliases: dict[str, dict[str, EntityAlias]] = {}
        self.custom_tags: dict[str, list[str]] = {}
        self.feedback_events: list[FeedbackEvent] = []
        self.bundles: list[PipelineRunBundle] = []
        self.task_rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.current_cards: dict[str, PrioritizedTaskCard] = {}

    def create_run(self, user_id: str) -> str:
        run_id = uuid4().hex
        self.runs[run_id] = {"user_id": user_id, "status": "started", "error_text": None}
        return run_id

    def mark_run_finished(self, run_id: str, *, error_text: str | None = None) -> None:
        status = "failed" if error_text else "finished"
        if run_id in self.runs:
            self.runs[run_id]["status"] = status
            self.runs[run_id]["error_text"] = error_text

    def get_raw_messages(self, user_id: str, *, limit: int | None = None) -> list[RawMessage]:
        messages = list(self.raw_messages.get(user_id, []))
        return messages[:limit] if limit is not None else messages

    def upsert_raw_messages(self, messages: list[RawMessage]) -> None:
        for message in messages:
            bucket = self.raw_messages.setdefault(message.user_id, [])
            existing = {(item.platform.value, item.source_id): item for item in bucket}
            existing[(message.platform.value, message.source_id)] = message
            self.raw_messages[message.user_id] = list(existing.values())

    def get_behavior_profile(self, user_id: str) -> BehaviorProfile | None:
        return self.profiles.get(user_id)

    def save_behavior_profile(self, profile: BehaviorProfile) -> None:
        self.profiles[profile.user_id] = profile

    def get_onboarding_context(self, user_id: str) -> OnboardingContext | None:
        return self.onboarding.get(user_id)

    def save_onboarding_context(self, context: OnboardingContext) -> None:
        self.onboarding[context.user_id] = context

    def get_entity_aliases(self, user_id: str) -> dict[str, EntityAlias]:
        return dict(self.aliases.get(user_id, {}))

    def upsert_entity_aliases(self, user_id: str, aliases: list[EntityAlias]) -> None:
        user_aliases = self.aliases.setdefault(user_id, {})
        for alias in aliases:
            user_aliases[alias.alias_key] = alias

    def get_custom_tags(self, user_id: str) -> list[str]:
        return list(self.custom_tags.get(user_id, []))

    def upsert_custom_tags(self, user_id: str, tags: list[str]) -> list[str]:
        merged = dedupe_tags([*self.custom_tags.get(user_id, []), *tags])
        self.custom_tags[user_id] = merged
        return merged

    def get_current_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        cards = [
            _row_to_card_from_memory(row)
            for row in self.task_rows.values()
            if row["user_id"] == user_id and row["status"] == TaskStatus.PENDING_REVIEW.value
        ]
        cards = [card for card in cards if card is not None]
        return cards

    def get_completed_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        cards = [
            _row_to_card_from_memory(row)
            for row in self.task_rows.values()
            if row["user_id"] == user_id and row["status"] == TaskStatus.COMPLETED.value
        ]
        cards = [card for card in cards if card is not None]
        return _sort_task_cards(cards)

    def get_accepted_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        cards = [
            _row_to_card_from_memory(row)
            for row in self.task_rows.values()
            if row["user_id"] == user_id and row["status"] == TaskStatus.ACCEPTED.value
        ]
        cards = [card for card in cards if card is not None]
        return _sort_task_cards(cards)

    def get_current_task_card(self, user_id: str, canonical_task_id: str) -> PrioritizedTaskCard | None:
        row = self.task_rows.get((user_id, canonical_task_id))
        if row is None or row["status"] != TaskStatus.PENDING_REVIEW.value:
            return None
        return _row_to_card_from_memory(row)

    def get_current_canonical_task(self, user_id: str, canonical_task_id: str) -> CanonicalTask | None:
        row = self.task_rows.get((user_id, canonical_task_id))
        if row is None:
            return None
        task = _parse_payload_task(row["payload"])
        return None if task is None else _apply_edit_overrides_to_task(task, row.get("payload", {}))

    def get_feedback_task_context(self, user_id: str, canonical_task_id: str) -> FeedbackTaskContext | None:
        row = self.task_rows.get((user_id, canonical_task_id))
        if row is None:
            return None
        return _feedback_context_from_memory_row(row)

    def get_feedback_update_context(self, user_id: str, canonical_task_id: str) -> FeedbackUpdateContext | None:
        task = self.get_feedback_task_context(user_id, canonical_task_id)
        if task is None:
            return None
        return FeedbackUpdateContext(task=task, profile=self.get_behavior_profile(user_id))

    def replace_task_tags(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        tags: list[str],
    ) -> PrioritizedTaskCard | None:
        row = self.task_rows.get((user_id, canonical_task_id))
        if row is None:
            return None
        updated = _replace_tags_in_memory_row(row, tags=tags)
        self.task_rows[(user_id, canonical_task_id)] = updated
        self._refresh_current_cards(user_id)
        return _row_to_card_from_memory(updated)

    def update_task(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        updates: dict[str, Any],
    ) -> PrioritizedTaskCard | None:
        row = self.task_rows.get((user_id, canonical_task_id))
        if row is None:
            return None
        updated = _update_memory_task_row(row, updates=updates)
        self.task_rows[(user_id, canonical_task_id)] = updated
        self._refresh_current_cards(user_id)
        return _row_to_card_from_memory(updated)

    def apply_task_action(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        action: FeedbackAction,
        direction: FeedbackDirection | None = None,
    ) -> PrioritizedTaskCard | None:
        row = self.task_rows.get((user_id, canonical_task_id))
        if row is None:
            return None
        updated = _apply_action_to_memory_row(row, action=action, direction=direction)
        self.task_rows[(user_id, canonical_task_id)] = updated
        self._refresh_current_cards(user_id)
        return _row_to_card_from_memory(updated)

    def shift_current_task_card_priority(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        direction: FeedbackDirection,
    ) -> PrioritizedTaskCard | None:
        return self.apply_task_action(
            user_id,
            canonical_task_id,
            action=FeedbackAction.WRONG_PRIORITY,
            direction=direction,
        )

    def dismiss_task_card(self, user_id: str, canonical_task_id: str) -> bool:
        row = self.task_rows.get((user_id, canonical_task_id))
        if row is None:
            return False
        action = FeedbackAction.REJECT if row["status"] == TaskStatus.PENDING_REVIEW.value else FeedbackAction.DELETE
        self.apply_task_action(user_id, canonical_task_id, action=action)
        return True

    def save_feedback_event(self, event: FeedbackEvent) -> None:
        self.feedback_events.append(event)

    def save_feedback_profile_update(self, event: FeedbackEvent, profile: BehaviorProfile) -> None:
        self.feedback_events.append(event)
        self.profiles[profile.user_id] = profile

    def save_pipeline_results(self, bundle: PipelineRunBundle) -> None:
        self.bundles.append(bundle)
        if bundle.profile is not None:
            self.profiles[bundle.profile.user_id] = bundle.profile

        decision_by_id = {decision.canonical_task_id: decision for decision in bundle.decisions}
        task_by_id = {task.canonical_task_id: task for task in bundle.canonical_tasks}
        ordered_task_cards = _sort_task_cards(bundle.task_cards)
        for card in ordered_task_cards:
            task = task_by_id.get(card.canonical_task_id)
            if task is None:
                continue
            key = (card.user_id, card.canonical_task_id)
            existing = self.task_rows.get(key)
            matched_key = key
            if existing is None:
                for existing_key, existing_row in self.task_rows.items():
                    row_user_id, existing_canonical_task_id = existing_key
                    if row_user_id != card.user_id or existing_canonical_task_id == card.canonical_task_id:
                        continue
                    if _task_rows_match_by_sources(
                        canonical_task=task,
                        task_card=card,
                        existing_payload=existing_row.get("payload", {}),
                    ):
                        existing = existing_row
                        matched_key = existing_key
                        break
            self.task_rows[key] = _merge_memory_task_row(
                existing=existing,
                task_card=card,
                canonical_task=task,
                llm_decision=decision_by_id.get(card.canonical_task_id),
            )
            if matched_key != key:
                self.task_rows.pop(matched_key, None)
        if ordered_task_cards:
            self._refresh_current_cards(ordered_task_cards[0].user_id)

    def _refresh_current_cards(self, user_id: str) -> None:
        self.current_cards = {
            canonical_task_id: card
            for (row_user_id, canonical_task_id), row in self.task_rows.items()
            if row_user_id == user_id
            for card in [_row_to_card_from_memory(row)]
            if card is not None and row["status"] == TaskStatus.PENDING_REVIEW.value
        }


class SqlAlchemyPipelineRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_run(self, user_id: str) -> str:
        return uuid4().hex

    def mark_run_finished(self, run_id: str, *, error_text: str | None = None) -> None:
        return None

    def get_raw_messages(self, user_id: str, *, limit: int | None = None) -> list[RawMessage]:
        with Session(self.engine) as session:
            stmt = select(StoredEmailRecord).where(StoredEmailRecord.user_id == int(user_id)).order_by(StoredEmailRecord.id.desc())
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = session.scalars(stmt).all()
            return [_stored_email_to_raw_message(row) for row in rows]

    def upsert_raw_messages(self, messages: list[RawMessage]) -> None:
        with Session(self.engine) as session:
            for message in messages:
                db_user_id = int(message.user_id)
                row = session.scalar(
                    select(StoredEmailRecord).where(
                        StoredEmailRecord.user_id == db_user_id,
                        StoredEmailRecord.platform == message.platform.value,
                        StoredEmailRecord.source_id == message.source_id,
                    )
                )
                payload = message.model_dump(mode="json")
                if row is None:
                    row = StoredEmailRecord(
                        user_id=db_user_id,
                        platform=message.platform.value,
                        source_id=message.source_id,
                    )
                    session.add(row)

                row.thread_id = payload.get("thread_id")
                row.timestamp_iso = _parse_dt(payload.get("timestamp_iso"))
                row.label_ids = payload.get("label_ids") or []
                row.sender_id = payload.get("sender_id")
                row.sender_display = payload.get("sender_display")
                row.sender_email = payload.get("sender_email")
                row.sender_domain = payload.get("sender_domain")
                row.subject = payload.get("subject")
                row.snippet = payload.get("snippet")
                row.body_text = payload.get("body_text") or ""
                row.body_html_present = bool(payload.get("body_html_present"))
                row.attachments_present = bool(payload.get("attachments_present"))
                row.mime_parts = payload.get("mime_parts") or []
                row.provider_metadata = payload.get("provider_metadata") or {}
                row.from_raw = payload.get("from_raw")
                row.to_raw = payload.get("to_raw")
                row.cc_raw = payload.get("cc_raw")
                row.bcc_raw = payload.get("bcc_raw")
                row.updated_at = utc_now_naive()
            session.commit()

    def get_behavior_profile(self, user_id: str) -> BehaviorProfile | None:
        with Session(self.engine) as session:
            row = session.get(PipelineUserStateRecord, user_id)
            if row is None or row.profile_payload is None:
                return None
            return BehaviorProfile.model_validate(row.profile_payload)

    def save_behavior_profile(self, profile: BehaviorProfile) -> None:
        with Session(self.engine) as session:
            row = self._get_or_create_user_state(session, profile.user_id)
            row.profile_version = profile.profile_version
            row.profile_payload = profile.model_dump(mode="json")
            row.updated_at = utc_now_naive()
            session.commit()

    def get_onboarding_context(self, user_id: str) -> OnboardingContext | None:
        with Session(self.engine) as session:
            row = session.get(PipelineUserStateRecord, user_id)
            if row is None or row.onboarding_payload is None:
                return None
            return OnboardingContext.model_validate(row.onboarding_payload)

    def save_onboarding_context(self, context: OnboardingContext) -> None:
        with Session(self.engine) as session:
            row = self._get_or_create_user_state(session, context.user_id)
            row.onboarding_payload = context.model_dump(mode="json")
            row.updated_at = utc_now_naive()
            session.commit()

    def get_entity_aliases(self, user_id: str) -> dict[str, EntityAlias]:
        with Session(self.engine) as session:
            row = session.get(PipelineUserStateRecord, user_id)
            payload = {} if row is None else (row.alias_payload or {})
            return {
                alias_key: EntityAlias.model_validate(alias_value)
                for alias_key, alias_value in payload.items()
                if isinstance(alias_value, dict)
            }

    def upsert_entity_aliases(self, user_id: str, aliases: list[EntityAlias]) -> None:
        with Session(self.engine) as session:
            row = self._get_or_create_user_state(session, user_id)
            current_payload = dict(row.alias_payload or {})
            for alias in aliases:
                current_payload[alias.alias_key] = alias.model_dump(mode="json")
            row.alias_payload = current_payload
            row.updated_at = utc_now_naive()
            session.commit()

    def get_custom_tags(self, user_id: str) -> list[str]:
        with Session(self.engine) as session:
            row = session.get(PipelineUserStateRecord, user_id)
            return dedupe_tags([] if row is None else (row.custom_tags or []))

    def upsert_custom_tags(self, user_id: str, tags: list[str]) -> list[str]:
        with Session(self.engine) as session:
            row = self._get_or_create_user_state(session, user_id)
            merged = dedupe_tags([*(row.custom_tags or []), *tags])
            row.custom_tags = merged
            row.updated_at = utc_now_naive()
            session.commit()
            return merged

    def get_current_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        return self._list_task_cards_for_status(user_id, TaskStatus.PENDING_REVIEW)

    def get_completed_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        return self._list_task_cards_for_status(user_id, TaskStatus.COMPLETED)

    def get_accepted_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        return self._list_task_cards_for_status(user_id, TaskStatus.ACCEPTED)

    def get_current_task_card(self, user_id: str, canonical_task_id: str) -> PrioritizedTaskCard | None:
        with Session(self.engine) as session:
            row = self._get_task_row(session, user_id, canonical_task_id)
            if row is None or row.status != TaskStatus.PENDING_REVIEW.value:
                return None
            return self._hydrate_card(row)

    def get_current_canonical_task(self, user_id: str, canonical_task_id: str) -> CanonicalTask | None:
        with Session(self.engine) as session:
            row = self._get_task_row(session, user_id, canonical_task_id)
            return None if row is None else _row_to_task(row)

    def get_feedback_task_context(self, user_id: str, canonical_task_id: str) -> FeedbackTaskContext | None:
        with Session(self.engine) as session:
            row = self._get_task_row(session, user_id, canonical_task_id)
            if row is None:
                return None
            return _feedback_context_from_row(row)

    def get_feedback_update_context(self, user_id: str, canonical_task_id: str) -> FeedbackUpdateContext | None:
        with Session(self.engine) as session:
            row = self._get_task_row(session, user_id, canonical_task_id)
            if row is None:
                return None
            user_state = session.get(PipelineUserStateRecord, user_id)
            profile = None if user_state is None or user_state.profile_payload is None else BehaviorProfile.model_validate(user_state.profile_payload)
            return FeedbackUpdateContext(task=_feedback_context_from_row(row), profile=profile)

    def replace_task_tags(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        tags: list[str],
    ) -> PrioritizedTaskCard | None:
        with Session(self.engine) as session:
            row = self._get_task_row(session, user_id, canonical_task_id)
            if row is None:
                return None
            _replace_tags_in_sql_row(row, tags=tags)
            row.updated_at = utc_now_naive()
            session.commit()
            session.refresh(row)
            return self._hydrate_card(row)

    def update_task(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        updates: dict[str, Any],
    ) -> PrioritizedTaskCard | None:
        with Session(self.engine) as session:
            row = self._get_task_row(session, user_id, canonical_task_id)
            if row is None:
                return None
            _update_sql_task_row(row, updates=updates)
            row.updated_at = utc_now_naive()
            session.commit()
            session.refresh(row)
            return self._hydrate_card(row)

    def apply_task_action(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        action: FeedbackAction,
        direction: FeedbackDirection | None = None,
    ) -> PrioritizedTaskCard | None:
        with Session(self.engine) as session:
            row = self._get_task_row(session, user_id, canonical_task_id)
            if row is None:
                return None
            _apply_action_to_sql_row(row, action=action, direction=direction)
            row.updated_at = utc_now_naive()
            session.commit()
            session.refresh(row)
            return self._hydrate_card(row)

    def shift_current_task_card_priority(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        direction: FeedbackDirection,
    ) -> PrioritizedTaskCard | None:
        return self.apply_task_action(
            user_id,
            canonical_task_id,
            action=FeedbackAction.WRONG_PRIORITY,
            direction=direction,
        )

    def dismiss_task_card(self, user_id: str, canonical_task_id: str) -> bool:
        with Session(self.engine) as session:
            row = self._get_task_row(session, user_id, canonical_task_id)
            if row is None:
                return False
            action = FeedbackAction.REJECT if row.status == TaskStatus.PENDING_REVIEW.value else FeedbackAction.DELETE
            _apply_action_to_sql_row(row, action=action, direction=None)
            row.updated_at = utc_now_naive()
            session.commit()
            return True

    def save_feedback_event(self, event: FeedbackEvent) -> None:
        return None

    def save_feedback_profile_update(self, event: FeedbackEvent, profile: BehaviorProfile) -> None:
        self.save_behavior_profile(profile)

    def save_pipeline_results(self, bundle: PipelineRunBundle) -> None:
        with Session(self.engine) as session:
            decision_by_id = {decision.canonical_task_id: decision for decision in bundle.decisions}
            task_by_id = {task.canonical_task_id: task for task in bundle.canonical_tasks}

            ordered_task_cards = _sort_task_cards(bundle.task_cards)
            for card in ordered_task_cards:
                task = task_by_id.get(card.canonical_task_id)
                if task is None:
                    continue
                row = self._get_task_row(session, card.user_id, card.canonical_task_id)
                if row is None:
                    row = self._find_task_row_by_sources(
                        session,
                        user_id=card.user_id,
                        canonical_task=task,
                        task_card=card,
                    )
                if row is None:
                    row = PipelineTaskRecord(
                        user_id=card.user_id,
                        canonical_task_id=card.canonical_task_id,
                        created_at=utc_now_naive(),
                    )
                    session.add(row)
                else:
                    row.canonical_task_id = card.canonical_task_id
                _merge_sql_task_row(
                    row=row,
                    task_card=card,
                    canonical_task=task,
                    llm_decision=decision_by_id.get(card.canonical_task_id),
                )

            if bundle.profile is not None:
                user_state = self._get_or_create_user_state(session, bundle.profile.user_id)
                user_state.profile_version = bundle.profile.profile_version
                user_state.profile_payload = bundle.profile.model_dump(mode="json")
                user_state.updated_at = utc_now_naive()

            session.commit()

    def _get_or_create_user_state(self, session: Session, user_id: str) -> PipelineUserStateRecord:
        row = session.get(PipelineUserStateRecord, user_id)
        if row is None:
            row = PipelineUserStateRecord(
                user_id=user_id,
                profile_version=1,
                profile_payload=None,
                onboarding_payload=None,
                custom_tags=[],
                alias_payload={},
                updated_at=utc_now_naive(),
            )
            session.add(row)
            session.flush()
        return row

    def _get_task_row(self, session: Session, user_id: str, canonical_task_id: str) -> PipelineTaskRecord | None:
        return session.scalar(
            select(PipelineTaskRecord).where(
                PipelineTaskRecord.user_id == user_id,
                PipelineTaskRecord.canonical_task_id == canonical_task_id,
            )
        )

    def _find_task_row_by_sources(
        self,
        session: Session,
        *,
        user_id: str,
        canonical_task: CanonicalTask,
        task_card: PrioritizedTaskCard,
    ) -> PipelineTaskRecord | None:
        rows = session.scalars(
            select(PipelineTaskRecord).where(PipelineTaskRecord.user_id == user_id)
        ).all()
        for row in rows:
            if row.canonical_task_id == task_card.canonical_task_id:
                continue
            if _task_rows_match_by_sources(
                canonical_task=canonical_task,
                task_card=task_card,
                existing_payload=row.payload or {},
            ):
                return row
        return None

    def _list_task_cards_for_status(self, user_id: str, status: TaskStatus) -> list[PrioritizedTaskCard]:
        with Session(self.engine) as session:
            stmt = select(PipelineTaskRecord).where(
                    PipelineTaskRecord.user_id == user_id,
                    PipelineTaskRecord.status == status.value,
                )
            if status == TaskStatus.PENDING_REVIEW:
                stmt = stmt.order_by(PipelineTaskRecord.created_at.asc(), PipelineTaskRecord.id.asc())
            rows = session.scalars(stmt).all()
            cards = [self._hydrate_card(row) for row in rows]
            hydrated_cards = [card for card in cards if card is not None]
            if status == TaskStatus.PENDING_REVIEW:
                return hydrated_cards
            return _sort_task_cards(hydrated_cards)

    def _hydrate_card(self, row: PipelineTaskRecord) -> PrioritizedTaskCard | None:
        card = _row_to_card(row)
        task = _row_to_task(row)
        if card is None:
            return None
        if task is not None and _task_card_needs_hydration(card):
            card = _enrich_task_card(card, task)
        return card


def _feedback_context_from_row(row: PipelineTaskRecord) -> FeedbackTaskContext:
    task = _row_to_task(row)
    card = _row_to_card(row)
    if task is None or card is None:
        raise ValueError("Task payload is incomplete.")
    return FeedbackTaskContext(
        user_id=row.user_id,
        canonical_task_id=row.canonical_task_id,
        task_type=task.task_type,
        entity_key=task.topic_entity.entity_key,
        entity_name=task.topic_entity.entity_name,
        entity_type=task.topic_entity.entity_type,
        sender_ids=list(task.sender_ids),
        deadline_hours=row.deadline_hours,
        task_tags=dedupe_tags(row.tags or card.tags),
        status=TaskStatus(row.status),
        suggested_priority_tier=PriorityTier(row.suggested_priority_tier),
        effective_priority_tier=PriorityTier(row.effective_priority_tier),
        applied_priority_delta=row.applied_priority_delta,
    )


def _feedback_context_from_memory_row(row: dict[str, Any]) -> FeedbackTaskContext:
    task = _parse_payload_task(row["payload"])
    if task is not None:
        task = _apply_edit_overrides_to_task(task, row.get("payload", {}))
    card = _row_to_card_from_memory(row)
    if task is None or card is None:
        raise ValueError("Task payload is incomplete.")
    return FeedbackTaskContext(
        user_id=row["user_id"],
        canonical_task_id=row["canonical_task_id"],
        task_type=task.task_type,
        entity_key=task.topic_entity.entity_key,
        entity_name=task.topic_entity.entity_name,
        entity_type=task.topic_entity.entity_type,
        sender_ids=list(task.sender_ids),
        deadline_hours=row["deadline_hours"],
        task_tags=dedupe_tags(row["tags"] or card.tags),
        status=TaskStatus(row["status"]),
        suggested_priority_tier=PriorityTier(row["suggested_priority_tier"]),
        effective_priority_tier=PriorityTier(row["effective_priority_tier"]),
        applied_priority_delta=row["applied_priority_delta"],
    )


def _row_to_card_from_memory(row: dict[str, Any]) -> PrioritizedTaskCard | None:
    card = _parse_payload_card(row["payload"])
    if card is None:
        return None
    card = _apply_edit_overrides_to_card(card, row.get("payload", {}))
    return card.model_copy(
        update={
            "status": TaskStatus(row["status"]),
            "priority_tier": PriorityTier(row["effective_priority_tier"]),
            "suggested_priority_tier": PriorityTier(row["suggested_priority_tier"]),
            "effective_priority_tier": PriorityTier(row["effective_priority_tier"]),
            "applied_priority_delta": row["applied_priority_delta"],
            "deadline_hours": row["deadline_hours"],
            "tags": dedupe_tags(row["tags"] or card.tags),
            "confidence": row["confidence"],
        }
    )


def _merge_sql_task_row(
    *,
    row: PipelineTaskRecord,
    task_card: PrioritizedTaskCard,
    canonical_task: CanonicalTask,
    llm_decision: LlmDecision | None,
) -> None:
    existing_status = TaskStatus(row.status) if row.status else TaskStatus.PENDING_REVIEW
    preserve_priority = bool(row.status) and (existing_status != TaskStatus.PENDING_REVIEW or _has_user_priority_edit(row))

    suggested_priority = PriorityTier(row.suggested_priority_tier) if preserve_priority and row.suggested_priority_tier else task_card.suggested_priority_tier
    effective_priority = PriorityTier(row.effective_priority_tier) if preserve_priority and row.effective_priority_tier else task_card.effective_priority_tier
    applied_priority_delta = row.applied_priority_delta if preserve_priority else task_card.applied_priority_delta
    status = existing_status if row.status else task_card.status
    tag_overrides = _get_tag_override_state(row.payload or {})
    edit_overrides = _get_edit_override_state(row.payload or {})
    generated_tags = dedupe_tags(task_card.tags)
    persisted_tags = _apply_tag_overrides(generated_tags, row.payload or {})
    persisted_task = _apply_edit_overrides_to_task(canonical_task, row.payload or {})

    persisted_card = task_card.model_copy(
        update={
            "status": status,
            "priority_tier": effective_priority,
            "suggested_priority_tier": suggested_priority,
            "effective_priority_tier": effective_priority,
            "applied_priority_delta": applied_priority_delta,
            "tags": persisted_tags,
        }
    )
    persisted_card = _apply_edit_overrides_to_card(persisted_card, row.payload or {})

    row.origin = persisted_card.origin.value
    row.status = status.value
    row.task_type = persisted_card.task_type.value
    row.entity_key = persisted_card.entity_key
    row.deadline_hours = persisted_card.deadline_hours
    row.suggested_priority_tier = suggested_priority.value
    row.effective_priority_tier = effective_priority.value
    row.applied_priority_delta = applied_priority_delta
    row.confidence = persisted_card.confidence
    row.tags = persisted_tags
    row.payload = _set_tag_override_state(
        _set_edit_override_state(
            _payload_for_task(task_card=persisted_card, canonical_task=persisted_task, llm_decision=llm_decision),
            overrides=edit_overrides,
        ),
        added_tags=tag_overrides["added"],
        removed_tags=tag_overrides["removed"],
        generated_tags=generated_tags,
    )
    row.decision_history = row.decision_history or []
    row.accepted_at = row.accepted_at
    row.rejected_at = row.rejected_at
    row.completed_at = row.completed_at
    row.deleted_at = row.deleted_at
    row.updated_at = utc_now_naive()


def _merge_memory_task_row(
    *,
    existing: dict[str, Any] | None,
    task_card: PrioritizedTaskCard,
    canonical_task: CanonicalTask,
    llm_decision: LlmDecision | None,
) -> dict[str, Any]:
    existing_status = TaskStatus(existing["status"]) if existing and existing.get("status") else TaskStatus.PENDING_REVIEW
    preserve_priority = existing is not None and (
        existing_status != TaskStatus.PENDING_REVIEW or bool(existing.get("applied_priority_delta"))
        or any(entry.get("action") == FeedbackAction.WRONG_PRIORITY.value for entry in existing.get("decision_history", []))
    )

    suggested_priority = PriorityTier(existing["suggested_priority_tier"]) if preserve_priority and existing else task_card.suggested_priority_tier
    effective_priority = PriorityTier(existing["effective_priority_tier"]) if preserve_priority and existing else task_card.effective_priority_tier
    applied_priority_delta = existing["applied_priority_delta"] if preserve_priority and existing else task_card.applied_priority_delta
    status = existing_status if existing else task_card.status
    existing_payload = existing.get("payload", {}) if existing else {}
    tag_overrides = _get_tag_override_state(existing_payload)
    edit_overrides = _get_edit_override_state(existing_payload)
    generated_tags = dedupe_tags(task_card.tags)
    persisted_tags = _apply_tag_overrides(generated_tags, existing_payload)
    persisted_task = _apply_edit_overrides_to_task(canonical_task, existing_payload)

    persisted_card = task_card.model_copy(
        update={
            "status": status,
            "priority_tier": effective_priority,
            "suggested_priority_tier": suggested_priority,
            "effective_priority_tier": effective_priority,
            "applied_priority_delta": applied_priority_delta,
            "tags": persisted_tags,
        }
    )
    persisted_card = _apply_edit_overrides_to_card(persisted_card, existing_payload)

    return {
        "user_id": persisted_card.user_id,
        "canonical_task_id": persisted_card.canonical_task_id,
        "origin": persisted_card.origin.value,
        "status": status.value,
        "task_type": persisted_card.task_type.value,
        "entity_key": persisted_card.entity_key,
        "deadline_hours": persisted_card.deadline_hours,
        "suggested_priority_tier": suggested_priority.value,
        "effective_priority_tier": effective_priority.value,
        "applied_priority_delta": applied_priority_delta,
        "confidence": persisted_card.confidence,
        "tags": persisted_tags,
        "payload": _set_tag_override_state(
            _set_edit_override_state(
                _payload_for_task(task_card=persisted_card, canonical_task=persisted_task, llm_decision=llm_decision),
                overrides=edit_overrides,
            ),
            added_tags=tag_overrides["added"],
            removed_tags=tag_overrides["removed"],
            generated_tags=generated_tags,
        ),
        "decision_history": list(existing.get("decision_history", [])) if existing else [],
        "accepted_at": existing.get("accepted_at") if existing else None,
        "rejected_at": existing.get("rejected_at") if existing else None,
        "completed_at": existing.get("completed_at") if existing else None,
        "deleted_at": existing.get("deleted_at") if existing else None,
        "created_at": existing.get("created_at") if existing else utc_now_naive(),
        "updated_at": utc_now_naive(),
    }


def _apply_action_to_sql_row(
    row: PipelineTaskRecord,
    *,
    action: FeedbackAction,
    direction: FeedbackDirection | None,
) -> None:
    card = _row_to_card(row)
    task = _row_to_task(row)
    if card is None or task is None:
        raise ValueError("Task payload is incomplete.")

    before_status = TaskStatus(row.status)
    before_priority = PriorityTier(row.effective_priority_tier)
    after_status = before_status
    after_priority = before_priority
    incremental_delta = 0

    if action == FeedbackAction.WRONG_PRIORITY:
        if direction is None:
            raise ValueError("direction is required when action is WRONG_PRIORITY")
        after_priority, new_delta, incremental_delta = compute_priority_adjustment(
            suggested_priority_tier=PriorityTier(row.suggested_priority_tier),
            effective_priority_tier=PriorityTier(row.effective_priority_tier),
            applied_priority_delta=row.applied_priority_delta,
            direction=direction,
        )
        row.effective_priority_tier = after_priority.value
        row.applied_priority_delta = new_delta
    elif action == FeedbackAction.ACCEPT:
        after_status = TaskStatus.ACCEPTED
        row.accepted_at = utc_now_naive()
    elif action == FeedbackAction.REJECT:
        after_status = TaskStatus.REJECTED
        row.rejected_at = utc_now_naive()
    elif action == FeedbackAction.COMPLETED:
        after_status = TaskStatus.COMPLETED
        row.completed_at = utc_now_naive()
    elif action == FeedbackAction.DELETE:
        after_status = TaskStatus.DELETED
        row.deleted_at = utc_now_naive()

    row.status = after_status.value
    row.tags = dedupe_tags(row.tags or card.tags)
    tag_overrides = _get_tag_override_state(row.payload or {})
    edit_overrides = _get_edit_override_state(row.payload or {})
    updated_card = card.model_copy(
        update={
            "status": after_status,
            "priority_tier": after_priority,
            "effective_priority_tier": after_priority,
            "applied_priority_delta": row.applied_priority_delta,
            "tags": row.tags,
        }
    )
    row.payload = _set_tag_override_state(
        _set_edit_override_state(
            _payload_for_task(task_card=updated_card, canonical_task=task, llm_decision=_parse_llm_decision(row.payload)),
            overrides=edit_overrides,
        ),
        added_tags=tag_overrides["added"],
        removed_tags=tag_overrides["removed"],
        generated_tags=tag_overrides["generated"] or dedupe_tags(row.tags),
    )
    history = list(row.decision_history or [])
    history.append(
        TaskDecision(
            action=action,
            before_status=before_status,
            after_status=after_status,
            before_priority=before_priority,
            after_priority=after_priority,
            incremental_priority_delta=incremental_delta,
        ).model_dump(mode="json")
    )
    row.decision_history = history
    row.confidence = updated_card.confidence


def _replace_tags_in_sql_row(
    row: PipelineTaskRecord,
    *,
    tags: list[str],
) -> None:
    card = _row_to_card(row)
    task = _row_to_task(row)
    if card is None or task is None:
        raise ValueError("Task payload is incomplete.")

    desired_tags = dedupe_tags(tags)
    tag_overrides = _get_tag_override_state(row.payload or {})
    edit_overrides = _get_edit_override_state(row.payload or {})
    generated_tags = tag_overrides["generated"] or dedupe_tags(row.tags or card.tags)
    added_tags = [tag for tag in desired_tags if tag not in generated_tags]
    removed_tags = [tag for tag in generated_tags if tag not in desired_tags]

    row.tags = desired_tags
    updated_card = card.model_copy(update={"tags": desired_tags})
    row.payload = _set_tag_override_state(
        _set_edit_override_state(
            _payload_for_task(task_card=updated_card, canonical_task=task, llm_decision=_parse_llm_decision(row.payload)),
            overrides=edit_overrides,
        ),
        added_tags=added_tags,
        removed_tags=removed_tags,
        generated_tags=generated_tags,
    )
    row.confidence = updated_card.confidence


def _update_sql_task_row(
    row: PipelineTaskRecord,
    *,
    updates: dict[str, Any],
) -> None:
    card = _row_to_card(row)
    task = _row_to_task(row)
    if card is None or task is None:
        raise ValueError("Task payload is incomplete.")

    next_task = task
    next_card = card
    edit_overrides = _get_edit_override_state(row.payload or {})
    before_status = TaskStatus(row.status)
    before_priority = PriorityTier(row.effective_priority_tier)
    history = list(row.decision_history or [])

    if "title" in updates:
        edit_overrides["title"] = updates["title"]
        next_card = next_card.model_copy(update={"task_title": updates["title"]})

    if "description" in updates:
        edit_overrides["description"] = updates["description"]
        next_card = next_card.model_copy(update={"task_description": updates["description"]})

    if "deadline_at" in updates:
        edit_overrides["deadline_at"] = updates["deadline_at"]
        deadline_at = _parse_dt(updates["deadline_at"])
        deadline_hours = _deadline_hours_from_iso(updates["deadline_at"])
        next_task = next_task.model_copy(update={"deadline_at": deadline_at, "deadline_hours": deadline_hours})
        next_card = next_card.model_copy(update={"deadline_at_iso": updates["deadline_at"], "deadline_hours": deadline_hours})
        row.deadline_hours = deadline_hours

    if "priority_tier" in updates:
        next_priority = PriorityTier(updates["priority_tier"])
        new_delta = _priority_delta_for_tiers(
            suggested=PriorityTier(row.suggested_priority_tier),
            effective=next_priority,
        )
        incremental_delta = new_delta - row.applied_priority_delta
        row.effective_priority_tier = next_priority.value
        row.applied_priority_delta = new_delta
        next_card = next_card.model_copy(
            update={
                "priority_tier": next_priority,
                "effective_priority_tier": next_priority,
                "applied_priority_delta": new_delta,
            }
        )
        if next_priority != before_priority:
            history.append(
                TaskDecision(
                    action=FeedbackAction.WRONG_PRIORITY,
                    before_status=before_status,
                    after_status=before_status,
                    before_priority=before_priority,
                    after_priority=next_priority,
                    incremental_priority_delta=incremental_delta,
                ).model_dump(mode="json")
            )

    if "status" in updates:
        next_status = TaskStatus.COMPLETED if updates["status"] == "COMPLETED" else TaskStatus.PENDING_REVIEW
        row.status = next_status.value
        next_card = next_card.model_copy(update={"status": next_status})
        if next_status == TaskStatus.COMPLETED:
            row.completed_at = row.completed_at or utc_now_naive()
        else:
            row.completed_at = None
        if next_status != before_status and next_status == TaskStatus.COMPLETED:
            history.append(
                TaskDecision(
                    action=FeedbackAction.COMPLETED,
                    before_status=before_status,
                    after_status=next_status,
                    before_priority=PriorityTier(row.effective_priority_tier),
                    after_priority=PriorityTier(row.effective_priority_tier),
                    incremental_priority_delta=0,
                ).model_dump(mode="json")
            )

    tag_overrides = _get_tag_override_state(row.payload or {})
    generated_tags = tag_overrides["generated"] or dedupe_tags(row.tags or card.tags)
    if "tags" in updates:
        desired_tags = dedupe_tags(updates["tags"])
        added_tags = [tag for tag in desired_tags if tag not in generated_tags]
        removed_tags = [tag for tag in generated_tags if tag not in desired_tags]
        row.tags = desired_tags
        next_card = next_card.model_copy(update={"tags": desired_tags})
    else:
        added_tags = tag_overrides["added"]
        removed_tags = tag_overrides["removed"]

    row.decision_history = history
    row.confidence = next_card.confidence
    row.payload = _set_tag_override_state(
        _set_edit_override_state(
            _payload_for_task(task_card=next_card, canonical_task=next_task, llm_decision=_parse_llm_decision(row.payload)),
            overrides=edit_overrides,
        ),
        added_tags=added_tags,
        removed_tags=removed_tags,
        generated_tags=generated_tags,
    )
    row.updated_at = utc_now_naive()


def _apply_action_to_memory_row(
    row: dict[str, Any],
    *,
    action: FeedbackAction,
    direction: FeedbackDirection | None,
) -> dict[str, Any]:
    card = _row_to_card_from_memory(row)
    task = _parse_payload_task(row["payload"])
    if card is None or task is None:
        raise ValueError("Task payload is incomplete.")

    before_status = TaskStatus(row["status"])
    before_priority = PriorityTier(row["effective_priority_tier"])
    after_status = before_status
    after_priority = before_priority
    incremental_delta = 0

    if action == FeedbackAction.WRONG_PRIORITY:
        if direction is None:
            raise ValueError("direction is required when action is WRONG_PRIORITY")
        after_priority, new_delta, incremental_delta = compute_priority_adjustment(
            suggested_priority_tier=PriorityTier(row["suggested_priority_tier"]),
            effective_priority_tier=PriorityTier(row["effective_priority_tier"]),
            applied_priority_delta=row["applied_priority_delta"],
            direction=direction,
        )
        row["effective_priority_tier"] = after_priority.value
        row["applied_priority_delta"] = new_delta
    elif action == FeedbackAction.ACCEPT:
        after_status = TaskStatus.ACCEPTED
        row["accepted_at"] = utc_now_naive()
    elif action == FeedbackAction.REJECT:
        after_status = TaskStatus.REJECTED
        row["rejected_at"] = utc_now_naive()
    elif action == FeedbackAction.COMPLETED:
        after_status = TaskStatus.COMPLETED
        row["completed_at"] = utc_now_naive()
    elif action == FeedbackAction.DELETE:
        after_status = TaskStatus.DELETED
        row["deleted_at"] = utc_now_naive()

    row["status"] = after_status.value
    row["tags"] = dedupe_tags(row["tags"] or card.tags)
    tag_overrides = _get_tag_override_state(row.get("payload", {}))
    edit_overrides = _get_edit_override_state(row.get("payload", {}))
    updated_card = card.model_copy(
        update={
            "status": after_status,
            "priority_tier": after_priority,
            "effective_priority_tier": after_priority,
            "applied_priority_delta": row["applied_priority_delta"],
            "tags": row["tags"],
        }
    )
    row["payload"] = _set_tag_override_state(
        _set_edit_override_state(
            _payload_for_task(task_card=updated_card, canonical_task=task, llm_decision=_parse_llm_decision(row["payload"])),
            overrides=edit_overrides,
        ),
        added_tags=tag_overrides["added"],
        removed_tags=tag_overrides["removed"],
        generated_tags=tag_overrides["generated"] or dedupe_tags(row["tags"]),
    )
    history = list(row.get("decision_history", []))
    history.append(
        TaskDecision(
            action=action,
            before_status=before_status,
            after_status=after_status,
            before_priority=before_priority,
            after_priority=after_priority,
            incremental_priority_delta=incremental_delta,
        ).model_dump(mode="json")
    )
    row["decision_history"] = history
    row["updated_at"] = utc_now_naive()
    return row


def _replace_tags_in_memory_row(
    row: dict[str, Any],
    *,
    tags: list[str],
) -> dict[str, Any]:
    card = _row_to_card_from_memory(row)
    task = _parse_payload_task(row["payload"])
    if card is None or task is None:
        raise ValueError("Task payload is incomplete.")

    desired_tags = dedupe_tags(tags)
    tag_overrides = _get_tag_override_state(row.get("payload", {}))
    edit_overrides = _get_edit_override_state(row.get("payload", {}))
    generated_tags = tag_overrides["generated"] or dedupe_tags(row["tags"] or card.tags)
    added_tags = [tag for tag in desired_tags if tag not in generated_tags]
    removed_tags = [tag for tag in generated_tags if tag not in desired_tags]

    row["tags"] = desired_tags
    updated_card = card.model_copy(update={"tags": desired_tags})
    row["payload"] = _set_tag_override_state(
        _set_edit_override_state(
            _payload_for_task(task_card=updated_card, canonical_task=task, llm_decision=_parse_llm_decision(row["payload"])),
            overrides=edit_overrides,
        ),
        added_tags=added_tags,
        removed_tags=removed_tags,
        generated_tags=generated_tags,
    )
    row["confidence"] = updated_card.confidence
    row["updated_at"] = utc_now_naive()
    return row


def _update_memory_task_row(
    row: dict[str, Any],
    *,
    updates: dict[str, Any],
) -> dict[str, Any]:
    card = _row_to_card_from_memory(row)
    task = _parse_payload_task(row["payload"])
    if card is None or task is None:
        raise ValueError("Task payload is incomplete.")

    next_task = task
    next_card = card
    edit_overrides = _get_edit_override_state(row.get("payload", {}))
    before_status = TaskStatus(row["status"])
    before_priority = PriorityTier(row["effective_priority_tier"])
    history = list(row.get("decision_history", []))

    if "title" in updates:
        edit_overrides["title"] = updates["title"]
        next_card = next_card.model_copy(update={"task_title": updates["title"]})

    if "description" in updates:
        edit_overrides["description"] = updates["description"]
        next_card = next_card.model_copy(update={"task_description": updates["description"]})

    if "deadline_at" in updates:
        edit_overrides["deadline_at"] = updates["deadline_at"]
        deadline_at = _parse_dt(updates["deadline_at"])
        deadline_hours = _deadline_hours_from_iso(updates["deadline_at"])
        next_task = next_task.model_copy(update={"deadline_at": deadline_at, "deadline_hours": deadline_hours})
        next_card = next_card.model_copy(update={"deadline_at_iso": updates["deadline_at"], "deadline_hours": deadline_hours})
        row["deadline_hours"] = deadline_hours

    if "priority_tier" in updates:
        next_priority = PriorityTier(updates["priority_tier"])
        new_delta = _priority_delta_for_tiers(
            suggested=PriorityTier(row["suggested_priority_tier"]),
            effective=next_priority,
        )
        incremental_delta = new_delta - row["applied_priority_delta"]
        row["effective_priority_tier"] = next_priority.value
        row["applied_priority_delta"] = new_delta
        next_card = next_card.model_copy(
            update={
                "priority_tier": next_priority,
                "effective_priority_tier": next_priority,
                "applied_priority_delta": new_delta,
            }
        )
        if next_priority != before_priority:
            history.append(
                TaskDecision(
                    action=FeedbackAction.WRONG_PRIORITY,
                    before_status=before_status,
                    after_status=before_status,
                    before_priority=before_priority,
                    after_priority=next_priority,
                    incremental_priority_delta=incremental_delta,
                ).model_dump(mode="json")
            )

    if "status" in updates:
        next_status = TaskStatus.COMPLETED if updates["status"] == "COMPLETED" else TaskStatus.PENDING_REVIEW
        row["status"] = next_status.value
        next_card = next_card.model_copy(update={"status": next_status})
        if next_status == TaskStatus.COMPLETED:
            row["completed_at"] = row.get("completed_at") or utc_now_naive()
        else:
            row["completed_at"] = None
        if next_status != before_status and next_status == TaskStatus.COMPLETED:
            history.append(
                TaskDecision(
                    action=FeedbackAction.COMPLETED,
                    before_status=before_status,
                    after_status=next_status,
                    before_priority=PriorityTier(row["effective_priority_tier"]),
                    after_priority=PriorityTier(row["effective_priority_tier"]),
                    incremental_priority_delta=0,
                ).model_dump(mode="json")
            )

    tag_overrides = _get_tag_override_state(row.get("payload", {}))
    generated_tags = tag_overrides["generated"] or dedupe_tags(row["tags"] or card.tags)
    if "tags" in updates:
        desired_tags = dedupe_tags(updates["tags"])
        added_tags = [tag for tag in desired_tags if tag not in generated_tags]
        removed_tags = [tag for tag in generated_tags if tag not in desired_tags]
        row["tags"] = desired_tags
        next_card = next_card.model_copy(update={"tags": desired_tags})
    else:
        added_tags = tag_overrides["added"]
        removed_tags = tag_overrides["removed"]

    row["decision_history"] = history
    row["confidence"] = next_card.confidence
    row["payload"] = _set_tag_override_state(
        _set_edit_override_state(
            _payload_for_task(task_card=next_card, canonical_task=next_task, llm_decision=_parse_llm_decision(row["payload"])),
            overrides=edit_overrides,
        ),
        added_tags=added_tags,
        removed_tags=removed_tags,
        generated_tags=generated_tags,
    )
    row["updated_at"] = utc_now_naive()
    return row


def _parse_llm_decision(payload: dict[str, Any]) -> LlmDecision | None:
    llm_payload = payload.get("llm_decision") if isinstance(payload, dict) else None
    if not isinstance(llm_payload, dict):
        return None
    return LlmDecision.model_validate(llm_payload)
