from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pipeline.config import PipelineSettings
from pipeline.models import (
    BehaviorProfile,
    CanonicalTask,
    EntityAlias,
    FeedbackEvent,
    LlmDecision,
    OnboardingContext,
    PrioritizedTaskCard,
    RawMessage,
    TaskSignal,
)
from pipeline.models.enums import EntityType, TaskType
from pipeline.services.postprocess import PostProcessor
from pipeline.storage.tables import (
    BehaviorProfileRecord,
    CanonicalTaskRecord,
    CurrentTaskCardRecord,
    DismissedTaskRecord,
    EntityAliasRecord,
    FeedbackEventRecord,
    LlmDecisionRecord,
    OnboardingContextRecord,
    PipelineRunRecord,
    RawMessageRecord,
    TaskCardRecord,
    TaskSignalRecord,
)
from pipeline.utils.time import utc_now_naive


_PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_DISPLAY_POST_PROCESSOR = PostProcessor(PipelineSettings())


def _sort_task_cards(cards: list[PrioritizedTaskCard]) -> list[PrioritizedTaskCard]:
    return sorted(
        cards,
        key=lambda card: (_PRIORITY_ORDER.get(card.priority_tier.value, 99), card.deadline_hours or float("inf")),
    )


def _enrich_canonical_task(task: CanonicalTask, signals: list[TaskSignal]) -> CanonicalTask:
    if not signals:
        return task

    representative = max(
        signals,
        key=lambda signal: (
            1 if signal.subject and signal.subject.lower() != "(no subject)" else 0,
            1 if signal.snippet else 0,
            1 if signal.body_excerpt else 0,
            signal.urgency_word_count + (1 if signal.deadline_hours is not None else 0),
        ),
    )

    return task.model_copy(
        update={
            "representative_source_id": task.representative_source_id or representative.source_id,
            "representative_subject": task.representative_subject or representative.subject,
            "representative_snippet": task.representative_snippet or representative.snippet,
            "representative_body_excerpt": task.representative_body_excerpt or representative.body_excerpt,
            "representative_sender_display": task.representative_sender_display or representative.sender_display,
            "representative_timestamp": task.representative_timestamp or representative.timestamp,
        }
    )


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


@dataclass
class PipelineRunBundle:
    run_id: str
    signals: list[TaskSignal]
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


@dataclass
class FeedbackUpdateContext:
    task: FeedbackTaskContext
    profile: BehaviorProfile | None


