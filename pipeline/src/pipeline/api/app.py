from __future__ import annotations

import argparse
import os

from fastapi import FastAPI, HTTPException

from pipeline.config import PipelineSettings
from pipeline.models import OnboardingContext
from pipeline.services.pipeline import PriorityPipeline
from pipeline.storage import SqlAlchemyPipelineRepository, create_engine_from_url, create_schema
from pipeline.storage.repositories import PipelineRepository
from pipeline.utils.env import load_dotenv_value

from .service import (
    FeedbackRequest,
    FeedbackResponse,
    PipelineApiService,
    PipelineRunResponse,
    TaskCardsResponse,
    UpsertAliasesRequest,
    UpsertMessagesRequest,
)


def create_app(
    *,
    repository: PipelineRepository | None = None,
    settings: PipelineSettings | None = None,
    database_url: str | None = None,
    create_db_schema: bool = False,
) -> FastAPI:
    runtime_settings = settings or PipelineSettings()
    repo = repository or _build_sql_repository(database_url=database_url, create_db_schema=create_db_schema)
    pipeline = PriorityPipeline(repo, settings=runtime_settings)
    service = PipelineApiService(repo, settings=runtime_settings, pipeline=pipeline)

    app = FastAPI(title="Priority Pipeline API", version="0.1.0")
    app.state.pipeline_service = service

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/users/{user_id}/raw-messages")
    def upsert_raw_messages(user_id: str, request: UpsertMessagesRequest) -> dict[str, int]:
        count = service.ingest_raw_messages(user_id, request.messages)
        return {"message_count": count}

    @app.put("/users/{user_id}/onboarding-context", response_model=OnboardingContext)
    def save_onboarding_context(user_id: str, context: OnboardingContext) -> OnboardingContext:
        return service.save_onboarding_context(user_id, context)

    @app.get("/users/{user_id}/onboarding-context", response_model=OnboardingContext)
    def get_onboarding_context(user_id: str) -> OnboardingContext:
        return service.get_onboarding_context(user_id)

    @app.put("/users/{user_id}/entity-aliases")
    def upsert_entity_aliases(user_id: str, request: UpsertAliasesRequest) -> dict[str, int]:
        count = service.save_entity_aliases(user_id, request.aliases)
        return {"alias_count": count}

    @app.post("/users/{user_id}/pipeline/run", response_model=PipelineRunResponse)
    def run_pipeline(user_id: str, limit: int | None = None) -> PipelineRunResponse:
        bundle = service.run_pipeline(user_id, limit=limit)
        raw_message_count = len(repo.get_raw_messages(user_id, limit=limit))
        return PipelineRunResponse(
            run_id=bundle.run_id,
            raw_message_count=raw_message_count,
            signal_count=len(bundle.signals),
            canonical_task_count=len(bundle.canonical_tasks),
            task_card_count=len(bundle.task_cards),
        )

    @app.get("/users/{user_id}/task-cards", response_model=TaskCardsResponse)
    def list_task_cards(user_id: str) -> TaskCardsResponse:
        return TaskCardsResponse(items=service.list_task_cards(user_id))

    @app.get("/users/{user_id}/profile")
    def get_profile(user_id: str):
        return service.get_profile(user_id)

    @app.post("/users/{user_id}/task-cards/{canonical_task_id}/feedback", response_model=FeedbackResponse)
    def submit_feedback(user_id: str, canonical_task_id: str, request: FeedbackRequest) -> FeedbackResponse:
        try:
            event, profile, items = service.submit_feedback(
                user_id,
                canonical_task_id,
                action=request.action,
                direction=request.direction,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return FeedbackResponse(feedback_event=event, profile=profile, items=items)

    return app


def _build_sql_repository(*, database_url: str | None, create_db_schema: bool) -> SqlAlchemyPipelineRepository:
    resolved_url = (
        database_url
        or os.getenv("PIPELINE_DATABASE_URL")
        or load_dotenv_value("PIPELINE_DATABASE_URL")
    )
    if not resolved_url:
        raise RuntimeError("PIPELINE_DATABASE_URL is required when no repository is provided.")

    engine = create_engine_from_url(resolved_url)
    if create_db_schema:
        create_schema(engine)
    return SqlAlchemyPipelineRepository(engine)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the priority pipeline API.")
    parser.add_argument("--database-url", default=None, help="SQLAlchemy database URL. Defaults to PIPELINE_DATABASE_URL.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8000, help="Bind port.")
    parser.add_argument("--create-schema", action="store_true", help="Create database tables before serving.")
    args = parser.parse_args()

    import uvicorn

    app = create_app(database_url=args.database_url, create_db_schema=args.create_schema)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
