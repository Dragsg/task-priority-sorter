from __future__ import annotations

import json
from pathlib import Path

from pipeline.models import RawMessage


PIPELINE_PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PIPELINE_PROJECT_ROOT.parent
LEGACY_FIXTURE_ROOT = Path(r"C:\Users\ngyin\Documents\straightup hackathon\data\fixtures\redacted\gmail")
DEFAULT_FIXTURE_ROOT_CANDIDATES = [
    PIPELINE_PROJECT_ROOT / "test_data",
    PIPELINE_PROJECT_ROOT / "test-data",
    REPO_ROOT / "test_data",
    REPO_ROOT / "test-data",
    LEGACY_FIXTURE_ROOT,
]


def resolve_fixture_root(fixture_root: str | Path | None = None) -> Path:
    if fixture_root is not None:
        return Path(fixture_root)

    for candidate in DEFAULT_FIXTURE_ROOT_CANDIDATES:
        if candidate.exists():
            return candidate

    return DEFAULT_FIXTURE_ROOT_CANDIDATES[0]


def load_manifest_message_ids(*, fixture_root: str | Path | None = None) -> list[str]:
    root = resolve_fixture_root(fixture_root)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest["message_ids"]
    return sorted(path.stem for path in root.glob("*.json"))


def load_fixture_message(
    message_id: str,
    *,
    user_id: str = "fixture-user",
    fixture_root: str | Path | None = None,
) -> RawMessage:
    root = resolve_fixture_root(fixture_root)
    payload = json.loads((root / f"{message_id}.json").read_text(encoding="utf-8"))
    payload.setdefault("user_id", user_id)
    return RawMessage.model_validate(payload)


def load_all_fixture_messages(
    *,
    user_id: str = "fixture-user",
    fixture_root: str | Path | None = None,
) -> list[RawMessage]:
    return [
        load_fixture_message(message_id, user_id=user_id, fixture_root=fixture_root)
        for message_id in load_manifest_message_ids(fixture_root=fixture_root)
    ]
