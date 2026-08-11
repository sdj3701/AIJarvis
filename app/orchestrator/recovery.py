"""Quarantine incomplete writes and malformed final JSONL records on startup."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.atomic import write_atomic
from app.core.errors import RecoveryError


class EventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    action: str
    source: Path | None
    quarantined: Path | None
    restored_turns: int


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    tmp_files: int
    broken_tails: int
    actions: tuple[RecoveryAction, ...]


def _unique_target(directory: Path, name: str) -> Path:
    candidate = directory / name
    sequence = 1
    while candidate.exists():
        candidate = directory / f"{name}.{sequence}"
        sequence += 1
    return candidate


def _quarantine_tmp(data_root: Path, source: Path, quarantine: Path) -> Path:
    relative = source.relative_to(data_root)
    target = _unique_target(quarantine, "__".join(relative.parts))
    os.replace(source, target)
    return target


def _parse_json_line(line: bytes) -> dict[str, Any]:
    decoded = line.decode("utf-8")
    parsed = json.loads(decoded)
    if not isinstance(parsed, dict):
        raise ValueError("JSONL record must be an object")
    return parsed


def recover_jsonl_tail(path: Path, quarantine: Path) -> RecoveryAction | None:
    """Move only a malformed final JSONL line aside and keep all valid lines."""
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    if not lines:
        return None

    for index, line in enumerate(lines):
        try:
            _parse_json_line(line)
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            if index != len(lines) - 1:
                raise RecoveryError(
                    "JSONL 중간 레코드가 손상되었습니다.",
                    {"file": path.name, "line": index + 1},
                ) from error
            tail_target = _unique_target(quarantine, f"{path.stem}.tail")
            write_atomic(tail_target, line)
            write_atomic(path, b"".join(lines[:index]))
            return RecoveryAction("quarantine_broken_tail", path, tail_target, restored_turns=index)
    return None


def recover_startup(data_root: Path, events: EventSink) -> RecoveryReport:
    """Perform Phase 0 filesystem recovery and emit a record for every outcome."""
    root = Path(data_root).resolve(strict=False)
    quarantine = root / "state" / "quarantine"
    raw_dir = root / "memory" / "raw"
    quarantine.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        temporary_files = sorted(
            path
            for path in root.rglob("*.tmp")
            if path.is_file() and not path.is_relative_to(quarantine)
        )
        events.emit(
            "recovery.start",
            {"unfinished_sessions": 0, "tmp_files": len(temporary_files), "running_steps": 0},
        )

        actions: list[RecoveryAction] = []
        for temporary in temporary_files:
            target = _quarantine_tmp(root, temporary, quarantine)
            action = RecoveryAction("quarantine_tmp", temporary, target, restored_turns=0)
            actions.append(action)
            _emit_result(events, action)

        for raw_path in sorted(raw_dir.glob("*.jsonl")):
            tail_action = recover_jsonl_tail(raw_path, quarantine)
            if tail_action is not None:
                actions.append(tail_action)
                _emit_result(events, tail_action)

        if not actions:
            empty_action = RecoveryAction("none", None, None, restored_turns=0)
            actions.append(empty_action)
            _emit_result(events, empty_action)
    except RecoveryError:
        _emit_failure(events)
        raise
    except OSError as error:
        _emit_failure(events)
        raise RecoveryError(
            "시작 복구 중 파일을 안전하게 처리하지 못했습니다.",
            {"error_type": type(error).__name__},
        ) from error

    return RecoveryReport(
        tmp_files=sum(action.action == "quarantine_tmp" for action in actions),
        broken_tails=sum(action.action == "quarantine_broken_tail" for action in actions),
        actions=tuple(actions),
    )


def _emit_result(events: EventSink, action: RecoveryAction) -> None:
    events.emit(
        "recovery.result",
        {
            "action": action.action,
            "session_id": action.source.stem
            if action.source and action.source.suffix == ".jsonl"
            else None,
            "quarantined": str(action.quarantined) if action.quarantined else None,
            "restored_turns": action.restored_turns,
        },
    )


def _emit_failure(events: EventSink) -> None:
    events.emit(
        "recovery.result",
        {
            "action": "failed",
            "session_id": None,
            "quarantined": None,
            "restored_turns": 0,
        },
    )
