from pipeline.models import CanonicalTask, PrioritizedTaskCard, TopicEntity
from pipeline.models.enums import ActionWindow, EntityType, Platform, PriorityTier, SenderRole, TaskType
from pipeline.storage.repositories import _enrich_task_card, _task_card_needs_hydration


def test_enrich_task_card_replaces_stale_untitled_placeholder():
    task = CanonicalTask(
        canonical_task_id="canon-1",
        user_id="user-1",
        run_id="run-1",
        task_type=TaskType.SUBMISSION,
        topic_entity=TopicEntity(entity_name="CS2103T", entity_type=EntityType.MODULE, entity_key="cs2103t"),
        source_ids=["msg-1"],
        deadline_hours=12.0,
        priority_score=50,
        priority_tier=PriorityTier.HIGH,
        score_reasons=["deadline under 24 hours"],
        signal_count=1,
        platforms_seen=[Platform.GMAIL],
        sender_roles=[SenderRole.LECTURER],
        sender_ids=["prof.chen"],
        urgency_word_count=1,
        representative_subject="CS2103T project due tonight",
        representative_snippet="Submit your project report by tonight 11:59pm on Canvas.",
        representative_sender_display="Prof Chen",
    )
    card = PrioritizedTaskCard(
        task_id="task-1",
        canonical_task_id="canon-1",
        user_id="user-1",
        run_id="run-1",
        priority_tier=PriorityTier.HIGH,
        action_window=ActionWindow.TODAY,
        rationale="Due soon",
        confidence=0.8,
        needs_user_review=False,
        task_title="Untitled task",
        entity_name="CS2103T",
    )

    enriched = _enrich_task_card(card, task)

    assert "CS2103T project due tonight" in enriched.task_title
    assert "Submit your project report" in enriched.task_title
    assert enriched.task_description is not None
    assert enriched.source_subject == "CS2103T project due tonight"
    assert enriched.source_snippet == "Submit your project report by tonight 11:59pm on Canvas."


def test_task_card_fast_path_skips_hydration_for_complete_cards():
    card = PrioritizedTaskCard(
        task_id="task-2",
        canonical_task_id="canon-2",
        user_id="user-1",
        run_id="run-1",
        priority_tier=PriorityTier.MEDIUM,
        action_window=ActionWindow.THIS_WEEK,
        rationale="Plenty of time remaining.",
        confidence=0.7,
        needs_user_review=False,
        task_title="Submit reflection for CS2103T",
        task_description="Complete and submit the weekly reflection.",
        source_subject="Submit reflection for CS2103T",
        source_snippet="Please upload your weekly reflection by Friday.",
        source_sender="Prof Chen",
        entity_name="CS2103T",
    )

    assert _task_card_needs_hydration(card) is False
