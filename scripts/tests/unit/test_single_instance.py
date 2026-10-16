# 파이썬 공부 | scripts/tests/unit/test_single_instance.py
# single_instance 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

from __future__ import annotations

from pathlib import Path

import pytest

from app.ui.single_instance import AlreadyRunningError, SingleInstanceLock

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0


# pytest가 test_second_instance_refused()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_second_instance_refused(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "state" / "jarvis.lock"
    # SingleInstanceLock()의 반환값을 first에 대입합니다.
    first = SingleInstanceLock(path)
    # SingleInstanceLock()의 반환값을 second에 대입합니다.
    second = SingleInstanceLock(path)
    # first.acquire()을 호출해 작업을 수행합니다.
    first.acquire()

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(AlreadyRunningError, match="이미 실행 중") as captured:
        # second.acquire()을 호출해 작업을 수행합니다.
        second.acquire()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.user_message == "Jarvis가 이미 실행 중입니다."
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.acquired
    # first.release()을 호출해 작업을 수행합니다.
    first.release()
    # second.acquire()을 호출해 작업을 수행합니다.
    second.acquire()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.acquired
    # second.release()을 호출해 작업을 수행합니다.
    second.release()


# pytest가 test_single_instance_context_releases_after_error()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_single_instance_context_releases_after_error(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "jarvis.lock"

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(RuntimeError, match="boom"), SingleInstanceLock(path):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError("boom")

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with SingleInstanceLock(path) as lock:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert lock.acquired