def _bundle_user_id(bundle: PipelineRunBundle) -> str | None:
    if bundle.profile is not None:
        return bundle.profile.user_id
    for collection_name in ("task_cards", "canonical_tasks", "signals"):
        collection = getattr(bundle, collection_name, [])
        if collection:
            return collection[0].user_id
    return None


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

    def get_current_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]: ...

    def get_current_task_card(self, user_id: str, canonical_task_id: str) -> PrioritizedTaskCard | None: ...

    def get_current_canonical_task(self, user_id: str, canonical_task_id: str) -> CanonicalTask | None: ...

    def get_feedback_task_context(self, user_id: str, canonical_task_id: str) -> FeedbackTaskContext | None: ...

    def get_feedback_update_context(self, user_id: str, canonical_task_id: str) -> FeedbackUpdateContext | None: ...

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
        self.feedback_events: list[FeedbackEvent] = []
        self.bundles: list[PipelineRunBundle] = []
        self.current_cards: dict[str, PrioritizedTaskCard] = {}
        self.dismissed_cards: set[tuple[str, str]] = set()

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
            existing = {item.source_id: item for item in bucket}
            existing[message.source_id] = message
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

    def get_current_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        cards = [
            card
            for card in self.current_cards.values()
            if card.user_id == user_id and (user_id, card.canonical_task_id) not in self.dismissed_cards
        ]
        return _sort_task_cards(cards)

    def get_current_task_card(self, user_id: str, canonical_task_id: str) -> PrioritizedTaskCard | None:
        card = self.current_cards.get(canonical_task_id)
        if card is None or card.user_id != user_id or (user_id, canonical_task_id) in self.dismissed_cards:
            return None
        return card

    def get_current_canonical_task(self, user_id: str, canonical_task_id: str) -> CanonicalTask | None:
        card = self.get_current_task_card(user_id, canonical_task_id)
        if card is None:
            return None

        for bundle in reversed(self.bundles):
            if bundle.run_id != card.run_id:
                continue
            for task in bundle.canonical_tasks:
                if task.canonical_task_id == canonical_task_id and task.user_id == user_id:
                    return task
        return None

    def get_feedback_task_context(self, user_id: str, canonical_task_id: str) -> FeedbackTaskContext | None:
        card = self.get_current_task_card(user_id, canonical_task_id)
        task = self.get_current_canonical_task(user_id, canonical_task_id)
        if card is None or task is None:
            return None
        return FeedbackTaskContext(
            user_id=user_id,
            canonical_task_id=canonical_task_id,
            task_type=task.task_type,
            entity_key=task.topic_entity.entity_key,
            entity_name=task.topic_entity.entity_name,
            entity_type=task.topic_entity.entity_type,
            sender_ids=list(task.sender_ids),
            deadline_hours=card.deadline_hours,
        )

    def get_feedback_update_context(self, user_id: str, canonical_task_id: str) -> FeedbackUpdateContext | None:
        task = self.get_feedback_task_context(user_id, canonical_task_id)
        if task is None:
            return None
        return FeedbackUpdateContext(task=task, profile=self.get_behavior_profile(user_id))

    def save_feedback_event(self, event: FeedbackEvent) -> None:
        self.feedback_events.append(event)

    def save_feedback_profile_update(self, event: FeedbackEvent, profile: BehaviorProfile) -> None:
        self.feedback_events.append(event)
        self.profiles[profile.user_id] = profile

    def dismiss_task_card(self, user_id: str, canonical_task_id: str) -> bool:
        self.dismissed_cards.add((user_id, canonical_task_id))
        removed = self.current_cards.pop(canonical_task_id, None)
        return removed is not None

    def save_pipeline_results(self, bundle: PipelineRunBundle) -> None:
        self.bundles.append(bundle)
        if bundle.profile is not None:
            self.profiles[bundle.profile.user_id] = bundle.profile
        user_id = _bundle_user_id(bundle)
        if user_id is not None:
            for canonical_task_id, card in list(self.current_cards.items()):
                if card.user_id == user_id:
                    self.current_cards.pop(canonical_task_id, None)
        for card in bundle.task_cards:
            if (card.user_id, card.canonical_task_id) in self.dismissed_cards:
                continue
            self.current_cards[card.canonical_task_id] = card


class SqlAlchemyPipelineRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_run(self, user_id: str) -> str:
        run_id = uuid4().hex
        with Session(self.engine) as session:
            session.add(PipelineRunRecord(run_id=run_id, user_id=user_id))
            session.commit()
        return run_id

    def mark_run_finished(self, run_id: str, *, error_text: str | None = None) -> None:
        with Session(self.engine) as session:
            stmt = (
                update(PipelineRunRecord)
                .where(PipelineRunRecord.run_id == run_id)
                .values(
                    status="failed" if error_text else "finished",
                    error_text=error_text,
                    finished_at=utc_now_naive(),
                )
            )
            session.execute(stmt)
            session.commit()

    def get_raw_messages(self, user_id: str, *, limit: int | None = None) -> list[RawMessage]:
        with Session(self.engine) as session:
            stmt = select(RawMessageRecord).where(RawMessageRecord.user_id == user_id).order_by(RawMessageRecord.id)
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = session.scalars(stmt).all()
            return [RawMessage.model_validate(row.payload) for row in rows]

    def upsert_raw_messages(self, messages: list[RawMessage]) -> None:
        with Session(self.engine) as session:
            for message in messages:
                row = session.scalar(
                    select(RawMessageRecord).where(
                        RawMessageRecord.user_id == message.user_id,
                        RawMessageRecord.source_id == message.source_id,
                    )
                )
                payload = message.model_dump(mode="json")
                if row is None:
                    session.add(
                        RawMessageRecord(
                            user_id=message.user_id,
                            source_id=message.source_id,
                            platform=message.platform.value,
                            payload=payload,
                        )
                    )
                else:
                    row.platform = message.platform.value
                    row.payload = payload
            session.commit()

    def get_behavior_profile(self, user_id: str) -> BehaviorProfile | None:
        with Session(self.engine) as session:
            current_row = session.scalar(
                select(BehaviorProfileRecord)
                .where(BehaviorProfileRecord.user_id == user_id, BehaviorProfileRecord.is_current.is_(True))
                .order_by(BehaviorProfileRecord.profile_version.desc())
            )
            latest_row = session.scalar(
                select(BehaviorProfileRecord)
                .where(BehaviorProfileRecord.user_id == user_id)
                .order_by(BehaviorProfileRecord.profile_version.desc())
            )
            row = latest_row if latest_row is not None and (
                current_row is None or latest_row.profile_version > current_row.profile_version
            ) else current_row
            return None if row is None else BehaviorProfile.model_validate(row.payload)

    def save_behavior_profile(self, profile: BehaviorProfile) -> None:
        with Session(self.engine) as session:
            existing = session.scalar(
                select(BehaviorProfileRecord).where(
                    BehaviorProfileRecord.user_id == profile.user_id,
                    BehaviorProfileRecord.profile_version == profile.profile_version,
                )
            )

            session.execute(
                update(BehaviorProfileRecord)
                .where(BehaviorProfileRecord.user_id == profile.user_id, BehaviorProfileRecord.is_current.is_(True))
                .values(is_current=False)
            )

            payload = profile.model_dump(mode="json")
            if existing is None:
                session.add(
                    BehaviorProfileRecord(
                        user_id=profile.user_id,
                        profile_version=profile.profile_version,
                        is_current=True,
                        payload=payload,
                    )
                )
            else:
                existing.is_current = True
                existing.payload = payload
            session.commit()

    def get_onboarding_context(self, user_id: str) -> OnboardingContext | None:
        with Session(self.engine) as session:
            row = session.get(OnboardingContextRecord, user_id)
            return None if row is None else OnboardingContext.model_validate(row.payload)

    def save_onboarding_context(self, context: OnboardingContext) -> None:
        with Session(self.engine) as session:
            row = session.get(OnboardingContextRecord, context.user_id)
            payload = context.model_dump(mode="json")
            if row is None:
                session.add(OnboardingContextRecord(user_id=context.user_id, payload=payload))
            else:
                row.payload = payload
                row.updated_at = utc_now_naive()
            session.commit()

    def get_entity_aliases(self, user_id: str) -> dict[str, EntityAlias]:
        with Session(self.engine) as session:
            rows = session.scalars(select(EntityAliasRecord).where(EntityAliasRecord.user_id == user_id)).all()
            return {
                row.alias_key: EntityAlias(
                    alias_key=row.alias_key,
                    canonical_entity_key=row.canonical_entity_key,
                    canonical_entity_name=row.canonical_entity_name,
                    entity_type=row.entity_type,
                )
                for row in rows
            }

    def upsert_entity_aliases(self, user_id: str, aliases: list[EntityAlias]) -> None:
        with Session(self.engine) as session:
            for alias in aliases:
                row = session.scalar(
                    select(EntityAliasRecord).where(
                        EntityAliasRecord.user_id == user_id,
                        EntityAliasRecord.alias_key == alias.alias_key,
                    )
                )
                if row is None:
                    session.add(
                        EntityAliasRecord(
                            user_id=user_id,
                            alias_key=alias.alias_key,
                            canonical_entity_key=alias.canonical_entity_key,
                            canonical_entity_name=alias.canonical_entity_name,
                            entity_type=alias.entity_type.value,
                        )
                    )
                else:
                    row.canonical_entity_key = alias.canonical_entity_key
                    row.canonical_entity_name = alias.canonical_entity_name
                    row.entity_type = alias.entity_type.value
            session.commit()

    def get_current_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        with Session(self.engine) as session:
            dismissed_ids = self._get_dismissed_task_ids(session, user_id)
            current_rows = session.scalars(
                select(CurrentTaskCardRecord)
                .where(CurrentTaskCardRecord.user_id == user_id)
                .order_by(CurrentTaskCardRecord.updated_at.desc())
            ).all()
            if not current_rows:
                return []

            task_ids = [row.task_id for row in current_rows]
            task_rows = session.scalars(select(TaskCardRecord).where(TaskCardRecord.task_id.in_(task_ids))).all()
            by_task_id = {row.task_id: PrioritizedTaskCard.model_validate(row.payload) for row in task_rows}
            cards = []
            for row in current_rows:
                if row.canonical_task_id in dismissed_ids or row.task_id not in by_task_id:
                    continue
                card = by_task_id[row.task_id]
                if _task_card_needs_hydration(card):
                    card = self._hydrate_task_card(session, row, card)
                cards.append(card)
            return _sort_task_cards(cards)

    def get_current_task_card(self, user_id: str, canonical_task_id: str) -> PrioritizedTaskCard | None:
        with Session(self.engine) as session:
            dismissed_ids = self._get_dismissed_task_ids(session, user_id)
            if canonical_task_id in dismissed_ids:
                return None
            current = session.scalar(
                select(CurrentTaskCardRecord).where(
                    CurrentTaskCardRecord.user_id == user_id,
                    CurrentTaskCardRecord.canonical_task_id == canonical_task_id,
                )
            )
            if current is None:
                return None
            row = session.scalar(select(TaskCardRecord).where(TaskCardRecord.task_id == current.task_id))
            if row is None:
                return None
            card = PrioritizedTaskCard.model_validate(row.payload)
            if _task_card_needs_hydration(card):
                return self._hydrate_task_card(session, current, card)
            return card

    def get_current_canonical_task(self, user_id: str, canonical_task_id: str) -> CanonicalTask | None:
        with Session(self.engine) as session:
            dismissed_ids = self._get_dismissed_task_ids(session, user_id)
            if canonical_task_id in dismissed_ids:
                return None
            current = session.scalar(
                select(CurrentTaskCardRecord).where(
                    CurrentTaskCardRecord.user_id == user_id,
                    CurrentTaskCardRecord.canonical_task_id == canonical_task_id,
                )
            )
            if current is None:
                return None
            row = session.scalar(
                select(CanonicalTaskRecord).where(
                    CanonicalTaskRecord.run_id == current.run_id,
                    CanonicalTaskRecord.canonical_task_id == canonical_task_id,
                    CanonicalTaskRecord.user_id == user_id,
                )
            )
            if row is None:
                return None
            task = CanonicalTask.model_validate(row.payload)
            signals = self._get_task_signals(session, run_id=current.run_id, user_id=user_id, source_ids=task.source_ids)
            return _enrich_canonical_task(task, signals)

    def get_feedback_task_context(self, user_id: str, canonical_task_id: str) -> FeedbackTaskContext | None:
        with Session(self.engine) as session:
            dismissed_ids = self._get_dismissed_task_ids(session, user_id)
            if canonical_task_id in dismissed_ids:
                return None

            current = session.scalar(
                select(CurrentTaskCardRecord).where(
                    CurrentTaskCardRecord.user_id == user_id,
                    CurrentTaskCardRecord.canonical_task_id == canonical_task_id,
                )
            )
            if current is None:
                return None

            canonical_row = session.scalar(
                select(CanonicalTaskRecord).where(
                    CanonicalTaskRecord.run_id == current.run_id,
                    CanonicalTaskRecord.canonical_task_id == canonical_task_id,
                    CanonicalTaskRecord.user_id == user_id,
                )
            )
            if canonical_row is None:
                return None

            task_row = session.scalar(select(TaskCardRecord).where(TaskCardRecord.task_id == current.task_id))
            canonical_payload = canonical_row.payload or {}
            entity_payload = canonical_payload.get("topic_entity") or {}
            sender_ids = canonical_payload.get("sender_ids") or []
            task_type_value = canonical_payload.get("task_type")
            entity_type_value = entity_payload.get("entity_type")
            deadline_hours = None
            if task_row is not None and isinstance(task_row.payload, dict):
                deadline_hours = task_row.payload.get("deadline_hours")
            if deadline_hours is None:
                deadline_hours = canonical_payload.get("deadline_hours")

            return FeedbackTaskContext(
                user_id=user_id,
                canonical_task_id=canonical_task_id,
                task_type=TaskType(task_type_value) if task_type_value else TaskType.ADMIN,
                entity_key=entity_payload.get("entity_key") or canonical_payload.get("entity_key") or "",
                entity_name=entity_payload.get("entity_name") or "Unknown",
                entity_type=EntityType(entity_type_value) if entity_type_value else EntityType.TOPIC,
                sender_ids=[sender_id for sender_id in sender_ids if sender_id],
                deadline_hours=deadline_hours,
            )

    def get_feedback_update_context(self, user_id: str, canonical_task_id: str) -> FeedbackUpdateContext | None:
        with Session(self.engine) as session:
            dismissed_ids = self._get_dismissed_task_ids(session, user_id)
            if canonical_task_id in dismissed_ids:
                return None

            current = session.scalar(
                select(CurrentTaskCardRecord).where(
                    CurrentTaskCardRecord.user_id == user_id,
                    CurrentTaskCardRecord.canonical_task_id == canonical_task_id,
                )
            )
            if current is None:
                return None

            canonical_row = session.scalar(
                select(CanonicalTaskRecord).where(
                    CanonicalTaskRecord.run_id == current.run_id,
                    CanonicalTaskRecord.canonical_task_id == canonical_task_id,
                    CanonicalTaskRecord.user_id == user_id,
                )
            )
            if canonical_row is None:
                return None

            task_row = session.scalar(select(TaskCardRecord).where(TaskCardRecord.task_id == current.task_id))
            canonical_payload = canonical_row.payload or {}
            entity_payload = canonical_payload.get("topic_entity") or {}
            sender_ids = canonical_payload.get("sender_ids") or []
            task_type_value = canonical_payload.get("task_type")
            entity_type_value = entity_payload.get("entity_type")
            deadline_hours = None
            if task_row is not None and isinstance(task_row.payload, dict):
                deadline_hours = task_row.payload.get("deadline_hours")
            if deadline_hours is None:
                deadline_hours = canonical_payload.get("deadline_hours")

            current_profile = session.scalar(
                select(BehaviorProfileRecord)
                .where(BehaviorProfileRecord.user_id == user_id, BehaviorProfileRecord.is_current.is_(True))
                .order_by(BehaviorProfileRecord.profile_version.desc())
            )
            latest_profile = session.scalar(
                select(BehaviorProfileRecord)
                .where(BehaviorProfileRecord.user_id == user_id)
                .order_by(BehaviorProfileRecord.profile_version.desc())
            )
            profile_row = latest_profile if latest_profile is not None and (
                current_profile is None or latest_profile.profile_version > current_profile.profile_version
            ) else current_profile

            return FeedbackUpdateContext(
                task=FeedbackTaskContext(
                    user_id=user_id,
                    canonical_task_id=canonical_task_id,
                    task_type=TaskType(task_type_value) if task_type_value else TaskType.ADMIN,
                    entity_key=entity_payload.get("entity_key") or canonical_payload.get("entity_key") or "",
                    entity_name=entity_payload.get("entity_name") or "Unknown",
                    entity_type=EntityType(entity_type_value) if entity_type_value else EntityType.TOPIC,
                    sender_ids=[sender_id for sender_id in sender_ids if sender_id],
                    deadline_hours=deadline_hours,
                ),
                profile=None if profile_row is None else BehaviorProfile.model_validate(profile_row.payload),
            )

    def dismiss_task_card(self, user_id: str, canonical_task_id: str) -> bool:
        with Session(self.engine) as session:
            existing = session.scalar(
                select(DismissedTaskRecord).where(
                    DismissedTaskRecord.user_id == user_id,
                    DismissedTaskRecord.canonical_task_id == canonical_task_id,
                )
            )
            if existing is None:
                session.add(DismissedTaskRecord(user_id=user_id, canonical_task_id=canonical_task_id))
            removed = session.execute(
                delete(CurrentTaskCardRecord).where(
                    CurrentTaskCardRecord.user_id == user_id,
                    CurrentTaskCardRecord.canonical_task_id == canonical_task_id,
                )
            )
            session.commit()
            return bool(removed.rowcount or existing is not None)

    def save_feedback_event(self, event: FeedbackEvent) -> None:
        with Session(self.engine) as session:
            session.add(
                FeedbackEventRecord(
                    user_id=event.user_id,
                    canonical_task_id=event.canonical_task_id,
                    action=event.action.value,
                    payload=event.model_dump(mode="json"),
                )
            )
            session.commit()

    def save_feedback_profile_update(self, event: FeedbackEvent, profile: BehaviorProfile) -> None:
        with Session(self.engine) as session:
            session.add(
                FeedbackEventRecord(
                    user_id=event.user_id,
                    canonical_task_id=event.canonical_task_id,
                    action=event.action.value,
                    payload=event.model_dump(mode="json"),
                )
            )

            existing = session.scalar(
                select(BehaviorProfileRecord).where(
                    BehaviorProfileRecord.user_id == profile.user_id,
                    BehaviorProfileRecord.profile_version == profile.profile_version,
                )
            )

            session.execute(
                update(BehaviorProfileRecord)
                .where(BehaviorProfileRecord.user_id == profile.user_id, BehaviorProfileRecord.is_current.is_(True))
                .values(is_current=False)
            )

            payload = profile.model_dump(mode="json")
            if existing is None:
                session.add(
                    BehaviorProfileRecord(
                        user_id=profile.user_id,
                        profile_version=profile.profile_version,
                        is_current=True,
                        payload=payload,
                    )
                )
            else:
                existing.is_current = True
                existing.payload = payload

            session.commit()

    def save_pipeline_results(self, bundle: PipelineRunBundle) -> None:
        with Session(self.engine) as session:
            user_id = _bundle_user_id(bundle)
            dismissed_ids = self._get_dismissed_task_ids(session, bundle.task_cards[0].user_id) if bundle.task_cards else set()
            if user_id is not None:
                dismissed_ids = self._get_dismissed_task_ids(session, user_id)
            for signal in bundle.signals:
                session.add(
                    TaskSignalRecord(
                        run_id=bundle.run_id,
                        user_id=signal.user_id,
                        source_id=signal.source_id,
                        entity_key=signal.topic_entity.entity_key,
                        payload=signal.model_dump(mode="json"),
                    )
                )
            for canonical_task in bundle.canonical_tasks:
                session.add(
                    CanonicalTaskRecord(
                        run_id=bundle.run_id,
                        canonical_task_id=canonical_task.canonical_task_id,
                        user_id=canonical_task.user_id,
                        entity_key=canonical_task.topic_entity.entity_key,
                        payload=canonical_task.model_dump(mode="json"),
                    )
                )
            for decision in bundle.decisions:
                session.add(
                    LlmDecisionRecord(
                        run_id=bundle.run_id,
                        canonical_task_id=decision.canonical_task_id,
                        prompt_version=decision.prompt_version,
                        schema_version_ref=decision.schema_version_ref,
                        payload=decision.model_dump(mode="json"),
                    )
                )
            if user_id is not None:
                session.execute(delete(CurrentTaskCardRecord).where(CurrentTaskCardRecord.user_id == user_id))
            for card in bundle.task_cards:
                session.add(
                    TaskCardRecord(
                        run_id=bundle.run_id,
                        task_id=card.task_id,
                        canonical_task_id=card.canonical_task_id,
                        user_id=card.user_id,
                        payload=card.model_dump(mode="json"),
                    )
                )
                if card.canonical_task_id in dismissed_ids:
                    continue
                current = session.get(CurrentTaskCardRecord, card.canonical_task_id)
                if current is None:
                    session.add(
                        CurrentTaskCardRecord(
                            canonical_task_id=card.canonical_task_id,
                            user_id=card.user_id,
                            task_id=card.task_id,
                            run_id=bundle.run_id,
                            updated_at=utc_now_naive(),
                        )
                    )
                else:
                    current.user_id = card.user_id
                    current.task_id = card.task_id
                    current.run_id = bundle.run_id
                    current.updated_at = utc_now_naive()
            if bundle.profile is not None:
                current_profile = session.scalar(
                    select(BehaviorProfileRecord)
                    .where(
                        BehaviorProfileRecord.user_id == bundle.profile.user_id,
                        BehaviorProfileRecord.is_current.is_(True),
                    )
                    .order_by(BehaviorProfileRecord.profile_version.desc())
                )

                if current_profile is None or current_profile.profile_version <= bundle.profile.profile_version:
                    session.execute(
                        update(BehaviorProfileRecord)
                        .where(
                            BehaviorProfileRecord.user_id == bundle.profile.user_id,
                            BehaviorProfileRecord.is_current.is_(True),
                        )
                        .values(is_current=False)
                    )
                    existing_profile = session.scalar(
                        select(BehaviorProfileRecord).where(
                            BehaviorProfileRecord.user_id == bundle.profile.user_id,
                            BehaviorProfileRecord.profile_version == bundle.profile.profile_version,
                        )
                    )
                    if existing_profile is None:
                        session.add(
                            BehaviorProfileRecord(
                                user_id=bundle.profile.user_id,
                                profile_version=bundle.profile.profile_version,
                                is_current=True,
                                payload=bundle.profile.model_dump(mode="json"),
                            )
                        )
                    else:
                        existing_profile.is_current = True
                        existing_profile.payload = bundle.profile.model_dump(mode="json")
            session.commit()

    def _get_dismissed_task_ids(self, session: Session, user_id: str) -> set[str]:
        rows = session.scalars(select(DismissedTaskRecord).where(DismissedTaskRecord.user_id == user_id)).all()
        return {row.canonical_task_id for row in rows}

    def _get_task_signals(
        self,
        session: Session,
        *,
        run_id: str,
        user_id: str,
        source_ids: list[str],
    ) -> list[TaskSignal]:
        if not source_ids:
            return []
        rows = session.scalars(
            select(TaskSignalRecord).where(
                TaskSignalRecord.run_id == run_id,
                TaskSignalRecord.user_id == user_id,
                TaskSignalRecord.source_id.in_(source_ids),
            )
        ).all()
        return [TaskSignal.model_validate(row.payload) for row in rows]

    def _hydrate_task_card(
        self,
        session: Session,
        current_row: CurrentTaskCardRecord,
        card: PrioritizedTaskCard,
    ) -> PrioritizedTaskCard:
        row = session.scalar(
            select(CanonicalTaskRecord).where(
                CanonicalTaskRecord.run_id == current_row.run_id,
                CanonicalTaskRecord.canonical_task_id == current_row.canonical_task_id,
                CanonicalTaskRecord.user_id == current_row.user_id,
            )
        )
        if row is None:
            return card
        task = CanonicalTask.model_validate(row.payload)
        signals = self._get_task_signals(
            session,
            run_id=current_row.run_id,
            user_id=current_row.user_id,
            source_ids=task.source_ids,
        )
        enriched_task = _enrich_canonical_task(task, signals)
        return _enrich_task_card(card, enriched_task)
