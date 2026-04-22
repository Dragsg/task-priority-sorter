from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict

from pipeline.models.enums import (
    ActionWindow,
    EntityType,
    FeedbackAction,
    FeedbackDirection,
    Platform,
    PriorityTier,
    SenderRole,
    TaskType,
)
from pipeline.utils.time import utc_now_naive


class MimePartSummary(BaseModel):
    mime_type: str | None = None
    filename: str | None = None
    size_bytes: int | None = None


class ProviderMetadata(BaseModel):
    thread_position: int | None = None
    folder: str | None = None
    importance: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RawMessage(BaseModel):
    schema_version: Literal["raw_message.v1"] = "raw_message.v1"
    user_id: str
    platform: Platform
    source_id: str
    thread_id: str | None = None
    timestamp_iso: str | None = None
    label_ids: list[str] = Field(default_factory=list)
    sender_id: str | None = None
    sender_display: str | None = None
    sender_email: str | None = None
    sender_domain: str | None = None
    subject: str | None = None
    snippet: str | None = None
    body_text: str = ""
    body_html_present: bool = False
    attachments_present: bool = False
    mime_parts: list[MimePartSummary] = Field(default_factory=list)
    provider_metadata: ProviderMetadata = Field(default_factory=ProviderMetadata)
    from_raw: str | None = None
    to_raw: str | None = None
    cc_raw: str | None = None
    bcc_raw: str | None = None


class TopicEntity(BaseModel):
    entity_name: str
    entity_type: EntityType
    entity_key: str


class TaskSignal(BaseModel):
    schema_version: Literal["task_signal.v1"] = "task_signal.v1"
    user_id: str
    run_id: str | None = None
    source_id: str
    platform: Platform
    timestamp: datetime | None = None
    sender_id: str | None = None
    sender_display: str | None = None
    sender_role: SenderRole = SenderRole.UNKNOWN
    subject: str | None = None
    snippet: str | None = None
    body_excerpt: str | None = None
    task_type: TaskType = TaskType.ADMIN
    has_task: bool = False
    task_verbs_found: list[str] = Field(default_factory=list)
    urgency_word_count: int = 0
    urgency_terms: list[str] = Field(default_factory=list)
    deadline_hours: float | None = None
    deadline_at: datetime | None = None
    score_reasons: list[str] = Field(default_factory=list)
    priority_score: int | None = None
    priority_tier: PriorityTier | None = None
    topic_entity: TopicEntity
    signal_count: int = 1
    platforms_seen: list[Platform] = Field(default_factory=list)


class CanonicalTask(BaseModel):
    schema_version: Literal["canonical_task.v1"] = "canonical_task.v1"
    canonical_task_id: str
    user_id: str
    run_id: str
    task_type: TaskType
    topic_entity: TopicEntity
    source_ids: list[str]
    deadline_hours: float | None = None
    priority_score: int | None = None
    priority_tier: PriorityTier | None = None
    score_reasons: list[str] = Field(default_factory=list)
    signal_count: int = 1
    platforms_seen: list[Platform] = Field(default_factory=list)
    sender_roles: list[SenderRole] = Field(default_factory=list)
    sender_ids: list[str] = Field(default_factory=list)
    urgency_word_count: int = 0
    representative_source_id: str | None = None
    representative_subject: str | None = None
    representative_snippet: str | None = None
    representative_body_excerpt: str | None = None
    representative_sender_display: str | None = None
    representative_timestamp: datetime | None = None


class EntityWeight(BaseModel):
    entity_name: str
    entity_key: str
    entity_type: EntityType
    priority_multiplier: float = 1.0
    defer_rate: float | None = None
    avg_start_lead_hours: float | None = None
    observation_count: int = 0


class SenderWeight(BaseModel):
    sender_hash: str
    label: str | None = None
    response_rate: float | None = None
    avg_response_lead_hours: float | None = None
    observation_count: int = 0
    weight: float = 1.0


class BehaviorProfile(BaseModel):
    schema_version: Literal["behavior_profile.v1"] = "behavior_profile.v1"
    user_id: str
    profile_version: int = 1
    confidence: float = 0.0
    task_type_start_leads: dict[TaskType, float] = Field(default_factory=dict)
    entity_weights: dict[str, EntityWeight] = Field(default_factory=dict)
    sender_weights: dict[str, SenderWeight] = Field(default_factory=dict)
    decision_window: list[float] = Field(default_factory=list)
    peak_action_hour: int | None = None
    low_energy_hours: list[int] = Field(default_factory=list)
    action_hours: list[int] = Field(default_factory=list)
    user_salt: str


class AvailabilityWindow(BaseModel):
    start_iso: str
    end_iso: str
    label: str | None = None


class OnboardingContext(BaseModel):
    schema_version: Literal["onboarding_context.v1"] = "onboarding_context.v1"
    user_id: str
    timezone: str = "Asia/Singapore"
    timetable_summary: str | None = None
    busy_windows: list[AvailabilityWindow] = Field(default_factory=list)
    recurring_task_notes: list[str] = Field(default_factory=list)
    static_preferences: dict[str, Any] = Field(default_factory=dict)


class FeedbackEvent(BaseModel):
    schema_version: Literal["feedback_event.v1"] = "feedback_event.v1"
    user_id: str
    canonical_task_id: str
    action: FeedbackAction
    direction: FeedbackDirection | None = None
    occurred_at: datetime = Field(default_factory=utc_now_naive)
    task_type: TaskType | None = None
    entity_key: str | None = None
    entity_name: str | None = None
    entity_type: EntityType | None = None
    sender_hash: str | None = None
    deadline_hours: float | None = None


class LlmDecision(BaseModel):
    schema_version: Literal["llm_decision.v1"] = "llm_decision.v1"
    run_id: str
    canonical_task_id: str
    prompt_version: str
    schema_version_ref: str
    provider: str = "openai"
    model: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now_naive)


class PrioritizedTaskCard(BaseModel):
    schema_version: Literal["task_card.v1"] = "task_card.v1"
    task_id: str
    canonical_task_id: str
    user_id: str
    run_id: str
    priority_tier: PriorityTier
    action_window: ActionWindow
    rationale: str
    confidence: float
    needs_user_review: bool
    deadline_hours: float | None = None
    platforms_seen: list[Platform] = Field(default_factory=list)
    profile_adjustment_made: bool = False
    adjustment_reason: str | None = None
    evidence_source_ids: list[str] = Field(default_factory=list)
    task_title: str | None = None
    task_description: str | None = None
    source_subject: str | None = None
    source_snippet: str | None = None
    source_sender: str | None = None
    source_timestamp_iso: str | None = None
    entity_name: str | None = None
    entity_type: EntityType | None = None
    score_reasons: list[str] = Field(default_factory=list)
    profile_version: int | None = None
    prompt_version: str | None = None
    schema_version_ref: str | None = None


class EntityAlias(BaseModel):
    alias_key: str
    canonical_entity_key: str
    canonical_entity_name: str
    entity_type: EntityType


class StructuredLlmOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority_tier: PriorityTier
    action_window: ActionWindow
    rationale: str
    confidence: float
    profile_adjustment_made: bool
    adjustment_reason: str | None = None
