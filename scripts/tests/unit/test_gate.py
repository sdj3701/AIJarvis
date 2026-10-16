# 파이썬 공부 | scripts/tests/unit/test_gate.py
# gate 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Phase 게이트 증거의 작업 트리 결합 검증."""

from __future__ import annotations

from subprocess import CompletedProcess

import pytest

from scripts import gate

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0


# pytest가 test_worktree_changes_ignore_only_gate_artifacts()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_worktree_changes_ignore_only_gate_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # CompletedProcess()의 반환값을 result에 대입합니다.
    result = CompletedProcess(
        args=["git"],
        returncode=0,
        stdout=(
            " M scripts/app/rag/fetcher.py\n"
            "?? artifacts/gates/phase5-20260811.json\n"
        ),
        stderr="",
    )
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: result)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert gate._worktree_changes() == (" M scripts/app/rag/fetcher.py",)
