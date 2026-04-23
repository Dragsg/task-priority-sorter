from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.config import PipelineSettings
from pipeline.fixtures import load_all_fixture_messages, load_fixture_message, resolve_fixture_root
from pipeline.services.pipeline import PriorityPipeline
from pipeline.storage.repositories import InMemoryPipelineRepository


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the priority pipeline against local Gmail fixture JSON files.")
    parser.add_argument(
        "--fixture-root",
        default=str(resolve_fixture_root()),
        help="Directory containing raw Gmail fixture JSON files.",
    )
    parser.add_argument(
        "--message-id",
        action="append",
        default=[],
        help="Optional message id to load. Repeat the flag to load multiple specific fixtures.",
    )
    parser.add_argument("--user-id", default="fixture-user", help="User identifier to assign to the fixture messages.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of fixtures to load.")
    parser.add_argument(
        "--show-filtered",
        action="store_true",
        help="Print the messages that were filtered out as non-actionable.",
    )
    return parser


def _load_messages(*, fixture_root: Path, user_id: str, message_ids: list[str], limit: int | None):
    if message_ids:
        messages = [
            load_fixture_message(message_id, user_id=user_id, fixture_root=fixture_root)
            for message_id in message_ids
        ]
    else:
        messages = load_all_fixture_messages(user_id=user_id, fixture_root=fixture_root)

    return messages[:limit] if limit is not None else messages


def _print_line(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_text)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    fixture_root = resolve_fixture_root(args.fixture_root)
    if not fixture_root.exists():
        parser.error(f"Fixture directory does not exist: {fixture_root}")

    messages = _load_messages(
        fixture_root=fixture_root,
        user_id=args.user_id,
        message_ids=args.message_id,
        limit=args.limit,
    )
    if not messages:
        parser.error(f"No fixture messages found in {fixture_root}")

    repository = InMemoryPipelineRepository()
    repository.upsert_raw_messages(messages)

    pipeline = PriorityPipeline(repository, settings=PipelineSettings())
    extracted = [pipeline.extractor.extract(message) for message in messages]
    actionable = [signal for signal in extracted if signal.has_task]
    filtered = [(message, signal) for message, signal in zip(messages, extracted, strict=False) if not signal.has_task]
    bundle = pipeline.run_for_user(args.user_id)

    _print_line(f"Fixture root: {fixture_root}")
    _print_line(f"Loaded messages: {len(messages)}")
    _print_line(f"Actionable signals: {len(actionable)}")
    _print_line(f"Filtered messages: {len(filtered)}")
    _print_line(f"Canonical tasks: {len(bundle.canonical_tasks)}")
    _print_line(f"Task cards: {len(bundle.task_cards)}")

    if bundle.task_cards:
        _print_line("\nTask cards:")
        for index, card in enumerate(bundle.task_cards, start=1):
            title = card.task_title or card.entity_name or card.source_subject or card.canonical_task_id
            _print_line(
                f"{index}. [{card.priority_tier.value}] {title} "
                f"(entity={card.entity_name or 'n/a'}, sources={len(card.evidence_source_ids)})"
            )

    if args.show_filtered and filtered:
        _print_line("\nFiltered messages:")
        for message, signal in filtered:
            labels = ",".join(message.label_ids) if message.label_ids else "-"
            _print_line(
                f"- {message.source_id}: {message.subject or '(no subject)'} "
                f"[labels={labels}] sender_role={signal.sender_role.value}"
            )


if __name__ == "__main__":
    main()
