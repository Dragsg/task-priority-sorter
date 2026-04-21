from __future__ import annotations

from pathlib import Path

from pipeline.config import PipelineSettings
from pipeline.models import BehaviorProfile, CanonicalTask, OnboardingContext, TopicEntity
from pipeline.models.enums import EntityType, Platform, PriorityTier, SenderRole, TaskType
from pipeline.services.llm import PriorityReasoner
from pipeline.utils.env import load_dotenv_value


class DummyClient:
    def __init__(self) -> None:
        self.called = False

    @property
    def responses(self):
        return self

    def create(self, **kwargs):
        self.called = True
        raise RuntimeError("stop after client creation")


def test_load_dotenv_value_reads_local_env_file(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-key\nOTHER=value\n", encoding="utf-8")

    assert load_dotenv_value("OPENAI_API_KEY") == "test-key"


def test_reasoner_uses_explicit_environment_before_dotenv(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    reasoner = PriorityReasoner(PipelineSettings(), client=None)
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
    llm_input = reasoner.build_llm_input(
        task=task,
        profile=BehaviorProfile(user_id="user-1", user_salt="salt-1"),
        onboarding=OnboardingContext(user_id="user-1"),
        entity_context=None,
        sender_context=None,
        can_personalize=False,
    )

    captured: dict[str, str] = {}

    def fake_openai(*, api_key: str):
        captured["api_key"] = api_key
        return DummyClient()

    import pipeline.services.llm as llm_module

    monkeypatch.setattr(llm_module, "OpenAI", fake_openai)
    reasoner.reason_task(run_id="run-1", task=task, llm_input=llm_input)

    assert captured["api_key"] == "env-key"
