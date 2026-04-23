from pipeline.config import PipelineSettings
from pipeline.models import (
    ActionWindow,
    BehaviorProfile,
    CanonicalTask,
    OnboardingContext,
    TopicEntity,
)
from pipeline.models.enums import EntityType, Platform, PriorityTier, SenderRole, TaskType
from pipeline.services.llm import PriorityReasoner
import pipeline.services.llm as llm_module


def test_timetable_can_change_action_window_without_changing_tier():
    settings = PipelineSettings()
    reasoner = PriorityReasoner(settings, client=None)
    task = CanonicalTask(
        canonical_task_id="task-1",
        user_id="user-1",
        run_id="run-1",
        task_type=TaskType.SUBMISSION,
        topic_entity=TopicEntity(entity_name="CS2103T", entity_type=EntityType.MODULE, entity_key="cs2103t"),
        source_ids=["msg-1"],
        deadline_hours=30,
        priority_score=50,
        priority_tier=PriorityTier.HIGH,
        score_reasons=["deadline within 3 days"],
        platforms_seen=[Platform.GMAIL],
        sender_roles=[SenderRole.LECTURER],
    )
    profile = BehaviorProfile(user_id="user-1", user_salt="salt-1", confidence=0.2)
    onboarding = OnboardingContext(
        user_id="user-1",
        timetable_summary="Busy in the afternoon",
        busy_windows=[],
    )

    llm_input = reasoner.build_llm_input(
        task=task,
        profile=profile,
        onboarding=onboarding,
        entity_context=None,
        sender_context=None,
        can_personalize=False,
        current_hour=13,
    )
    output, _ = reasoner.reason_task(run_id="run-1", task=task, llm_input=llm_input)

    assert output.priority_tier == PriorityTier.HIGH
    assert output.action_window in {ActionWindow.TODAY, ActionWindow.THIS_WEEK}


def test_reasoner_builds_few_shot_messages_for_current_schema():
    settings = PipelineSettings()
    reasoner = PriorityReasoner(settings, client=None)
    task = CanonicalTask(
        canonical_task_id="task-1",
        user_id="user-1",
        run_id="run-1",
        task_type=TaskType.SUBMISSION,
        topic_entity=TopicEntity(entity_name="CS2103T", entity_type=EntityType.MODULE, entity_key="cs2103t"),
        source_ids=["msg-1"],
        deadline_hours=9,
        priority_score=60,
        priority_tier=PriorityTier.HIGH,
        score_reasons=["deadline under 24 hours", "graded submission"],
        platforms_seen=[Platform.GMAIL],
        sender_roles=[SenderRole.LECTURER],
    )
    profile = BehaviorProfile(user_id="user-1", user_salt="salt-1", confidence=0.9)
    onboarding = OnboardingContext(user_id="user-1", timetable_summary="Evening free")

    llm_input = reasoner.build_llm_input(
        task=task,
        profile=profile,
        onboarding=onboarding,
        entity_context=None,
        sender_context=None,
        can_personalize=False,
        current_hour=20,
    )
    messages = reasoner._request_messages(llm_input)

    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert len(messages) == 1 + (3 * 2) + 1
    assert '"entity_name": "CS2103T"' in messages[-1]["content"][0]["text"]


def test_reasoner_uses_singapore_hour_by_default(monkeypatch):
    settings = PipelineSettings()
    reasoner = PriorityReasoner(settings, client=None)
    task = CanonicalTask(
        canonical_task_id="task-1",
        user_id="user-1",
        run_id="run-1",
        task_type=TaskType.SUBMISSION,
        topic_entity=TopicEntity(entity_name="CS2103T", entity_type=EntityType.MODULE, entity_key="cs2103t"),
        source_ids=["msg-1"],
        priority_tier=PriorityTier.HIGH,
        platforms_seen=[Platform.GMAIL],
        sender_roles=[SenderRole.LECTURER],
    )
    profile = BehaviorProfile(user_id="user-1", user_salt="salt-1", confidence=0.9)
    onboarding = OnboardingContext(user_id="user-1")

    monkeypatch.setattr(llm_module, "current_hour_for_timezone", lambda timezone_name, fallback: 2)

    llm_input = reasoner.build_llm_input(
        task=task,
        profile=profile,
        onboarding=onboarding,
        entity_context=None,
        sender_context=None,
        can_personalize=False,
    )

    assert onboarding.timezone == "Asia/Singapore"
    assert settings.provider_timezone_fallback == "Asia/Singapore"
    assert llm_input["user_context"]["current_hour"] == 2


def test_fallback_reasoner_confidence_varies_with_task_evidence():
    settings = PipelineSettings()
    reasoner = PriorityReasoner(settings, client=None)
    profile = BehaviorProfile(user_id="user-1", user_salt="salt-1", confidence=0.2)
    onboarding = OnboardingContext(user_id="user-1", timetable_summary="Evening free")

    low_signal_task = CanonicalTask(
        canonical_task_id="task-low",
        user_id="user-1",
        run_id="run-1",
        task_type=TaskType.READING,
        topic_entity=TopicEntity(entity_name="Weekly Digest", entity_type=EntityType.TOPIC, entity_key="weekly_digest"),
        source_ids=["msg-low"],
        priority_tier=PriorityTier.LOW,
        score_reasons=["single low-signal mention"],
        signal_count=1,
        representative_subject="Weekly newsletter",
        representative_snippet="Weekly roundup.",
        platforms_seen=[Platform.GMAIL],
        sender_roles=[SenderRole.UNKNOWN],
    )
    high_signal_task = CanonicalTask(
        canonical_task_id="task-high",
        user_id="user-1",
        run_id="run-1",
        task_type=TaskType.SUBMISSION,
        topic_entity=TopicEntity(entity_name="CS2103T", entity_type=EntityType.MODULE, entity_key="cs2103t"),
        source_ids=["msg-high"],
        deadline_hours=8,
        priority_tier=PriorityTier.HIGH,
        score_reasons=["deadline under 24 hours", "graded submission", "mentioned across platforms"],
        signal_count=4,
        representative_subject="CS2103T reflection due tonight",
        representative_snippet="Submit your reflection by tonight 11:59pm on Canvas.",
        platforms_seen=[Platform.GMAIL, Platform.TEAMS],
        sender_roles=[SenderRole.LECTURER],
    )

    low_input = reasoner.build_llm_input(
        task=low_signal_task,
        profile=profile,
        onboarding=onboarding,
        entity_context=None,
        sender_context=None,
        can_personalize=False,
        current_hour=14,
    )
    high_input = reasoner.build_llm_input(
        task=high_signal_task,
        profile=profile,
        onboarding=onboarding,
        entity_context=None,
        sender_context=None,
        can_personalize=False,
        current_hour=20,
    )

    low_output, _ = reasoner.reason_task(run_id="run-1", task=low_signal_task, llm_input=low_input)
    high_output, _ = reasoner.reason_task(run_id="run-1", task=high_signal_task, llm_input=high_input)

    assert low_output.confidence < high_output.confidence
    assert low_output.confidence != 0.45
    assert high_output.confidence != 0.45
