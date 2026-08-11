"""웹 검색 제공자 계약 테스트."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from app.rag.search_provider import DuckDuckGoProvider

pytestmark = pytest.mark.phase3


def test_duckduckgo_receives_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[int] = []

    class FakeDDGS:
        def __init__(self, *, timeout: int) -> None:
            captured.append(timeout)

        def text(self, query: str, *, max_results: int) -> list[dict[str, str]]:
            assert query == "테스트"
            assert max_results == 3
            return []

    module = ModuleType("ddgs")
    module.DDGS = FakeDDGS  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ddgs", module)

    hits = DuckDuckGoProvider().search("테스트", max_results=3, timeout_s=1.2)

    assert hits == ()
    assert captured == [2]
