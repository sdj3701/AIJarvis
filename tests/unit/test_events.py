from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.config.models import DetectorPolicy, MaskPolicy
from app.core.clock import KST
from app.telemetry.events import EventIdentity, JsonlEventWriter
from app.telemetry.masking import LogMasker
from tests.fakes.clock import FrozenClock

pytestmark = pytest.mark.phase0


def _writer(logs_dir: Path, *, fsync_events: bool = False) -> JsonlEventWriter:
    masker = LogMasker(
        [
            DetectorPolicy(
                id="secret",
                label="시크릿",
                pattern=r"sk-[A-Za-z0-9_\-]{20,}",
                action="block",
                kind="secret",
            ),
            DetectorPolicy(
                id="bearer",
                label="Bearer 토큰",
                pattern=r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}",
                action="block",
                kind="secret",
            ),
            DetectorPolicy(
                id="private_key",
                label="개인키",
                pattern=r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                action="block",
                kind="secret",
            ),
            DetectorPolicy(
                id="rrn",
                label="주민등록번호",
                pattern=r"\b\d{6}[-\s]?[1-4]\d{6}\b",
                action="block",
                kind="pii_high",
            ),
        ],
        MaskPolicy(replacement="[{label}]", keep_tail={}),
    )
    return JsonlEventWriter(
        logs_dir,
        clock=FrozenClock(datetime(2026, 8, 11, 12, 34, 56, 789000, tzinfo=KST)),
        masker=masker,
        fsync_events=fsync_events,
    )


def test_event_envelope_is_appended_and_masked(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "logs")
    secret = "sk-abcdefghijklmnopqrstuvwxyz"
    identity = EventIdentity(
        request_id="req_01J8Z9K3M4N5P6Q7R8S9T0ABCD",
        session_id="ses_01J8Z9K3M4N5P6Q7R8S9T0ABCD",
        turn_id="turn_01J8Z9K3M4N5P6Q7R8S9T0ABCD",
    )

    writer.emit("error", {"detail": {"message": secret}}, identity=identity, level="error")
    writer.emit("app.stop", {"exit_code": 0, "uptime_ms": 10})

    path = tmp_path / "logs" / "events-2026-08-11.jsonl"
    raw = path.read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw.splitlines()]
    assert secret not in raw
    assert len(events) == 2
    assert events[0] == {
        "actor": "system",
        "event_type": "error",
        "level": "error",
        "payload": {"detail": {"message": "[시크릿]"}},
        "redactions": [{"action": "mask", "count": 1, "detector_id": "secret"}],
        "request_id": identity.request_id,
        "session_id": identity.session_id,
        "task_id": None,
        "ts": "2026-08-11T12:34:56.789+09:00",
        "turn_id": identity.turn_id,
        "v": 1,
    }


def test_event_writer_flushes_then_fsyncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr("app.telemetry.events.os.fsync", calls.append)
    writer = _writer(tmp_path / "logs", fsync_events=True)

    writer.emit("app.start", {"version": "0.0.0", "pid": 1})

    assert len(calls) == 1
    assert (tmp_path / "logs" / "events-2026-08-11.jsonl").read_text(encoding="utf-8")


def test_required_sensitive_test_strings_are_never_written(tmp_path: Path) -> None:
    sensitive = [
        "sk-abcdefghijklmnopqrstuvwxyz",
        "Bearer abcdefghijklmnopqrstuvwxyz",
        "-----BEGIN RSA PRIVATE KEY-----",
        "900101-1234567",
    ]
    logs = tmp_path / "logs"

    _writer(logs).emit("error", {"samples": sensitive})

    raw = (logs / "events-2026-08-11.jsonl").read_text(encoding="utf-8")
    assert all(value not in raw for value in sensitive)
    assert json.loads(raw)["redactions"] == [
        {"action": "mask", "count": 1, "detector_id": "bearer"},
        {"action": "mask", "count": 1, "detector_id": "private_key"},
        {"action": "mask", "count": 1, "detector_id": "rrn"},
        {"action": "mask", "count": 1, "detector_id": "secret"},
    ]


@pytest.mark.parametrize(
    "event_type",
    [
        "app.start",
        "app.stop",
        "error",
        "recovery.start",
        "recovery.result",
        "voice.barge_in",
        "voice.source_filter",
    ],
)
def test_required_phase_zero_event_types_are_supported(tmp_path: Path, event_type: str) -> None:
    _writer(tmp_path / event_type.replace(".", "_")).emit(event_type, {})


def test_unknown_event_type_is_rejected_before_file_creation(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    writer = _writer(logs)

    with pytest.raises(ValueError, match="unsupported event_type"):
        writer.emit("unknown.event", {})

    assert list(logs.iterdir()) == []
