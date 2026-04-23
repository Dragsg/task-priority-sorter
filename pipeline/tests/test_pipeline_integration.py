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


def test_accepted_task_stays_hidden_when_rerun_changes_canonical_id():
    repository = InMemoryPipelineRepository()
    settings = PipelineSettings(profile_confidence_threshold=0.65)
    pipeline = PriorityPipeline(repository, settings=settings)

    repository.upsert_raw_messages(
        [
            RawMessage(
                user_id="user-accepted",
                platform=Platform.GMAIL,
                source_id="msg-accepted-1",
                subject="CS2103T project due tonight",
                snippet="Submit the CS2103T project by tonight 11:59pm.",
                body_text="Submit the CS2103T project by tonight 11:59pm.",
                sender_display="Prof Chen",
                sender_email="chen@school.edu",
                sender_domain="school.edu",
            )
        ]
    )

    first_bundle = pipeline.run_for_user("user-accepted")
    first_card = first_bundle.task_cards[0]
    repository.apply_task_action(
        "user-accepted",
        first_card.canonical_task_id,
        action=FeedbackAction.ACCEPT,
    )

    repository.upsert_raw_messages(
        [
            RawMessage(
                user_id="user-accepted",
                platform=Platform.GMAIL,
                source_id="msg-accepted-1",
                subject="Action required: CS2103T project due tonight",
                snippet="Submit the CS2103T project by tonight 11:59pm on Canvas.",
                body_text="Submit the CS2103T project by tonight 11:59pm on Canvas.",
                sender_display="Prof Chen",
                sender_email="chen@school.edu",
                sender_domain="school.edu",
            )
        ]
    )

    second_bundle = pipeline.run_for_user("user-accepted")

    assert first_card.canonical_task_id != second_bundle.task_cards[0].canonical_task_id
    assert repository.get_current_task_cards("user-accepted") == []
    accepted_cards = repository.get_accepted_task_cards("user-accepted")
    assert len(accepted_cards) == 1
    assert accepted_cards[0].source_subject == "Action required: CS2103T project due tonight"


def test_removed_task_tag_stays_removed_after_rerun():
    repository = InMemoryPipelineRepository()
    settings = PipelineSettings(profile_confidence_threshold=0.65)
    pipeline = PriorityPipeline(repository, settings=settings)

    repository.upsert_raw_messages(
        [
            RawMessage(
                user_id="user-3",
                platform=Platform.GMAIL,
                source_id="msg-4",
                subject="CS2103T project due tonight",
                snippet="Submit the CS2103T project by tonight 11:59pm.",
                body_text="Submit the CS2103T project by tonight 11:59pm.",
                sender_display="Prof Chen",
                sender_email="chen@school.edu",
                sender_domain="school.edu",
            )
        ]
    )

    first_bundle = pipeline.run_for_user("user-3")
    card = first_bundle.task_cards[0]

    assert card.tags
    removed_tag = card.tags[0]
    remaining_tags = [tag for tag in card.tags if tag != removed_tag]

    repository.replace_task_tags("user-3", card.canonical_task_id, tags=remaining_tags)

    pipeline.run_for_user("user-3")
    current_card = repository.get_current_task_card("user-3", card.canonical_task_id)

    assert current_card is not None
    assert removed_tag not in current_card.tags


def test_added_task_tag_stays_after_rerun():
    repository = InMemoryPipelineRepository()
    settings = PipelineSettings(profile_confidence_threshold=0.65)
    pipeline = PriorityPipeline(repository, settings=settings)

    repository.upsert_raw_messages(
        [
            RawMessage(
                user_id="user-4",
                platform=Platform.GMAIL,
                source_id="msg-5",
                subject="Career fair announcement",
                snippet="Join the campus career fair next week.",
                body_text="Join the campus career fair next week and register if interested.",
                sender_display="Careers Office",
                sender_email="careers@school.edu",
                sender_domain="school.edu",
            )
        ]
    )

    first_bundle = pipeline.run_for_user("user-4")
    card = first_bundle.task_cards[0]

    repository.replace_task_tags("user-4", card.canonical_task_id, tags=[*card.tags, "custom_focus"])
    pipeline.run_for_user("user-4")
    current_card = repository.get_current_task_card("user-4", card.canonical_task_id)

    assert current_card is not None
    assert "custom_focus" in current_card.tags


def test_direct_task_edits_survive_rerun():
    repository = InMemoryPipelineRepository()
    settings = PipelineSettings(profile_confidence_threshold=0.65)
    pipeline = PriorityPipeline(repository, settings=settings)

    repository.upsert_raw_messages(
        [
            RawMessage(
                user_id="user-5",
                platform=Platform.GMAIL,
                source_id="msg-6",
                subject="Prepare lab report by Friday",
                snippet="Please submit the lab report by Friday evening.",
                body_text="Please submit the lab report by Friday evening through the portal.",
                sender_display="Teaching Team",
                sender_email="teaching@school.edu",
                sender_domain="school.edu",
            )
        ]
    )

    first_bundle = pipeline.run_for_user("user-5")
    card = first_bundle.task_cards[0]

    repository.update_task(
        "user-5",
        card.canonical_task_id,
        updates={
            "title": "Finish lab report draft",
            "description": "Use the new grading rubric before submitting.",
            "deadline_at": "2026-04-25T18:30:00+00:00",
            "priority_tier": "CRITICAL",
            "status": "COMPLETED",
            "tags": ["lab", "writing"],
        },
    )

    pipeline.run_for_user("user-5")
    completed_cards = repository.get_completed_task_cards("user-5")

    assert len(completed_cards) == 1
    current_card = completed_cards[0]
    assert current_card.task_title == "Finish lab report draft"
    assert current_card.task_description == "Use the new grading rubric before submitting."
    assert current_card.deadline_at_iso == "2026-04-25T18:30:00+00:00"
    assert current_card.priority_tier.value == "CRITICAL"
    assert current_card.status.value == "completed"
    assert current_card.tags == ["lab", "writing"]
