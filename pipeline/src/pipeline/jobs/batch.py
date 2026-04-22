from __future__ import annotations

import argparse

from pipeline import PipelineSettings
from pipeline.services.pipeline import PriorityPipeline
from pipeline.storage import SqlAlchemyPipelineRepository, create_engine_from_url, create_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the priority pipeline for a single user.")
    parser.add_argument("--database-url", required=True, help="SQLAlchemy database URL.")
    parser.add_argument("--user-id", required=True, help="User identifier to process.")
    parser.add_argument("--limit", type=int, default=None, help="Optional raw message limit.")
    parser.add_argument("--create-schema", action="store_true", help="Create database tables before running.")
    args = parser.parse_args()

    engine = create_engine_from_url(args.database_url)
    if args.create_schema:
        create_schema(engine)

    repository = SqlAlchemyPipelineRepository(engine)
    pipeline = PriorityPipeline(repository, settings=PipelineSettings())
    bundle = pipeline.run_for_user(args.user_id, limit=args.limit)
    print(f"Run {bundle.run_id} completed with {len(bundle.task_cards)} task cards.")
