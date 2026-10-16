# 파이썬 공부 | scripts/tests/security/test_url_schemes_open_url.py
# url_schemes_open_url 관련 보안 경계을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""URL scheme blocking for open_url via SafetyGate."""

from __future__ import annotations

import pytest

from app.llm.base import ToolCall
from tests.helpers.phase4_app import Phase4App, read_lines
from tests.security.test_approval_binding import _ctx

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase4, pytest.mark.security]


# pytest가 test_open_url_scheme_corpus_blocked()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: phase4_app, url.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("url", read_lines("url_schemes.txt"))
def test_open_url_scheme_corpus_blocked(phase4_app: Phase4App, url: str) -> None:
    # 오른쪽 식을 계산한 값을 gate에 대입합니다.
    gate = phase4_app.runtime.safety_gate
    # 오른쪽 식을 계산한 값을 spec에 대입합니다.
    spec = phase4_app.runtime.tool_registry.specs["open_url"]
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall(id="u1", name="open_url", arguments={"url": url})
    # gate.evaluate()의 반환값을 verdict에 대입합니다.
    verdict = gate.evaluate(call, ctx=_ctx(phase4_app), spec=spec)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict.decision == "deny", url
