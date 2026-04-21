from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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
from pipeline.storage.tables import (
    BehaviorProfileRecord,
    CanonicalTaskRecord,
    CurrentTaskCardRecord,
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


def _sort_task_cards(cards: list[PrioritizedTaskCard]) -> list[PrioritizedTaskCard]:
    return sorted(
        cards,
        key=lambda card: (_PRIORITY_ORDER.get(card.priority_tier.value, 99), card.deadline_hours or float("inf")),
    )


@dataclass
class PipelineRunBundle:
    run_id: str
    signals: list[TaskSignal]
    canonical_tasks: list[CanonicalTask]
    decisions: list[LlmDecision]
    task_cards: list[PrioritizedTaskCard]
    profile: BehaviorProfile | None = None


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

    def save_feedback_event(self, event: FeedbackEvent) -> None: ...

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
        cards = [card for card in self.current_cards.values() if card.user_id == user_id]
        return _sort_task_cards(cards)

    def get_current_task_card(self, user_id: str, canonical_task_id: str) -> PrioritizedTaskCard | None:
        card = self.current_cards.get(canonical_task_id)
        if card is None or card.user_id != user_id:
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

    def save_feedback_event(self, event: FeedbackEvent) -> None:
        self.feedback_events.append(event)

    def save_pipeline_results(self, bundle: PipelineRunBundle) -> None:
        self.bundles.append(bundle)
        if bundle.profile is not None:
            self.profiles[bundle.profile.user_id] = bundle.profile
        for card in bundle.task_cards:
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
            row = session.scalar(
                select(BehaviorProfileRecord)
                .where(BehaviorProfileRecord.user_id == user_id, BehaviorProfileRecord.is_current.is_(True))
                .order_by(BehaviorProfileRecord.profile_version.desc())
            )
            return None if row is None else BehaviorProfile.model_validate(row.payload)

    def save_behavior_profile(self, profile: BehaviorProfile) -> None:
        with Session(self.engine) as session:
            session.execute(
                update(BehaviorProfileRecord)
                .where(BehaviorProfileRecord.user_id == profile.user_id, BehaviorProfileRecord.is_current.is_(True))
                .values(is_current=False)
            )
            session.add(
                BehaviorProfileRecord(
                    user_id=profile.user_id,
                    profile_version=profile.profile_version,
                    is_current=True,
                    payload=profile.model_dump(mode="json"),
                )
            )
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
            cards = [by_task_id[row.task_id] for row in current_rows if row.task_id in by_task_id]
            return _sort_task_cards(cards)

    def get_current_task_card(self, user_id: str, canonical_task_id: str) -> PrioritizedTaskCard | None:
        with Session(self.engine) as session:
            current = session.scalar(
                select(CurrentTaskCardRecord).where(
                    CurrentTaskCardRecord.user_id == user_id,
                    CurrentTaskCardRecord.canonical_task_id == canonical_task_id,
                )
            )
            if current is None:
                return None
            row = session.scalar(select(TaskCardRecord).where(TaskCardRecord.task_id == current.task_id))
            return None if row is None else PrioritizedTaskCard.model_validate(row.payload)

    def get_current_canonical_task(self, user_id: str, canonical_task_id: str) -> CanonicalTask | None:
        with Session(self.engine) as session:
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
            return None if row is None else CanonicalTask.model_validate(row.payload)

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

    def save_pipeline_results(self, bundle: PipelineRunBundle) -> None:
        with Session(self.engine) as session:
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
                session.execute(
                    update(BehaviorProfileRecord)
                    .where(
                        BehaviorProfileRecord.user_id == bundle.profile.user_id,
                        BehaviorProfileRecord.is_current.is_(True),
                    )
                    .values(is_current=False)
                )
                session.add(
                    BehaviorProfileRecord(
                        user_id=bundle.profile.user_id,
                        profile_version=bundle.profile.profile_version,
                        is_current=True,
                        payload=bundle.profile.model_dump(mode="json"),
                    )
                )
            session.commit()
