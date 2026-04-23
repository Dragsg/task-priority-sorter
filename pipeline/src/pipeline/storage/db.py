from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import Engine, MetaData, Table, create_engine, inspect, select
from sqlalchemy.orm import Session

from pipeline.models import BehaviorProfile, CanonicalTask, OnboardingContext, PrioritizedTaskCard
from pipeline.storage.tables import Base, PipelineTaskRecord, PipelineUserStateRecord, StoredEmailRecord
from pipeline.utils.tags import dedupe_tags
from pipeline.utils.time import utc_now_naive

_LEGACY_TABLES = [
    "raw_messages",
    "pipeline_runs",
    "task_signals",
    "canonical_tasks",
    "llm_decisions",
    "task_cards",
    "current_task_cards",
    "dismissed_tasks",
    "feedback_events",
    "behavior_profiles",
    "onboarding_context",
    "entity_aliases",
]


def create_engine_from_url(url: str, *, echo: bool = False) -> Engine:
    connect_args: dict[str, str] = {}
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+psycopg://") or url.startswith("postgresql://"):
        connect_args["options"] = "-c timezone=Asia/Singapore"
    return create_engine(
        url,
        echo=echo,
        future=True,
        connect_args=connect_args,
    )


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    legacy_tables = [table_name for table_name in _LEGACY_TABLES if inspector.has_table(table_name)]
    if not legacy_tables:
        return

    metadata = MetaData()
    with engine.begin() as connection:
        metadata.reflect(connection, only=legacy_tables)

    with Session(engine) as session:
        _migrate_raw_messages(session, metadata)
        _migrate_user_state(session, metadata)
        _migrate_pipeline_tasks(session, metadata)
        session.commit()

    with engine.begin() as connection:
        cleanup_metadata = MetaData()
        cleanup_metadata.reflect(connection, only=legacy_tables)
        for table_name in _LEGACY_TABLES:
            table = cleanup_metadata.tables.get(table_name)
            if table is not None:
                table.drop(connection, checkfirst=True)


def _migrate_raw_messages(session: Session, metadata: MetaData) -> None:
    raw_messages = metadata.tables.get("raw_messages")
    if raw_messages is None:
        return

    rows = session.execute(select(raw_messages)).mappings().all()
    for legacy_row in rows:
        payload = dict(legacy_row.get("payload") or {})
        user_id = legacy_row.get("user_id") or payload.get("user_id")
        source_id = legacy_row.get("source_id") or payload.get("source_id")
        platform = legacy_row.get("platform") or payload.get("platform")
        if user_id is None or source_id is None or platform is None:
            continue
        try:
            db_user_id = int(str(user_id))
        except ValueError:
            continue

        existing = session.scalar(
            select(StoredEmailRecord).where(
                StoredEmailRecord.user_id == db_user_id,
                StoredEmailRecord.platform == str(platform),
                StoredEmailRecord.source_id == str(source_id),
            )
        )
        if existing is not None:
            continue

        session.add(
            StoredEmailRecord(
                user_id=db_user_id,
                platform=str(platform),
                source_id=str(source_id),
                thread_id=payload.get("thread_id"),
                timestamp_iso=_parse_iso_datetime(payload.get("timestamp_iso")),
                label_ids=payload.get("label_ids") or [],
                sender_id=payload.get("sender_id"),
                sender_display=payload.get("sender_display"),
                sender_email=payload.get("sender_email"),
                sender_domain=payload.get("sender_domain"),
                subject=payload.get("subject"),
                snippet=payload.get("snippet"),
                body_text=payload.get("body_text") or "",
                body_html_present=bool(payload.get("body_html_present")),
                attachments_present=bool(payload.get("attachments_present")),
                mime_parts=payload.get("mime_parts") or [],
                provider_metadata=payload.get("provider_metadata") or {},
                from_raw=payload.get("from_raw"),
                to_raw=payload.get("to_raw"),
                cc_raw=payload.get("cc_raw"),
                bcc_raw=payload.get("bcc_raw"),
                created_at=legacy_row.get("created_at") or utc_now_naive(),
                updated_at=legacy_row.get("created_at") or utc_now_naive(),
            )
        )


