# 파이썬 공부 | scripts/app/rag/models.py
# 문서 검색과 색인 결과의 데이터 구조를 정의합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Structured RAG search and indexing models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


# SearchHit: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SearchHit:
    # title: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    title: str
    # url: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    url: str
    # snippet: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    snippet: str
    # published_at: datetime | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    published_at: datetime | None
    # fetched_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    fetched_at: datetime


# FetchedDocument: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class FetchedDocument:
    # requested_url: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    requested_url: str
    # final_url: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    final_url: str
    # title: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    title: str
    # content: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    content: str
    # content_type: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    content_type: str
    # fetched_at: datetime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    fetched_at: datetime
    # truncated: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    truncated: bool


# RetrievedChunk: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    # chunk_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    chunk_id: str
    # doc_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    doc_id: str
    # relative_path: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    relative_path: str
    # ordinal: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ordinal: int
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # start_char: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    start_char: int
    # end_char: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    end_char: int
    # transfer_class: Literal['local_only', 'api_allowed'] 타입을 기대하는 필드입니다. 이 줄만으로
    # 값이 대입되지는 않습니다.
    transfer_class: Literal["local_only", "api_allowed"]
    # score: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    score: float
    rerank_score: float | None = None
    title: str = ""
    pages: tuple[int, ...] = ()
    structure: tuple[str, ...] = ()
    spans: tuple[dict[str, object], ...] = ()


# IndexReport: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class IndexReport:
    # indexed: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    indexed: int
    # updated: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    updated: int
    # removed: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    removed: int
    # skipped: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    skipped: int
    # errors: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    errors: tuple[str, ...]
