# 파이썬 공부 | scripts/tests/security/test_reparse_points.py
# reparse_points 관련 보안 경계을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Junction-based sandbox escape attempts."""

from __future__ import annotations

import os
import subprocess

import pytest

from app.llm.base import ToolCall
from tests.helpers.phase4_app import Phase4App
from tests.security.test_approval_binding import _ctx

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase4, pytest.mark.security]


# pytest가 test_junction_escape_blocked()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: phase4_app.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_junction_escape_blocked(phase4_app: Phase4App) -> None:
    # 오른쪽 식을 계산한 값을 data_root에 대입합니다.
    data_root = phase4_app.data_root
    # 오른쪽 식을 계산한 값을 outside에 대입합니다.
    outside = data_root.parent / "outside"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    outside.mkdir(exist_ok=True)
    # 오른쪽 식을 계산한 값을 link에 대입합니다.
    link = data_root / "docs" / "notes" / "link"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    link.parent.mkdir(parents=True, exist_ok=True)
    # subprocess.run()의 반환값을 result에 대입합니다.
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: result.returncode != 0.
    if result.returncode != 0:
        # pytest.skip()을 호출해 작업을 수행합니다.
        pytest.skip("junction creation requires appropriate permissions")
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(
        id="junction",
        name="create_file",
        arguments={"root": "notes", "relative_path": "link\\x.md", "content": "x"},
    )
    # phase4_app.chat.execute_tool_call()의 반환값을 outcome에 대입합니다.
    outcome = phase4_app.chat.execute_tool_call(call, ctx=_ctx(phase4_app))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not outcome.ok
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not (outside / "x.md").exists()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert phase4_app.audit()[-1]["phase"] == "denied"
