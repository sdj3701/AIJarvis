from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import RecoveryError
from app.orchestrator.recovery import recover_startup
from scripts.bootstrap import create_tree

pytestmark = pytest.mark.phase0


class RecordingEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self.items.append((event_type, dict(payload)))


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "Jarvis"
    create_tree(root)
    return root


def test_leftover_temporary_file_is_quarantined_and_reported(tmp_path: Path) -> None:
    root = _root(tmp_path)
    temporary = root / "docs" / "notes" / "draft.md.tmp"
    temporary.write_bytes(b"partial")
    events = RecordingEvents()

    report = recover_startup(root, events)

    assert report.tmp_files == 1
    assert report.broken_tails == 0
    assert not temporary.exists()
    quarantined = report.actions[0].quarantined
    assert quarantined is not None and quarantined.read_bytes() == b"partial"
    assert [event_type for event_type, _ in events.items] == [
        "recovery.start",
        "recovery.result",
    ]
    assert events.items[1][1]["action"] == "quarantine_tmp"


def test_broken_final_jsonl_line_is_moved_and_valid_lines_remain(tmp_path: Path) -> None:
    root = _root(tmp_path)
    raw_path = root / "memory" / "raw" / "ses_123.jsonl"
    valid = [{"turn": 1}, {"turn": 2}]
    prefix = b"".join(
        json.dumps(item, separators=(",", ":")).encode("utf-8") + b"\n" for item in valid
    )
    broken = b'{"turn":3'
    raw_path.write_bytes(prefix + broken)
    events = RecordingEvents()

    report = recover_startup(root, events)

    assert report.broken_tails == 1
    assert raw_path.read_bytes() == prefix
    tail = report.actions[0].quarantined
    assert tail is not None and tail.name == "ses_123.tail"
    assert tail.read_bytes() == broken
    assert events.items[-1][1] == {
        "action": "quarantine_broken_tail",
        "session_id": "ses_123",
        "quarantined": str(tail),
        "restored_turns": 2,
    }


def test_invalid_middle_jsonl_line_is_hard_failure_and_not_rewritten(tmp_path: Path) -> None:
    root = _root(tmp_path)
    raw_path = root / "memory" / "raw" / "ses_bad.jsonl"
    original = b'{"turn":1}\nnot-json\n{"turn":3}\n'
    raw_path.write_bytes(original)
    events = RecordingEvents()

    with pytest.raises(RecoveryError, match="중간 레코드"):
        recover_startup(root, events)

    assert raw_path.read_bytes() == original
    assert events.items[-1][1]["action"] == "failed"


def test_clean_startup_emits_explicit_no_action_result(tmp_path: Path) -> None:
    events = RecordingEvents()

    report = recover_startup(_root(tmp_path), events)

    assert report.tmp_files == report.broken_tails == 0
    assert report.actions[0].action == "none"
    assert [event_type for event_type, _ in events.items] == [
        "recovery.start",
        "recovery.result",
    ]
