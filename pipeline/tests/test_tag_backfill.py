from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from pipeline.models import CanonicalTask, PrioritizedTaskCard, TopicEntity
from pipeline.models.enums import ActionWindow, EntityType, Platform, PriorityTier, SenderRole, TaskStatus, TaskType
from pipeline.jobs.backfill_tags import retag_pipeline_tasks
from pipeline.storage.tables import Base, PipelineTaskRecord, PipelineUserStateRecord
from pipeline.utils.time import utc_now_naive


def test_retag_pipeline_tasks_backfills_tags_in_row_and_payload():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    task = CanonicalTask(
        canonical_task_id="canon-1",
        user_id="7",
        run_id="run-1",
        task_type=TaskType.READING,
        topic_entity=TopicEntity(entity_name="Weekly Digest", entity_type=EntityType.TOPIC, entity_key="weekly-digest"),
        source_ids=["msg-1"],
        priority_score=10,
        priority_tier=PriorityTier.LOW,
        score_reasons=[],
        platforms_seen=[Platform.GMAIL],
        sender_roles=[SenderRole.UNKNOWN],
        sender_ids=["digest@example.com"],
        representative_subject="Weekly newsletter announcement",
        representative_snippet="Newsletter and announcement roundup for this week.",
        representative_sender_display="Weekly Digest",
    )
    card = PrioritizedTaskCard(
        task_id="task-1",
        canonical_task_id="canon-1",
        user_id="7",
        run_id="run-1",
        status=TaskStatus.PENDING_REVIEW,
        task_type=TaskType.READING,
        entity_key="weekly-digest",
        priority_tier=PriorityTier.LOW,
        action_window=ActionWindow.THIS_WEEK,
        rationale="Read when free.",
        confidence=0.8,
        needs_user_review=False,
        task_title="Weekly newsletter announcement",
        source_subject="Weekly newsletter announcement",
        source_snippet="Newsletter and announcement roundup for this week.",
        source_sender="Weekly Digest",
        entity_name="Weekly Digest",
        entity_type=EntityType.TOPIC,
        sender_ids=["digest@example.com"],
        tags=[],
    )

    with Session(engine) as session:
        session.add(
            PipelineUserStateRecord(
                user_id="7",
                custom_tags=[],
                alias_payload={},
                profile_payload=None,
                onboarding_payload=None,
                updated_at=utc_now_naive(),
            )
        )
        session.add(
            PipelineTaskRecord(
                user_id="7",
                canonical_task_id="canon-1",
                origin="email",
                status="pending_review",
                task_type="reading",
                entity_key="weekly-digest",
                deadline_hours=None,
                suggested_priority_tier="LOW",
                effective_priority_tier="LOW",
                applied_priority_delta=0,
                confidence=0.8,
                tags=[],
                payload={
                    "task_card": card.model_dump(mode="json"),
                    "canonical_task": task.model_dump(mode="json"),
                    "llm_decision": None,
                },
                decision_history=[],
                created_at=utc_now_naive(),
                updated_at=utc_now_naive(),
            )
        )
        session.commit()

    result = retag_pipeline_tasks(engine)

    assert result == {"scanned": 1, "updated": 1, "skipped": 0}

    with Session(engine) as session:
        row = session.scalar(select(PipelineTaskRecord).where(PipelineTaskRecord.canonical_task_id == "canon-1"))
        assert row is not None
        assert row.tags == ["newsletter", "announcement"]
        assert row.payload["task_card"]["tags"] == ["newsletter", "announcement"]
