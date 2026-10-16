# 파이썬 공부 | scripts/app/rag/search_provider.py
# 웹 검색의 공통 규약과 DuckDuckGo 검색 구현을 제공합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Web search provider protocol and DuckDuckGo implementation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.errors import JarvisError
from app.rag.models import SearchHit


# SearchFailed: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class SearchFailed(JarvisError):
    """Search provider returned an error or unusable response."""


# SearchProvider: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class SearchProvider(Protocol):
    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, max_results, timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: tuple[SearchHit, ...].
    def search(
        self,
        query: str,
        *,
        max_results: int,
        timeout_s: float,
    ) -> tuple[SearchHit, ...]: ...


# DuckDuckGoProvider: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class DuckDuckGoProvider:
    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, max_results, timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: tuple[SearchHit, ...].
    def search(
        self,
        query: str,
        *,
        max_results: int,
        timeout_s: float,
    ) -> tuple[SearchHit, ...]:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            from ddgs import DDGS
        # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ImportError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SearchFailed(
                "검색 패키지가 설치되지 않았습니다. "
                "pip install jarvis-assistant[search]를 실행하세요.",
                {"provider": "duckduckgo"},
            ) from error

        # datetime.now().astimezone()의 반환값을 fetched_at에 대입합니다.
        fetched_at = datetime.now().astimezone()
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 아래 함수()의 반환값을 raw_results에 대입합니다.
            raw_results: object = DDGS(timeout=max(1, math.ceil(timeout_s))).text(
                query,
                max_results=max_results,
            )
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SearchFailed(
                "웹 검색 요청에 실패했습니다.",
                {"provider": "duckduckgo", "error_type": type(error).__name__},
            ) from error

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(raw_results, list).
        if not isinstance(raw_results, list):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise SearchFailed("웹 검색 응답 형식이 올바르지 않습니다.")

        # hits에 리스트(순서가 있고 수정 가능)을 대입합니다.
        hits: list[SearchHit] = []
        # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
        for item in raw_results:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(item, dict).
            if not isinstance(item, dict):
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # 리스트 끝에 항목 하나를 추가합니다.
            hits.append(
                SearchHit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("href") or item.get("url") or ""),
                    snippet=str(item.get("body") or item.get("snippet") or ""),
                    published_at=None,
                    fetched_at=fetched_at,
                )
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(hits)


# build_search_provider(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: provider_name.
# 반환 타입 힌트: SearchProvider.
def build_search_provider(provider_name: str) -> SearchProvider:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: provider_name == 'duckduckgo'.
    if provider_name == "duckduckgo":
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return DuckDuckGoProvider()
    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
    raise SearchFailed(f"지원하지 않는 검색 제공자입니다: {provider_name}")
