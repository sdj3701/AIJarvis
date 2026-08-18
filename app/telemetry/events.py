"""Append privacy-safe structured events to daily JSONL files."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from app.core.clock import Clock
from app.core.errors import JarvisError
from app.telemetry.masking import JsonValue, LogMasker

Actor = Literal["user", "assistant", "system", "tool"]
Level = Literal["debug", "info", "warn", "error"]

EVENT_TYPES = frozenset(
    {
        "app.start",
        "app.stop",
        "session.start",
        "session.checkpoint",
        "session.end",
        "session.summary_failed",
        "user.input",
        "llm.request",
        "llm.response",
        "llm.retry",
        "privacy.redact",
        "privacy.block",
        "memory.search",
        "memory.write",
        "memory.confirm",
        "memory.supersede",
        "memory.delete",
        "agent.step",
        "agent.stop",
        "tool.intent",
        "tool.result",
        "approval.request",
        "approval.grant",
        "approval.deny",
        "approval.mismatch",
        "approval.cancel",
        "policy.deny",
        "rag.index",
        "secrets.dev_fallback",
        "retention.run",
        "backup.result",
        "backup.restore",
        "budget.warn",
        "budget.stop",
        "voice.recording",
        "voice.barge_in",
        "voice.source_filter",
        "stt.result",
        "tts.result",
        "ui.state",
        "ui.hotkey",
        "recovery.start",
        "recovery.result",
        "error",
    }
)
_ID_PATTERN = re.compile(r"^(req|ses|turn|task)_[0-9A-HJKMNP-TV-Z]{26}$")


@dataclass(frozen=True, slots=True)
class EventIdentity:
    request_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    task_id: str | None = None

    def __post_init__(self) -> None:
        for value in (self.request_id, self.session_id, self.turn_id, self.task_id):
            if value is not None and _ID_PATTERN.fullmatch(value) is None:
                raise ValueError("event identity contains an invalid identifier")


class JsonlEventWriter:
    """Synchronous event writer whose successful return means data was flushed."""

    def __init__(
        self,
        logs_dir: Path,
        *,
        clock: Clock,
        masker: LogMasker,
        fsync_events: bool,
    ) -> None:
        self._logs_dir = Path(logs_dir)
        self._clock = clock
        self._masker = masker
        self._fsync_events = fsync_events
        self._lock = RLock()
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        identity: EventIdentity | None = None,
        actor: Actor = "system",
        level: Level = "info",
    ) -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {event_type}")
        if actor not in {"user", "assistant", "system", "tool"}:
            raise ValueError("unsupported event actor")
        if level not in {"debug", "info", "warn", "error"}:
            raise ValueError("unsupported event level")

        sanitized, findings = self._masker.sanitize_value(payload)
        if not isinstance(sanitized, dict):
            raise TypeError("event payload must be a mapping")
        counts = Counter(finding.detector_id for finding in findings)
        redactions: list[JsonValue] = [
            {"detector_id": detector_id, "action": "mask", "count": count}
            for detector_id, count in sorted(counts.items())
        ]
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("event clock must return a timezone-aware datetime")
        event_identity = identity or EventIdentity()
        envelope: dict[str, JsonValue] = {
            "v": 1,
            "ts": now.isoformat(timespec="milliseconds"),
            "event_type": event_type,
            "request_id": event_identity.request_id,
            "session_id": event_identity.session_id,
            "turn_id": event_identity.turn_id,
            "task_id": event_identity.task_id,
            "actor": actor,
            "level": level,
            "payload": sanitized,
            "redactions": redactions,
        }
        line = json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        path = self._logs_dir / f"events-{now.date().isoformat()}.jsonl"

        try:
            with self._lock, path.open("a", encoding="utf-8", newline="\n") as output:
                output.write(line)
                output.write("\n")
                output.flush()
                if self._fsync_events:
                    os.fsync(output.fileno())
        except OSError as error:
            raise JarvisError(
                "이벤트 로그를 기록할 수 없습니다.",
                {"error_type": type(error).__name__, "log_file": path.name},
            ) from error
