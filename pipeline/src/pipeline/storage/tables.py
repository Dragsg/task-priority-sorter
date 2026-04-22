from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pipeline.utils.time import utc_now_naive


class Base(DeclarativeBase):
    pass


class RawMessageRecord(Base):
    __tablename__ = "raw_messages"
    __table_args__ = (UniqueConstraint("user_id", "source_id", name="uq_raw_messages_user_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    source_id: Mapped[str] = mapped_column(String(255), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class PipelineRunRecord(Base):
    __tablename__ = "pipeline_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), default="started")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskSignalRecord(Base):
    __tablename__ = "task_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    source_id: Mapped[str] = mapped_column(String(255), index=True)
    entity_key: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class CanonicalTaskRecord(Base):
    __tablename__ = "canonical_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    canonical_task_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    entity_key: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class LlmDecisionRecord(Base):
    __tablename__ = "llm_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    canonical_task_id: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[str] = mapped_column(String(64))
    schema_version_ref: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class TaskCardRecord(Base):
    __tablename__ = "task_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    canonical_task_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class CurrentTaskCardRecord(Base):
    __tablename__ = "current_task_cards"

    canonical_task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class DismissedTaskRecord(Base):
    __tablename__ = "dismissed_tasks"
    __table_args__ = (UniqueConstraint("user_id", "canonical_task_id", name="uq_dismissed_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    canonical_task_id: Mapped[str] = mapped_column(String(64), index=True)
    removed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class FeedbackEventRecord(Base):
    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    canonical_task_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class BehaviorProfileRecord(Base):
    __tablename__ = "behavior_profiles"
    __table_args__ = (UniqueConstraint("user_id", "profile_version", name="uq_behavior_profile_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    profile_version: Mapped[int] = mapped_column(Integer, index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class OnboardingContextRecord(Base):
    __tablename__ = "onboarding_context"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class EntityAliasRecord(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (UniqueConstraint("user_id", "alias_key", name="uq_entity_alias_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    alias_key: Mapped[str] = mapped_column(String(255), index=True)
    canonical_entity_key: Mapped[str] = mapped_column(String(255), index=True)
    canonical_entity_name: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(32))
