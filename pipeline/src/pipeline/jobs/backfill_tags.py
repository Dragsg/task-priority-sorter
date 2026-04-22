from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pipeline.models import CanonicalTask, PrioritizedTaskCard
from pipeline.storage import create_engine_from_url
from pipeline.storage.tables import PipelineTaskRecord, PipelineUserStateRecord
from pipeline.utils.tags import dedupe_tags, synthesize_task_tags
from pipeline.utils.time import utc_now_naive


def _build_tags_for_row(
    row: PipelineTaskRecord,
    *,
    custom_tags: list[str] | None = None,
) -> list[str] | None:
    payload = row.payload or {}
    task_payload = payload.get("canonical_task")
    task_card_payload = payload.get("task_card")
    if not isinstance(task_payload, dict) or not isinstance(task_card_payload, dict):
        return None

    try:
        task = CanonicalTask.model_validate(task_payload)
        card = PrioritizedTaskCard.model_validate(task_card_payload)
    except Exception:
        return None
    return synthesize_task_tags(
        task_type=task.task_type,
        text_parts=[
            card.task_title,
            card.task_description,
            card.source_subject,
            card.source_snippet,
            card.source_sender,
            task.representative_subject,
            task.representative_body_excerpt,
            task.representative_snippet,
            task.representative_sender_display,
            task.topic_entity.entity_name,
        ],
        score_reasons=task.score_reasons,
        manual_tags=task.manual_tags,
        llm_tags=dedupe_tags([*(row.tags or []), *(card.tags or [])]),
        available_tags=custom_tags,
        max_count=3,
    )


def retag_pipeline_tasks(engine: Engine, *, user_id: str | None = None) -> dict[str, int]:
    summary = {"scanned": 0, "updated": 0, "skipped": 0}

    with Session(engine) as session:
        custom_tags_by_user = {
            row.user_id: dedupe_tags(row.custom_tags or [])
            for row in session.scalars(select(PipelineUserStateRecord)).all()
        }

        stmt = select(PipelineTaskRecord)
        if user_id is not None:
            stmt = stmt.where(PipelineTaskRecord.user_id == str(user_id))

        for row in session.scalars(stmt).all():
            summary["scanned"] += 1
            new_tags = _build_tags_for_row(row, custom_tags=custom_tags_by_user.get(row.user_id, []))
            if new_tags is None:
                summary["skipped"] += 1
                continue

            existing_tags = dedupe_tags(row.tags or [])
            payload = dict(row.payload or {})
            task_card_payload = dict(payload.get("task_card") or {})
            payload_tags = dedupe_tags(task_card_payload.get("tags") or [])

            if new_tags == existing_tags and new_tags == payload_tags:
                continue

            task_card_payload["tags"] = new_tags
            payload["task_card"] = task_card_payload
            row.tags = new_tags
            row.payload = payload
            row.updated_at = utc_now_naive()
            summary["updated"] += 1

        session.commit()

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill synthesized tags into pipeline_tasks rows.")
    parser.add_argument("--database-url", required=True, help="SQLAlchemy database URL.")
    parser.add_argument("--user-id", default=None, help="Optional user identifier to retag.")
    args = parser.parse_args()

    engine = create_engine_from_url(args.database_url)
    result = retag_pipeline_tasks(engine, user_id=args.user_id)
    print(
        f"Retag complete: scanned={result['scanned']} updated={result['updated']} skipped={result['skipped']}"
    )


if __name__ == "__main__":
    main()