def _migrate_user_state(session: Session, metadata: MetaData) -> None:
    behavior_profiles = metadata.tables.get("behavior_profiles")
    onboarding_context = metadata.tables.get("onboarding_context")
    entity_aliases = metadata.tables.get("entity_aliases")

    user_ids: set[str] = set()
    if behavior_profiles is not None:
        user_ids.update(str(row.user_id) for row in session.execute(select(behavior_profiles.c.user_id)).all())
    if onboarding_context is not None:
        user_ids.update(str(row.user_id) for row in session.execute(select(onboarding_context.c.user_id)).all())
    if entity_aliases is not None:
        user_ids.update(str(row.user_id) for row in session.execute(select(entity_aliases.c.user_id)).all())

    for user_id in user_ids:
        state = session.get(PipelineUserStateRecord, user_id)
        if state is None:
            state = PipelineUserStateRecord(
                user_id=user_id,
                profile_version=1,
                profile_payload=None,
                onboarding_payload=None,
                custom_tags=[],
                alias_payload={},
                updated_at=utc_now_naive(),
            )
            session.add(state)
            session.flush()

        if behavior_profiles is not None and state.profile_payload is None:
            rows = session.execute(
                select(behavior_profiles).where(behavior_profiles.c.user_id == user_id)
            ).mappings().all()
            if rows:
                latest = max(rows, key=lambda row: int(row.get("profile_version") or 0))
                coerced_profile = _coerce_behavior_profile_payload(latest.get("payload"), user_id)
                state.profile_version = coerced_profile["profile_version"]
                state.profile_payload = coerced_profile

        if onboarding_context is not None and state.onboarding_payload is None:
            legacy = session.execute(
                select(onboarding_context).where(onboarding_context.c.user_id == user_id)
            ).mappings().first()
            if legacy is not None:
                state.onboarding_payload = _coerce_onboarding_payload(legacy.get("payload"), user_id)

        if entity_aliases is not None and not state.alias_payload:
            rows = session.execute(
                select(entity_aliases).where(entity_aliases.c.user_id == user_id)
            ).mappings().all()
            alias_payload = {}
            for row in rows:
                alias_payload[str(row.get("alias_key"))] = {
                    "alias_key": row.get("alias_key"),
                    "canonical_entity_key": row.get("canonical_entity_key"),
                    "canonical_entity_name": row.get("canonical_entity_name"),
                    "entity_type": row.get("entity_type"),
                }
            state.alias_payload = alias_payload
        state.updated_at = utc_now_naive()


def _migrate_pipeline_tasks(session: Session, metadata: MetaData) -> None:
    task_cards = metadata.tables.get("task_cards")
    current_task_cards = metadata.tables.get("current_task_cards")
    canonical_tasks = metadata.tables.get("canonical_tasks")
    dismissed_tasks = metadata.tables.get("dismissed_tasks")

    if task_cards is None or canonical_tasks is None:
        return

    task_card_rows = session.execute(select(task_cards)).mappings().all()
    by_task_id = {str(row.get("task_id")): row for row in task_card_rows if row.get("task_id") is not None}
    latest_task_card_by_task = {
        (str(row.get("user_id")), str(row.get("canonical_task_id"))): row
        for row in task_card_rows
        if row.get("user_id") is not None and row.get("canonical_task_id") is not None
    }

    canonical_rows = session.execute(select(canonical_tasks)).mappings().all()
    canonical_by_exact_key = {
        (str(row.get("user_id")), str(row.get("canonical_task_id")), str(row.get("run_id"))): row
        for row in canonical_rows
        if row.get("user_id") is not None and row.get("canonical_task_id") is not None and row.get("run_id") is not None
    }
    canonical_by_task_key = {
        (str(row.get("user_id")), str(row.get("canonical_task_id"))): row
        for row in canonical_rows
        if row.get("user_id") is not None and row.get("canonical_task_id") is not None
    }

    dismissed_by_key: dict[tuple[str, str], Any] = {}
    if dismissed_tasks is not None:
        dismissed_rows = session.execute(select(dismissed_tasks)).mappings().all()
        dismissed_by_key = {
            (str(row.get("user_id")), str(row.get("canonical_task_id"))): row
            for row in dismissed_rows
            if row.get("user_id") is not None and row.get("canonical_task_id") is not None
        }

    migrated_keys: set[tuple[str, str]] = set()
    if current_task_cards is not None:
        current_rows = session.execute(select(current_task_cards)).mappings().all()
        for current_row in current_rows:
            user_id = str(current_row.get("user_id"))
            canonical_task_id = str(current_row.get("canonical_task_id"))
            task_id = str(current_row.get("task_id"))
            if session.scalar(
                select(PipelineTaskRecord).where(
                    PipelineTaskRecord.user_id == user_id,
                    PipelineTaskRecord.canonical_task_id == canonical_task_id,
                )
            ):
                migrated_keys.add((user_id, canonical_task_id))
                continue

            task_row = by_task_id.get(task_id)
            canonical_row = canonical_by_exact_key.get((user_id, canonical_task_id, str(current_row.get("run_id"))))
            if canonical_row is None:
                canonical_row = canonical_by_task_key.get((user_id, canonical_task_id))
            if task_row is None or canonical_row is None:
                continue

            _insert_migrated_task(
                session,
                user_id=user_id,
                canonical_task_id=canonical_task_id,
                task_payload=task_row.get("payload"),
                canonical_payload=canonical_row.get("payload"),
                status="pending_review",
                status_timestamp=current_row.get("updated_at"),
            )
            migrated_keys.add((user_id, canonical_task_id))

    for key, dismissed_row in dismissed_by_key.items():
        if key in migrated_keys:
            continue
        user_id, canonical_task_id = key
        task_row = latest_task_card_by_task.get((user_id, canonical_task_id))
        canonical_row = canonical_by_task_key.get((user_id, canonical_task_id))
        if task_row is None or canonical_row is None:
            continue
        if session.scalar(
            select(PipelineTaskRecord).where(
                PipelineTaskRecord.user_id == user_id,
                PipelineTaskRecord.canonical_task_id == canonical_task_id,
            )
        ):
            continue
        _insert_migrated_task(
            session,
            user_id=user_id,
            canonical_task_id=canonical_task_id,
            task_payload=task_row.get("payload"),
            canonical_payload=canonical_row.get("payload"),
            status="rejected",
            status_timestamp=dismissed_row.get("removed_at"),
        )


