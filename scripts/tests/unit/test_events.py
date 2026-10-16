# 파이썬 공부 | scripts/tests/unit/test_events.py
# events 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0


# _writer(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: logs_dir, fsync_events.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: JsonlEventWriter.
def _writer(logs_dir: Path, *, fsync_events: bool = False) -> JsonlEventWriter:
    # LogMasker()의 반환값을 masker에 대입합니다.
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
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return JsonlEventWriter(
        logs_dir,
        clock=FrozenClock(datetime(2026, 8, 11, 12, 34, 56, 789000, tzinfo=KST)),
        masker=masker,
        fsync_events=fsync_events,
    )


# pytest가 test_event_envelope_is_appended_and_masked()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_event_envelope_is_appended_and_masked(tmp_path: Path) -> None:
    # _writer()의 반환값을 writer에 대입합니다.
    writer = _writer(tmp_path / "logs")
    # secret에 문자열을 대입합니다.
    secret = "sk-abcdefghijklmnopqrstuvwxyz"
    # EventIdentity()의 반환값을 identity에 대입합니다.
    identity = EventIdentity(
        request_id="req_01J8Z9K3M4N5P6Q7R8S9T0ABCD",
        session_id="ses_01J8Z9K3M4N5P6Q7R8S9T0ABCD",
        turn_id="turn_01J8Z9K3M4N5P6Q7R8S9T0ABCD",
    )

    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
    writer.emit("error", {"detail": {"message": secret}}, identity=identity, level="error")
    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
    writer.emit("app.stop", {"exit_code": 0, "uptime_ms": 10})

    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "logs" / "events-2026-08-11.jsonl"
    # path.read_text()의 반환값을 raw에 대입합니다.
    raw = path.read_text(encoding="utf-8")
    # 오른쪽 식을 계산한 값을 events에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    events = [json.loads(line) for line in raw.splitlines()]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert secret not in raw
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(events) == 2
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
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


# pytest가 test_event_writer_flushes_then_fsyncs()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path, monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_event_writer_flushes_then_fsyncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
    calls: list[int] = []
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.telemetry.events.os.fsync", calls.append)
    # _writer()의 반환값을 writer에 대입합니다.
    writer = _writer(tmp_path / "logs", fsync_events=True)

    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
    writer.emit("app.start", {"version": "0.0.0", "pid": 1})

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(calls) == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert (tmp_path / "logs" / "events-2026-08-11.jsonl").read_text(encoding="utf-8")


# pytest가 test_required_sensitive_test_strings_are_never_written()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_required_sensitive_test_strings_are_never_written(tmp_path: Path) -> None:
    # sensitive에 리스트(순서가 있고 수정 가능)을 대입합니다.
    sensitive = [
        "sk-abcdefghijklmnopqrstuvwxyz",
        "Bearer abcdefghijklmnopqrstuvwxyz",
        "-----BEGIN RSA PRIVATE KEY-----",
        "900101-1234567",
    ]
    # 오른쪽 식을 계산한 값을 logs에 대입합니다.
    logs = tmp_path / "logs"

    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
    _writer(logs).emit("error", {"samples": sensitive})

    # (logs / 'events-2026-08-11.jsonl').read_text()의 반환값을 raw에 대입합니다.
    raw = (logs / "events-2026-08-11.jsonl").read_text(encoding="utf-8")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all(value not in raw for value in sensitive)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert json.loads(raw)["redactions"] == [
        {"action": "mask", "count": 1, "detector_id": "bearer"},
        {"action": "mask", "count": 1, "detector_id": "private_key"},
        {"action": "mask", "count": 1, "detector_id": "rrn"},
        {"action": "mask", "count": 1, "detector_id": "secret"},
    ]


# pytest가 test_required_phase_zero_event_types_are_supported()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path, event_type.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    "event_type",
    [
        "app.start",
        "app.stop",
        "error",
        "recovery.start",
        "recovery.result",
        "voice.barge_in",
    ],
)
def test_required_phase_zero_event_types_are_supported(tmp_path: Path, event_type: str) -> None:
    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
    _writer(tmp_path / event_type.replace(".", "_")).emit(event_type, {})


# pytest가 test_unknown_event_type_is_rejected_before_file_creation()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_unknown_event_type_is_rejected_before_file_creation(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 logs에 대입합니다.
    logs = tmp_path / "logs"
    # _writer()의 반환값을 writer에 대입합니다.
    writer = _writer(logs)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="unsupported event_type"):
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        writer.emit("unknown.event", {})

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert list(logs.iterdir()) == []
