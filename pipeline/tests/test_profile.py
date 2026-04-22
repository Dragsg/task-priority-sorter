from datetime import datetime

from pipeline.config import PipelineSettings
from pipeline.models import BehaviorProfile, FeedbackEvent
from pipeline.models.enums import EntityType, FeedbackAction, FeedbackDirection, TaskType
from pipeline.services.profile import ProfileService


def build_profile() -> BehaviorProfile:
    return BehaviorProfile(user_id="user-1", user_salt="salt-1")


def test_confidence_uses_rolling_recent_window():
    service = ProfileService(PipelineSettings(decision_window_size=5))
    profile = build_profile()

    for action in [
        FeedbackAction.ACCEPT,
        FeedbackAction.ACCEPT,
        FeedbackAction.WRONG_PRIORITY,
        FeedbackAction.REJECT,
        FeedbackAction.ACCEPT,
    ]:
        profile = service.update_from_feedback(
            profile,
            FeedbackEvent(user_id="user-1", canonical_task_id="task-1", action=action),
        )

    assert 0.15 <= profile.confidence < 0.8
    assert len(profile.decision_window) == 5


def test_wrong_priority_too_low_increases_entity_and_sender_importance():
    settings = PipelineSettings()
    service = ProfileService(settings)
    profile = build_profile()
    sender_hash = service.hash_identity(user_salt=profile.user_salt, identifier="prof@example.edu")

    event = FeedbackEvent(
        user_id="user-1",
        canonical_task_id="task-1",
        action=FeedbackAction.WRONG_PRIORITY,
        direction=FeedbackDirection.TOO_LOW,
        entity_key="cs2103t",
        entity_name="CS2103T",
        entity_type=EntityType.MODULE,
        sender_hash=sender_hash,
        task_type=TaskType.SUBMISSION,
        incremental_priority_delta=1,
    )

    updated = service.update_from_feedback(profile, event)

    assert updated.entity_weights["cs2103t"].priority_multiplier > 1.0
    assert updated.sender_weights[sender_hash].weight > 1.0


def test_personalization_requires_minimum_observations():
    settings = PipelineSettings(minimum_personalization_observations=5)
    service = ProfileService(settings)
    profile = BehaviorProfile(user_id="user-1", user_salt="salt-1", confidence=0.9)

    assert not service.can_personalize(profile, entity_observation_count=4, sender_observation_count=0)
    assert service.can_personalize(profile, entity_observation_count=5, sender_observation_count=0)


def test_manual_task_updates_task_type_and_entity_context_without_touching_confidence():
    service = ProfileService(PipelineSettings())
    profile = build_profile()

    updated = service.update_from_manual_task(
        profile,
        task_type=TaskType.SUBMISSION,
        entity_key="cs2103t",
        entity_name="CS2103T",
        entity_type=EntityType.MODULE,
        deadline_hours=6.0,
        occurred_at=datetime(2026, 4, 22, 21, 0, 0),
    )

    assert updated.task_type_start_leads[TaskType.SUBMISSION] == 6.0
    assert updated.entity_weights["cs2103t"].observation_count == 1
    assert updated.entity_weights["cs2103t"].priority_multiplier >= 1.2
    assert updated.confidence == 0.0