def _insert_migrated_task(
    session: Session,
    *,
    user_id: str,
    canonical_task_id: str,
    task_payload: dict[str, Any] | None,
    canonical_payload: dict[str, Any] | None,
    status: str,
    status_timestamp: Any,
) -> None:
    coerced_canonical = _coerce_canonical_task_payload(canonical_payload, user_id)
    canonical_task = CanonicalTask.model_validate(coerced_canonical)
    coerced_task_card = _coerce_task_card_payload(task_payload, canonical_task.model_dump(mode="json"), user_id, status)
    card = PrioritizedTaskCard.model_validate(coerced_task_card)
    timestamp = status_timestamp or utc_now_naive()

    session.add(
        PipelineTaskRecord(
            user_id=user_id,
            canonical_task_id=canonical_task_id,
            origin=card.origin.value,
            status=status,
            task_type=card.task_type.value,
            entity_key=card.entity_key,
            deadline_hours=card.deadline_hours,
            suggested_priority_tier=card.suggested_priority_tier.value,
            effective_priority_tier=card.effective_priority_tier.value,
            applied_priority_delta=0,
            confidence=card.confidence,
            tags=dedupe_tags(card.tags),
            payload={
                "task_card": card.model_dump(mode="json"),
                "canonical_task": canonical_task.model_dump(mode="json"),
                "llm_decision": None,
            },
            decision_history=[],
            accepted_at=timestamp if status == "accepted" else None,
            rejected_at=timestamp if status == "rejected" else None,
            completed_at=timestamp if status == "completed" else None,
            deleted_at=timestamp if status == "deleted" else None,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )


def _coerce_behavior_profile_payload(payload: Any, user_id: str) -> dict[str, Any]:
    data = dict(payload or {})
    data["schema_version"] = "behavior_profile.v2"
    data["user_id"] = str(data.get("user_id") or user_id)
    data["profile_version"] = int(data.get("profile_version") or 1)
    data.setdefault("confidence", 0.0)
    data.setdefault("task_type_start_leads", {})
    data.setdefault("entity_weights", {})
    data.setdefault("sender_weights", {})
    data.setdefault("task_type_weights", {})
    data.setdefault("tag_weights", {})
    data.setdefault("decision_window", [])
    data.setdefault("peak_action_hour", None)
    data.setdefault("low_energy_hours", [])
    data.setdefault("action_hours", [])
    data.setdefault("user_salt", hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:16])
    return BehaviorProfile.model_validate(data).model_dump(mode="json")


