from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.models import RawMessage
from pipeline.fixtures import (
    load_all_fixture_messages as _load_all_fixture_messages,
    load_fixture_message as _load_fixture_message,
    load_manifest_message_ids as _load_manifest_message_ids,
    resolve_fixture_root,
)


FIXTURE_ROOT = resolve_fixture_root()


def require_fixture_root() -> Path:
    if not FIXTURE_ROOT.exists():
        pytest.skip(f"Real Gmail fixture directory not found: {FIXTURE_ROOT}")
    return FIXTURE_ROOT


def load_manifest_message_ids() -> list[str]:
    return _load_manifest_message_ids(fixture_root=require_fixture_root())


def load_fixture_message(message_id: str, *, user_id: str = "fixture-user") -> RawMessage:
    return _load_fixture_message(message_id, user_id=user_id, fixture_root=require_fixture_root())


def load_all_fixture_messages(*, user_id: str = "fixture-user") -> list[RawMessage]:
    return _load_all_fixture_messages(user_id=user_id, fixture_root=require_fixture_root())
