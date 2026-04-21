from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from pipeline.config import PipelineSettings
from pipeline.models import (
    BehaviorProfile,
    CanonicalTask,
    EntityAlias,
    FeedbackAction,
    FeedbackDirection,
    FeedbackEvent,
    OnboardingContext,
    PrioritizedTaskCard,
    RawMessage,
)
from pipeline.services.pipeline import PriorityPipeline
from pipeline.storage.repositories import PipelineRepository, PipelineRunBundle


class FeedbackRequest(BaseModel):
    action: FeedbackAction
    direction: FeedbackDirection | None = None

    @model_validator(mode="after")
    def validate_direction(self) -> "FeedbackRequest":
        if self.action == FeedbackAction.WRONG_PRIORITY and self.direction is None:
            raise ValueError("direction is required when action is WRONG_PRIORITY")
        if self.action != FeedbackAction.WRONG_PRIORITY:
            self.direction = None
        return self


class UpsertMessagesRequest(BaseModel):
    messages: list[RawMessage] = Field(default_factory=list)


class UpsertAliasesRequest(BaseModel):
    aliases: list[EntityAlias] = Field(default_factory=list)


class TaskCardsResponse(BaseModel):
    items: list[PrioritizedTaskCard]


class PipelineRunResponse(BaseModel):
    run_id: str
    raw_message_count: int
    signal_count: int
    canonical_task_count: int
    task_card_count: int


class FeedbackResponse(BaseModel):
    feedback_event: FeedbackEvent
    profile: BehaviorProfile


class PipelineApiService:
    def __init__(
        self,
        repository: PipelineRepository,
        *,
        settings: PipelineSettings | None = None,
        pipeline: PriorityPipeline | None = None,
    ) -> None:
        self.settings = settings or PipelineSettings()
        self.repository = repository
        self.pipeline = pipeline or PriorityPipeline(repository, settings=self.settings)

    def ingest_raw_messages(self, user_id: str, messages: list[RawMessage]) -> int:
        normalized = [message.model_copy(update={"user_id": user_id}) for message in messages]
        self.repository.upsert_raw_messages(normalized)
        return len(normalized)

    def save_onboarding_context(self, user_id: str, context: OnboardingContext) -> OnboardingContext:
        normalized = context.model_copy(update={"user_id": user_id})
        self.repository.save_onboarding_context(normalized)
        return normalized

    def save_entity_aliases(self, user_id: str, aliases: list[EntityAlias]) -> int:
        self.repository.upsert_entity_aliases(user_id, aliases)
        return len(aliases)

    def get_profile(self, user_id: str) -> BehaviorProfile:
        return self.repository.get_behavior_profile(user_id) or self.pipeline.profile_service.create_default_profile(user_id)

    def get_onboarding_context(self, user_id: str) -> OnboardingContext:
        return self.repository.get_onboarding_context(user_id) or OnboardingContext(user_id=user_id)

    def list_task_cards(self, user_id: str) -> list[PrioritizedTaskCard]:
        return self.repository.get_current_task_cards(user_id)

    def run_pipeline(self, user_id: str, *, limit: int | None = None) -> PipelineRunBundle:
        return self.pipeline.run_for_user(user_id, limit=limit)

    def submit_feedback(
        self,
        user_id: str,
        canonical_task_id: str,
        *,
        action: FeedbackAction,
        direction: FeedbackDirection | None = None,
    ) -> tuple[FeedbackEvent, BehaviorProfile]:
        task_card = self.repository.get_current_task_card(user_id, canonical_task_id)
        canonical_task = self.repository.get_current_canonical_task(user_id, canonical_task_id)
        if task_card is None or canonical_task is None:
            raise LookupError(f"No current task found for canonical_task_id={canonical_task_id!r}")

        profile = self.repository.get_behavior_profile(user_id) or self.pipeline.profile_service.create_default_profile(user_id)
        sender_hash = self._sender_hash_for_task(profile, canonical_task)
        event = FeedbackEvent(
            user_id=user_id,
            canonical_task_id=canonical_task_id,
            action=action,
            direction=direction,
            task_type=canonical_task.task_type,
            entity_key=canonical_task.topic_entity.entity_key,
            entity_name=canonical_task.topic_entity.entity_name,
            entity_type=canonical_task.topic_entity.entity_type,
            sender_hash=sender_hash,
            deadline_hours=task_card.deadline_hours,
        )
        updated = self.pipeline.apply_feedback(event)
        return event, updated

    def _sender_hash_for_task(self, profile: BehaviorProfile, task: CanonicalTask) -> str | None:
        for sender_id in task.sender_ids:
            if sender_id:
                return self.pipeline.profile_service.hash_identity(user_salt=profile.user_salt, identifier=sender_id)
        return None
