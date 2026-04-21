from __future__ import annotations

from uuid import uuid4

from pipeline.config import PipelineSettings
from pipeline.models import CanonicalTask, PrioritizedTaskCard, StructuredLlmOutput


class PostProcessor:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings

    def build_task_card(
        self,
        *,
        run_id: str,
        task: CanonicalTask,
        llm_output: StructuredLlmOutput,
        profile_version: int,
    ) -> PrioritizedTaskCard:
        return PrioritizedTaskCard(
            task_id=uuid4().hex,
            canonical_task_id=task.canonical_task_id,
            user_id=task.user_id,
            run_id=run_id,
            priority_tier=llm_output.priority_tier,
            action_window=llm_output.action_window,
            rationale=llm_output.rationale,
            confidence=llm_output.confidence,
            needs_user_review=llm_output.confidence < self.settings.profile_confidence_threshold,
            deadline_hours=task.deadline_hours,
            platforms_seen=task.platforms_seen,
            profile_adjustment_made=llm_output.profile_adjustment_made,
            adjustment_reason=llm_output.adjustment_reason,
            evidence_source_ids=task.source_ids,
            entity_name=task.topic_entity.entity_name,
            entity_type=task.topic_entity.entity_type,
            score_reasons=task.score_reasons,
            profile_version=profile_version,
            prompt_version=self.settings.llm_prompt_version,
            schema_version_ref=self.settings.llm_schema_version,
        )
