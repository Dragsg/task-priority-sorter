from pipeline.config import PipelineSettings
from pipeline.models import CanonicalTask, StructuredLlmOutput, TopicEntity
from pipeline.models.enums import ActionWindow, EntityType, Platform, PriorityTier, SenderRole, TaskType
from pipeline.services.postprocess import PostProcessor


def make_task(**overrides) -> CanonicalTask:
    payload = {
        "canonical_task_id": "task-1",
        "user_id": "user-1",
        "run_id": "run-1",
        "task_type": TaskType.SUBMISSION,
        "topic_entity": TopicEntity(entity_name="CS2103T", entity_type=EntityType.MODULE, entity_key="cs2103t"),
        "source_ids": ["msg-1"],
        "deadline_hours": 24.0,
        "priority_score": 50,
        "priority_tier": PriorityTier.HIGH,
        "score_reasons": ["deadline under 24 hours"],
        "signal_count": 1,
        "platforms_seen": [Platform.GMAIL],
        "sender_roles": [SenderRole.LECTURER],
        "sender_ids": ["lecturer-1"],
        "urgency_word_count": 1,
        "representative_subject": "CS2103T project update",
        "representative_snippet": "Submit your individual project by tonight 11:59pm on Canvas.",
        "representative_body_excerpt": None,
    }
    payload.update(overrides)
    return CanonicalTask(**payload)


def test_task_title_prefers_subject_plus_detail_over_entity_name():
    processor = PostProcessor(PipelineSettings())

    title = processor._build_task_title(make_task())

    assert "CS2103T project update" in title
    assert "Submit your individual project" in title


def test_task_title_uses_preview_when_subject_is_weak():
    processor = PostProcessor(PipelineSettings())

    title = processor._build_task_title(
        make_task(
            representative_subject="Action Required Important",
            representative_snippet="Submit the reflection worksheet by Friday 5pm.",
        )
    )

    assert title == "Submit the reflection worksheet by Friday 5pm."


def test_task_title_fallback_is_synthetic_not_raw_entity_only():
    processor = PostProcessor(PipelineSettings())

    title = processor._build_task_title(
        make_task(
            representative_subject=None,
            representative_snippet=None,
            representative_body_excerpt=None,
            topic_entity=TopicEntity(
                entity_name="welfare pack collection",
                entity_type=EntityType.CCA,
                entity_key="welfare pack collection",
            ),
            task_type=TaskType.ADMIN,
        )
    )

    assert title == "Task related to welfare pack collection"


def test_best_preview_prefers_complete_body_excerpt_over_truncated_snippet():
    processor = PostProcessor(PipelineSettings())
    task = make_task(
        representative_subject='New assignment: "Collaboration reflection"',
        representative_snippet="Hi NG YING XUAN, Dennis Lam posted a new assignment in 2019 S1-04 ChangeMakers. Due: Jan 20 Level 1: What is my underst",
        representative_body_excerpt=(
            "Dennis Lam posted a new assignment in 2019 S1-04 ChangeMakers: Innovation and Entrepreneurship. "
            "Homework for Week 2. Please complete INDIVIDUALLY and submit your answers by next Monday morning 8.30am."
        ),
    )

    preview = processor._select_best_preview(task)
    description = processor._build_task_description(task, task_title=processor._build_task_title(task))

    assert preview == task.representative_body_excerpt
    assert description is not None
    assert "submit your answers by next Monday morning 8.30am" in description
    assert "Dennis Lam posted" not in description


def test_task_description_extracts_actionable_summary_without_email_boilerplate():
    processor = PostProcessor(PipelineSettings())
    task = make_task(
        representative_subject="Interview invitation",
        representative_snippet=(
            "SYFC CCA invited you to an interview. Please attend the interview tomorrow at 3pm in COM1 "
            "and bring your student ID."
        ),
        representative_body_excerpt=(
            "Singapore Youth Flying Club invited you to an interview for your application. "
            "Please attend the interview tomorrow at 3pm in COM1. "
            "Bring your student ID and transcript."
        ),
    )

    description = processor._build_task_description(task, task_title=processor._build_task_title(task))

    assert description is not None
    assert "attend the interview tomorrow at 3pm in com1" in description.lower()
    assert "bring your student id" in description.lower()
    assert "invited you to an interview for your application" not in description.lower()


def test_build_task_card_infers_tags_even_when_llm_returns_none_and_confidence_is_low():
    processor = PostProcessor(PipelineSettings())
    task = make_task(
        task_type=TaskType.ADMIN,
        representative_subject="Lab registration closes Friday",
        representative_snippet="Register for the chemistry lab before Friday noon.",
        representative_body_excerpt="The chemistry lab registration closes before Friday noon.",
        score_reasons=["deadline under 24 hours"],
    )
    llm_output = StructuredLlmOutput(
        priority_tier=PriorityTier.HIGH,
        action_window=ActionWindow.TODAY,
        rationale="Due soon.",
        confidence=0.2,
        profile_adjustment_made=False,
        adjustment_reason=None,
        tags=[],
    )

    card = processor.build_task_card(
        run_id="run-1",
        task=task,
        llm_output=llm_output,
        profile_version=1,
    )

    assert card.tags == ["admin", "deadline", "lab"]
