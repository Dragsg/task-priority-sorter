from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.models import RawMessage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_FIXTURE_ROOT = PROJECT_ROOT / "test-data"
LEGACY_FIXTURE_ROOT = Path(r"C:\Users\ngyin\Documents\straightup hackathon\data\fixtures\redacted\gmail")
FIXTURE_ROOT = LOCAL_FIXTURE_ROOT if LOCAL_FIXTURE_ROOT.exists() else LEGACY_FIXTURE_ROOT


def require_fixture_root() -> Path:
    if not FIXTURE_ROOT.exists():
        pytest.skip(f"Real Gmail fixture directory not found: {FIXTURE_ROOT}")
    return FIXTURE_ROOT


def load_manifest_message_ids() -> list[str]:
    root = require_fixture_root()
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest["message_ids"]
    return sorted(path.stem for path in root.glob("*.json"))


def load_fixture_message(message_id: str, *, user_id: str = "fixture-user") -> RawMessage:
    root = require_fixture_root()
    payload = json.loads((root / f"{message_id}.json").read_text(encoding="utf-8"))
    payload.setdefault("user_id", user_id)
    return RawMessage.model_validate(payload)


def load_all_fixture_messages(*, user_id: str = "fixture-user") -> list[RawMessage]:
    return [load_fixture_message(message_id, user_id=user_id) for message_id in load_manifest_message_ids()]
