# 파이썬 공부 | scripts/tests/unit/test_search_provider.py
# search_provider 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""웹 검색 제공자 계약 테스트."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from app.rag.search_provider import DuckDuckGoProvider

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase3


# pytest가 test_duckduckgo_receives_configured_timeout()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_duckduckgo_receives_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # captured에 리스트(순서가 있고 수정 가능)을 대입합니다.
    captured: list[int] = []

    # FakeDDGS: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class FakeDDGS:
        # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 입력: timeout.
        # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
        # 반환 타입 힌트: 별도 결과 없음(None).
        def __init__(self, *, timeout: int) -> None:
            # 리스트 끝에 항목 하나를 추가합니다.
            captured.append(timeout)

        # text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 입력: query, max_results.
        # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
        # 반환 타입 힌트: list[dict[str, str]].
        def text(self, query: str, *, max_results: int) -> list[dict[str, str]]:
            # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
            assert query == "테스트"
            # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
            assert max_results == 3
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return []

    # ModuleType()의 반환값을 module에 대입합니다.
    module = ModuleType("ddgs")
    # 오른쪽 식을 계산한 값을 module.DDGS에 대입합니다.
    module.DDGS = FakeDDGS  # type: ignore[attr-defined]
    # monkeypatch.setitem()을 호출해 작업을 수행합니다.
    monkeypatch.setitem(sys.modules, "ddgs", module)

    # DuckDuckGoProvider().search()의 반환값을 hits에 대입합니다.
    hits = DuckDuckGoProvider().search("테스트", max_results=3, timeout_s=1.2)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert hits == ()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured == [2]
