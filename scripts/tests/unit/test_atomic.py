# 파이썬 공부 | scripts/tests/unit/test_atomic.py
# atomic 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.atomic import write_atomic

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0


# pytest가 test_write_atomic_flushes_before_replace()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path, monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_write_atomic_flushes_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = tmp_path / "settings.json"
    # 바이트 데이터를 파일에 기록합니다.
    target.write_bytes(b"old")
    # calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
    calls: list[str] = []
    # 오른쪽 식을 계산한 값을 original_fsync에 대입합니다.
    original_fsync = os.fsync
    # 오른쪽 식을 계산한 값을 original_replace에 대입합니다.
    original_replace = os.replace

    # recording_fsync(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: descriptor.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def recording_fsync(descriptor: int) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        calls.append("fsync")
        # original_fsync()을 호출해 작업을 수행합니다.
        original_fsync(descriptor)

    # recording_replace(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: source, destination.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def recording_replace(source: Path, destination: Path) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        calls.append("replace")
        # original_replace()을 호출해 작업을 수행합니다.
        original_replace(source, destination)

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.core.atomic.os.fsync", recording_fsync)
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.core.atomic.os.replace", recording_replace)

    # write_atomic()을 호출해 작업을 수행합니다.
    write_atomic(target, b"new")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert target.read_bytes() == b"new"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert calls[:2] == ["fsync", "replace"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not target.with_suffix(".json.tmp").exists()


# pytest가 test_write_atomic_leaves_recoverable_temp_when_replace_fails()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path, monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_write_atomic_leaves_recoverable_temp_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = tmp_path / "state.json"
    # 바이트 데이터를 파일에 기록합니다.
    target.write_bytes(b"old")

    # fail_replace(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: source, destination.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def fail_replace(source: Path, destination: Path) -> None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise OSError("simulated")

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.core.atomic.os.replace", fail_replace)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(OSError, match="simulated"):
        # write_atomic()을 호출해 작업을 수행합니다.
        write_atomic(target, b"new")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert target.read_bytes() == b"old"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert target.with_suffix(".json.tmp").read_bytes() == b"new"
