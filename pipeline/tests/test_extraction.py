from pipeline.models import Platform, RawMessage
from pipeline.models.enums import EntityType, TaskType
from pipeline.services.extraction import SignalExtractor


def test_extracts_module_entity_from_academic_message():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.GMAIL,
        source_id="msg-1",
        subject="CS2103T project due tonight",
        body_text="Please submit your CS2103T individual project by tonight 11:59pm.",
        sender_display="Prof Chen",
        sender_email="chen@school.edu",
        sender_domain="school.edu",
    )

    signal = extractor.extract(message)

    assert signal.topic_entity.entity_name == "CS2103T"
    assert signal.topic_entity.entity_type == EntityType.MODULE
    assert signal.task_type == TaskType.SUBMISSION


def test_extracts_non_academic_entity_from_welfare_message():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.TEAMS,
        source_id="msg-2",
        body_text="Anyone going to the welfare pack collection tmr at deck 9?",
        sender_display="Computing Club Welfare",
    )

    signal = extractor.extract(message)

    assert signal.topic_entity.entity_type in {EntityType.CCA, EntityType.TOPIC}
    assert "welfare" in signal.topic_entity.entity_name.lower() or "pack" in signal.topic_entity.entity_name.lower()