def _coerce_onboarding_payload(payload: Any, user_id: str) -> dict[str, Any]:
    data = dict(payload or {})
    data["schema_version"] = "onboarding_context.v2"
    data["user_id"] = str(data.get("user_id") or user_id)
    data.setdefault("timezone", "Asia/Singapore")
    data.setdefault("timetable_summary", None)
    data.setdefault("busy_windows", [])
    data.setdefault("recurring_task_notes", [])
    data.setdefault("static_preferences", {})
    data.setdefault("calendar_source", None)
    return OnboardingContext.model_validate(data).model_dump(mode="json")


def _coerce_canonical_task_payload(payload: Any, user_id: str) -> dict[str, Any]:
    data = dict(payload or {})
    platforms_seen = data.get("platforms_seen") or []
    origin = data.get("origin") or ("manual" if "manual" in platforms_seen else "email")
    data["schema_version"] = "canonical_task.v2"
    data["user_id"] = str(data.get("user_id") or user_id)
    data["origin"] = origin
    data.setdefault("manual_tags", [])
    return CanonicalTask.model_validate(data).model_dump(mode="json")


def _coerce_task_card_payload(
    payload: Any,
    canonical_payload: dict[str, Any],
    user_id: str,
    status: str,
) -> dict[str, Any]:
    data = dict(payload or {})
    priority_tier = data.get("effective_priority_tier") or data.get("priority_tier") or "LOW"
    data["schema_version"] = "task_card.v2"
    data["user_id"] = str(data.get("user_id") or user_id)
    data["status"] = status
    data.setdefault("origin", canonical_payload.get("origin") or "email")
    data.setdefault("task_type", canonical_payload.get("task_type") or "admin")
    data.setdefault("entity_key", canonical_payload.get("topic_entity", {}).get("entity_key"))
    data["priority_tier"] = priority_tier
    data.setdefault("suggested_priority_tier", priority_tier)
    data.setdefault("effective_priority_tier", priority_tier)
    data.setdefault("applied_priority_delta", 0)
    data.setdefault("action_window", data.get("action_window") or "THIS_WEEK")
    data.setdefault("rationale", data.get("rationale") or "Migrated task card.")
    data.setdefault("confidence", float(data.get("confidence") or 0.0))
    data.setdefault("needs_user_review", bool(data.get("needs_user_review", True)))
    data.setdefault("deadline_hours", canonical_payload.get("deadline_hours"))
    data.setdefault("platforms_seen", canonical_payload.get("platforms_seen") or [])
    data.setdefault("profile_adjustment_made", bool(data.get("profile_adjustment_made", False)))
    data.setdefault("adjustment_reason", data.get("adjustment_reason"))
    data.setdefault("evidence_source_ids", canonical_payload.get("source_ids") or [])
    data.setdefault("task_title", data.get("task_title"))
    data.setdefault("task_description", data.get("task_description"))
    data.setdefault("source_subject", data.get("source_subject") or canonical_payload.get("representative_subject"))
    data.setdefault("source_snippet", data.get("source_snippet") or canonical_payload.get("representative_snippet"))
    data.setdefault("source_sender", data.get("source_sender") or canonical_payload.get("representative_sender_display"))
    timestamp = canonical_payload.get("representative_timestamp")
    data.setdefault("source_timestamp_iso", timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp)
    data.setdefault("entity_name", data.get("entity_name") or canonical_payload.get("topic_entity", {}).get("entity_name"))
    data.setdefault("entity_type", data.get("entity_type") or canonical_payload.get("topic_entity", {}).get("entity_type"))
    data.setdefault("score_reasons", data.get("score_reasons") or canonical_payload.get("score_reasons") or [])
    data.setdefault("profile_version", data.get("profile_version"))
    data.setdefault("prompt_version", data.get("prompt_version"))
    data.setdefault("schema_version_ref", data.get("schema_version_ref"))
    data.setdefault("sender_ids", canonical_payload.get("sender_ids") or [])
    data.setdefault("tags", dedupe_tags(data.get("tags") or canonical_payload.get("manual_tags") or []))
    return PrioritizedTaskCard.model_validate(data).model_dump(mode="json")


def _parse_iso_datetime(value: Any):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
