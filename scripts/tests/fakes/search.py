# 파이썬 공부 | scripts/tests/fakes/search.py
# 외부 검색 대신 정해진 검색 결과를 돌려주는 테스트용 객체입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Deterministic search provider for offline tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.rag.models import SearchHit
from app.rag.search_provider import SearchFailed


# FakeSearchProvider: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class FakeSearchProvider:
    # field()의 반환값을 hits에 대입합니다.
    hits: list[SearchHit] = field(default_factory=list)
    # field()의 반환값을 calls에 대입합니다.
    calls: list[str] = field(default_factory=list)
    # fail_with을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    fail_with: SearchFailed | None = None

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
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del timeout_s
        # 리스트 끝에 항목 하나를 추가합니다.
        self.calls.append(query)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.fail_with is not None.
        if self.fail_with is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise self.fail_with
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(self.hits[:max_results])

    # add_hit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: title, url, snippet, fetched_at.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def add_hit(
        self,
        *,
        title: str,
        url: str,
        snippet: str,
        fetched_at: datetime | None = None,
    ) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=snippet,
                published_at=None,
                fetched_at=fetched_at or datetime.now().astimezone(),
            )
        )
