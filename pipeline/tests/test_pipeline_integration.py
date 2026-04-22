from pipeline.config import PipelineSettings
from pipeline.models import (
    BehaviorProfile,
    EntityAlias,
    EntityWeight,
    FeedbackEvent,
    OnboardingContext,
    Platform,
    RawMessage,
    SenderWeight,
)
from pipeline.models.enums import EntityType, FeedbackAction, FeedbackDirection
from pipeline.services.pipeline import PriorityPipeline
from pipeline.services.profile import ProfileService
from pipeline.storage.repositories import InMemoryPipelineRepository


def test_end_to_end_pipeline_and_feedback_cycle():
    repository = InMemoryPipelineRepository()
    settings = PipelineSettings(profile_confidence_threshold=0.65)
    profile_service = ProfileService(settings)
    pipeline = PriorityPipeline(repository, settings=settings, profile_service=profile_service)

    repository.upsert_raw_messages(
        [
            RawMessage(
                user_id="user-1",
                platform=Platform.GMAIL,
                source_id="msg-1",
                subject="CS2103T project due tonight",
                body_text="Submit the CS2103T project by tonight 11:59pm.",
                sender_id="prof.chen",
                sender_display="Prof Chen",
                sender_email="chen@school.edu",
                sender_domain="school.edu",
            ),
            RawMessage(
                user_id="user-1",
                platform=Platform.TEAMS,
                source_id="msg-2",
                body_text="Reminder: CS2103T project due tonight",
                sender_id="prof.chen",
                sender_display="Prof Chen",
            ),
        ]
    )
    repository.upsert_entity_aliases(
        "user-1",
        [
            EntityAlias(
                alias_key="cs2103t",
                canonical_entity_key="cs2103t",
                canonical_entity_name="CS2103T",
                entity_type=EntityType.MODULE,
            )
        ],
    )
    sender_hash = profile_service.hash_identity(user_salt="salt-1", identifier="prof.chen")
    repository.save_behavior_profile(
        BehaviorProfile(
            user_id="user-1",
            user_salt="salt-1",
            confidence=0.9,
            profile_version=3,
            entity_weights={
                "cs2103t": EntityWeight(
                    entity_name="CS2103T",
                    entity_key="cs2103t",
                    entity_type=EntityType.MODULE,
                    priority_multiplier=1.5,
                    observation_count=6,
                    avg_start_lead_hours=9.0,
                )
            },
            sender_weights={
                sender_hash: SenderWeight(
                    sender_hash=sender_hash,
                    label="Lecturer",
                    response_rate=0.95,
                    observation_count=6,
                    weight=1.5,
                )
            },
        )
    )
    repository.save_onboarding_context(OnboardingContext(user_id="user-1", timetable_summary="Evenings are best"))

    bundle = pipeline.run_for_user("user-1")

    assert len(bundle.canonical_tasks) == 1
    assert len(bundle.task_cards) == 1
    assert bundle.task_cards[0].entity_name == "CS2103T"
    assert bundle.task_cards[0].task_title == "CS2103T project due tonight"
    assert bundle.task_cards[0].task_description is not None
    assert bundle.task_cards[0].source_subject == "CS2103T project due tonight"
    assert bundle.task_cards[0].source_snippet is not None
    assert repository.current_cards[bundle.task_cards[0].canonical_task_id].task_id == bundle.task_cards[0].task_id

    updated_profile = pipeline.apply_feedback(
        FeedbackEvent(
            user_id="user-1",
            canonical_task_id=bundle.task_cards[0].canonical_task_id,
            action=FeedbackAction.WRONG_PRIORITY,
            direction=FeedbackDirection.TOO_LOW,
            entity_key="cs2103t",
            entity_name="CS2103T",
            entity_type=EntityType.MODULE,
            sender_hash=sender_hash,
            incremental_priority_delta=1,
        )
    )

    assert updated_profile.profile_version > 3
    assert updated_profile.entity_weights["cs2103t"].priority_multiplier >= 1.5


def test_dismissed_task_card_stays_hidden_from_current_queue():
    repository = InMemoryPipelineRepository()
    settings = PipelineSettings(profile_confidence_threshold=0.65)
    pipeline = PriorityPipeline(repository, settings=settings)

    repository.upsert_raw_messages(
        [
            RawMessage(
                user_id="user-2",
                platform=Platform.GMAIL,
                source_id="msg-3",
                subject="Collect welfare pack tomorrow",
                snippet="Please collect your welfare pack tomorrow at 3pm.",
                body_text="Please collect your welfare pack tomorrow at 3pm from deck 9.",
                sender_display="Computing Club",
                sender_email="welfare@club.org",
                sender_domain="club.org",
            )
        ]
    )

    first_bundle = pipeline.run_for_user("user-2")
    canonical_task_id = first_bundle.task_cards[0].canonical_task_id

    assert repository.dismiss_task_card("user-2", canonical_task_id) is True
    assert repository.get_current_task_cards("user-2") == []

    pipeline.run_for_user("user-2")

    assert repository.get_current_task_cards("user-2") == []
