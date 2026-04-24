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


def test_informational_storage_alert_is_not_marked_as_actionable_task():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.GMAIL,
        source_id="msg-3",
        subject="Usage reached your limit",
        snippet="Your storage is almost full. Review your plan options.",
        body_text="Your storage usage reached the limit for this account.",
        sender_display="Drive Team",
        sender_email="no-reply@drive.example.com",
        sender_domain="drive.example.com",
    )

    signal = extractor.extract(message)

    assert signal.has_task is False


def test_manual_task_metadata_overrides_extraction_with_structured_fields():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.MANUAL,
        source_id="manual-1",
        subject="Submit reflection",
        snippet="Write and submit the reflection note.",
        body_text="Write and submit the reflection note.",
        provider_metadata={
            "extra": {
                "manual_task": {
                    "task_type": "submission",
                    "entity_name": "CS2103T",
                    "entity_type": "module",
                    "deadline_iso": "2026-04-22T23:59:00",
                }
            }
        },
    )

    signal = extractor.extract(message)

    assert signal.has_task is True
    assert signal.task_type == TaskType.SUBMISSION
    assert signal.topic_entity.entity_name == "CS2103T"
    assert signal.topic_entity.entity_type == EntityType.MODULE
    assert signal.deadline_at is not None


def test_body_excerpt_prefers_complete_actionable_lines_over_raw_snippet_cutoff():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.GMAIL,
        source_id="msg-4",
        subject='New assignment: "What is my understanding of collaboration?"',
        snippet="Hi NG YING XUAN, Dennis Lam posted a new assignment in 2019 S1-04 ChangeMakers. Due: Jan 20 Level 1: What is my underst",
        body_text=(
            "Hi NG YING XUAN,\n"
            "Dennis Lam posted a new assignment in 2019 S1-04 ChangeMakers: Innovation and Entrepreneurship.\n"
            "Due: Jan 20\n"
            "Homework for Week 2. Please complete INDIVIDUALLY and submit your answers by next Monday morning 8.30am.\n"
            "OPEN\n"
            "https://classroom.google.com/example\n"
            "If you don't want to receive emails from Classroom, you can unsubscribe.\n"
        ),
        sender_display="Dennis Lam",
        sender_email="dennis@classroom.google.com",
        sender_domain="classroom.google.com",
    )

    signal = extractor.extract(message)

    assert signal.body_excerpt is not None
    assert "submit your answers by next Monday morning 8.30am" in signal.body_excerpt
    assert "unsubscribe" not in signal.body_excerpt.lower()
    assert "http" not in signal.body_excerpt.lower()


def test_promotions_label_newsletter_is_filtered_even_with_urgency_words():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.GMAIL,
        source_id="msg-5",
        subject="Morning Brew: High hopes",
        snippet="Due tomorrow: markets, policy, and startup headlines.",
        body_text=(
            "View online.\n"
            "Trump may soon ease restrictions tomorrow.\n"
            "Read this by tonight and stay ahead.\n"
            "Unsubscribe anytime.\n"
        ),
        sender_display="Morning Brew",
        sender_email="crew@morningbrew.com",
        sender_domain="morningbrew.com",
        label_ids=["INBOX", "CATEGORY_PROMOTIONS"],
        provider_metadata={
            "extra": {
                "list_unsubscribe": "<mailto:unsubscribe@morningbrew.com>",
                "precedence": "bulk",
            }
        },
    )

    signal = extractor.extract(message)

    assert signal.has_task is False


def test_bulk_updates_email_from_institution_with_deadline_still_survives():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.GMAIL,
        source_id="msg-6",
        subject="CS2103T assignment due Friday",
        snippet="Submit your assignment by Friday 11:59pm on Classroom.",
        body_text=(
            "Hello,\n"
            "Please submit your CS2103T assignment by Friday 11:59pm on Classroom.\n"
            "If you don't want to receive emails from Classroom, you can unsubscribe.\n"
        ),
        sender_display="Google Classroom",
        sender_email="notifications@classroom.google.com",
        sender_domain="classroom.google.com",
        label_ids=["INBOX", "CATEGORY_UPDATES"],
        provider_metadata={
            "extra": {
                "list_unsubscribe": "<https://classroom.google.com/unsubscribe>",
                "precedence": "list",
            }
        },
    )

    signal = extractor.extract(message)

    assert signal.has_task is True
    assert signal.task_type == TaskType.SUBMISSION
    assert signal.deadline_at is not None


def test_newsletter_sender_email_is_filtered():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.GMAIL,
        source_id="msg-7",
        subject="Weekly digest: submit this form by Friday",
        snippet="Due Friday: complete the form before 5pm.",
        body_text="Please complete the form and submit it by Friday 5pm. Unsubscribe anytime.",
        sender_display="Campus Weekly",
        sender_email="newsletter@campus.example.com",
        sender_domain="campus.example.com",
        label_ids=["INBOX", "CATEGORY_UPDATES"],
        provider_metadata={
            "extra": {
                "list_unsubscribe": "<mailto:unsubscribe@campus.example.com>",
                "precedence": "bulk",
            }
        },
    )

    signal = extractor.extract(message)

    assert signal.has_task is False


def test_important_or_starred_labels_override_hard_gmail_filters():
    extractor = SignalExtractor()
    message = RawMessage(
        user_id="user-1",
        platform=Platform.GMAIL,
        source_id="msg-8",
        subject="Project consultation tomorrow",
        snippet="Please attend the project consultation tomorrow at 2pm.",
        body_text="Please attend the CS2103T project consultation tomorrow at 2pm in COM1.",
        sender_display="Prof Chen",
        sender_email="chen@school.edu",
        sender_domain="school.edu",
        label_ids=["INBOX", "CATEGORY_SOCIAL", "IMPORTANT", "STARRED"],
    )

    signal = extractor.extract(message)

    assert signal.has_task is True
    assert signal.deadline_at is not None
