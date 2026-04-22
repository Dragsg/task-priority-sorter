from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pipeline.utils.time import utc_now_naive


class Base(DeclarativeBase):
    pass


class StoredEmailRecord(Base):
    __tablename__ = "stored_emails"
    __table_args__ = (UniqueConstraint("user_id", "platform", "source_id", name="uq_stored_emails_user_platform_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(255), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp_iso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    label_ids: Mapped[list] = mapped_column(JSON, default=list)
    sender_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_display: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_html_present: Mapped[bool] = mapped_column(default=False)
    attachments_present: Mapped[bool] = mapped_column(default=False)
    mime_parts: Mapped[list] = mapped_column(JSON, default=list)
    provider_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    from_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    cc_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    bcc_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now_naive)


class PipelineTaskRecord(Base):
    __tablename__ = "pipeline_tasks"
    __table_args__ = (UniqueConstraint("user_id", "canonical_task_id", name="uq_pipeline_tasks_user_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    canonical_task_id: Mapped[str] = mapped_column(String(128), index=True)
    origin: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_key: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    deadline_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_priority_tier: Mapped[str] = mapped_column(String(16), index=True)
    effective_priority_tier: Mapped[str] = mapped_column(String(16), index=True)
    applied_priority_delta: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_history: Mapped[list] = mapped_column(JSON, default=list)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)


class PipelineUserStateRecord(Base):
    __tablename__ = "pipeline_user_state"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    profile_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    onboarding_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    custom_tags: Mapped[list] = mapped_column(JSON, default=list)
    alias_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now_naive)
