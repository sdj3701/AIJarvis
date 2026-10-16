# 파이썬 공부 | scripts/tests/unit/test_recovery.py
# recovery 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import RecoveryError
from app.core.recovery import recover_startup
from scripts.bootstrap import create_tree

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0


# RecordingEvents: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class RecordingEvents:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.items에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.items: list[tuple[str, dict[str, Any]]] = []

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.items.append((event_type, dict(payload)))


# _root(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
def _root(tmp_path: Path) -> Path:
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return root


# pytest가 test_leftover_temporary_file_is_quarantined_and_reported()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_leftover_temporary_file_is_quarantined_and_reported(tmp_path: Path) -> None:
    # _root()의 반환값을 root에 대입합니다.
    root = _root(tmp_path)
    # 오른쪽 식을 계산한 값을 temporary에 대입합니다.
    temporary = root / "docs" / "notes" / "draft.md.tmp"
    # 바이트 데이터를 파일에 기록합니다.
    temporary.write_bytes(b"partial")
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()

    # recover_startup()의 반환값을 report에 대입합니다.
    report = recover_startup(root, events)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.tmp_files == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.broken_tails == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not temporary.exists()
    # 오른쪽 식을 계산한 값을 quarantined에 대입합니다.
    quarantined = report.actions[0].quarantined
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert quarantined is not None and quarantined.read_bytes() == b"partial"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [event_type for event_type, _ in events.items] == [
        "recovery.start",
        "recovery.result",
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.items[1][1]["action"] == "quarantine_tmp"


# pytest가 test_broken_final_jsonl_line_is_moved_and_valid_lines_remain()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_broken_final_jsonl_line_is_moved_and_valid_lines_remain(tmp_path: Path) -> None:
    # _root()의 반환값을 root에 대입합니다.
    root = _root(tmp_path)
    # 오른쪽 식을 계산한 값을 raw_path에 대입합니다.
    raw_path = root / "memory" / "raw" / "ses_123.jsonl"
    # valid에 리스트(순서가 있고 수정 가능)을 대입합니다.
    valid = [{"turn": 1}, {"turn": 2}]
    # b''.join()의 반환값을 prefix에 대입합니다.
    prefix = b"".join(
        json.dumps(item, separators=(",", ":")).encode("utf-8") + b"\n" for item in valid
    )
    # broken에 숫자 등 고정된 값을 대입합니다.
    broken = b'{"turn":3'
    # 바이트 데이터를 파일에 기록합니다.
    raw_path.write_bytes(prefix + broken)
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()

    # recover_startup()의 반환값을 report에 대입합니다.
    report = recover_startup(root, events)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.broken_tails == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert raw_path.read_bytes() == prefix
    # 오른쪽 식을 계산한 값을 tail에 대입합니다.
    tail = report.actions[0].quarantined
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tail is not None and tail.name == "ses_123.tail"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tail.read_bytes() == broken
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.items[-1][1] == {
        "action": "quarantine_broken_tail",
        "session_id": "ses_123",
        "quarantined": str(tail),
        "restored_turns": 2,
    }


# pytest가 test_invalid_middle_jsonl_line_is_hard_failure_and_not_rewritten()을 실행해 아래 상황이
# 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_invalid_middle_jsonl_line_is_hard_failure_and_not_rewritten(tmp_path: Path) -> None:
    # _root()의 반환값을 root에 대입합니다.
    root = _root(tmp_path)
    # 오른쪽 식을 계산한 값을 raw_path에 대입합니다.
    raw_path = root / "memory" / "raw" / "ses_bad.jsonl"
    # original에 숫자 등 고정된 값을 대입합니다.
    original = b'{"turn":1}\nnot-json\n{"turn":3}\n'
    # 바이트 데이터를 파일에 기록합니다.
    raw_path.write_bytes(original)
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(RecoveryError, match="중간 레코드"):
        # recover_startup()을 호출해 작업을 수행합니다.
        recover_startup(root, events)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert raw_path.read_bytes() == original
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.items[-1][1]["action"] == "failed"


# pytest가 test_clean_startup_emits_explicit_no_action_result()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_clean_startup_emits_explicit_no_action_result(tmp_path: Path) -> None:
    # RecordingEvents()의 반환값을 events에 대입합니다.
    events = RecordingEvents()

    # recover_startup()의 반환값을 report에 대입합니다.
    report = recover_startup(_root(tmp_path), events)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.tmp_files == report.broken_tails == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert report.actions[0].action == "none"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [event_type for event_type, _ in events.items] == [
        "recovery.start",
        "recovery.result",
    ]
