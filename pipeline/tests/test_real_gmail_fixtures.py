from __future__ import annotations

from pipeline.config import PipelineSettings
from pipeline.models.enums import EntityType, TaskType
from pipeline.services.extraction import SignalExtractor
from pipeline.services.pipeline import PriorityPipeline
from pipeline.storage.repositories import InMemoryPipelineRepository
from tests.real_fixture_helpers import load_all_fixture_messages, load_fixture_message


def test_real_fixture_corpus_validates_and_extracts():
    extractor = SignalExtractor()
    messages = load_all_fixture_messages()

    assert len(messages) == 50

    for message in messages:
        signal = extractor.extract(message)
        assert signal.source_id == message.source_id
        assert signal.topic_entity.entity_name
        assert signal.topic_entity.entity_key
        assert signal.platform == message.platform


def test_real_assignment_fixture_extracts_submission_and_reasonable_deadline():
    extractor = SignalExtractor()
    message = load_fixture_message("1684f501bc21a694")

    signal = extractor.extract(message)

    assert signal.task_type == TaskType.SUBMISSION
    assert signal.has_task is True
    assert signal.deadline_hours is not None
    assert 100 <= signal.deadline_hours <= 130


def test_real_tryout_fixture_extracts_meeting_like_signal():
    extractor = SignalExtractor()
    message = load_fixture_message("16856bd073f647a8")

    signal = extractor.extract(message)

    assert signal.task_type == TaskType.MEETING
    assert signal.has_task is True
    assert signal.deadline_hours is not None
    assert 10 <= signal.deadline_hours <= 30


def test_real_reply_fixture_avoids_quoted_deadline_false_positive():
    extractor = SignalExtractor()
    message = load_fixture_message("1685ec1446fa98d4")

    signal = extractor.extract(message)

    assert signal.task_type == TaskType.SOCIAL
    assert signal.deadline_hours is None


def test_pipeline_runs_over_real_gmail_fixture_corpus():
    repository = InMemoryPipelineRepository()
    messages = load_all_fixture_messages(user_id="fixture-user")
    repository.upsert_raw_messages(messages)

    pipeline = PriorityPipeline(repository, settings=PipelineSettings())
    bundle = pipeline.run_for_user("fixture-user")

    assert 0 < len(bundle.signals) <= len(messages)
    assert len(bundle.task_cards) > 0
    assert all(card.entity_name for card in bundle.task_cards)
    assert all(card.task_title for card in bundle.task_cards)
    assert all(card.canonical_task_id for card in bundle.task_cards)
