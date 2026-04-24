from __future__ import annotations

from pydantic import BaseModel, Field


class PipelineSettings(BaseModel):
    """Runtime configuration for the priority pipeline."""

    profile_confidence_threshold: float = 0.65
    decision_window_size: int = 20
    minimum_personalization_observations: int = 5
    ewma_decay: float = 0.85
    dedup_similarity_threshold: float = 0.82
    llm_model: str = "gpt-5.2"
    llm_max_concurrency: int = 4
    llm_prompt_version: str = "priority-pipeline.v2"
    llm_schema_version: str = "priority-card.v2"
    provider_timezone_fallback: str = "Asia/Singapore"
    sender_hash_pepper: str = Field(
        default="change-me",
        description="Application-level pepper combined with per-user salt.",
    )
