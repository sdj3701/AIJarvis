# 파이썬 공부 | scripts/app/rag/benchmark/datasets.py
# 정답 문서 정보가 담긴 JSON 평가 데이터를 읽습니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Load the editable JSON relevance-judgment dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from app.rag.benchmark.models import EvaluationQuery, QueryType

# frozenset()의 반환값을 _QUERY_TYPES에 대입합니다.
_QUERY_TYPES = frozenset(("keyword", "semantic", "hybrid"))


# load_evaluation_queries(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: tuple[EvaluationQuery, ...].
def load_evaluation_queries(path: Path) -> tuple[EvaluationQuery, ...]:
    """Validate and load human-maintained query relevance judgments.

    Relevance remains document-level on purpose: a relevant document is counted
    once even when several of its chunks appear in a retrieval result.
    """

    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # json.loads()의 반환값을 raw에 대입합니다.
        raw = json.loads(path.read_text(encoding="utf-8"))
    # FileNotFoundError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except FileNotFoundError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"평가 쿼리 파일이 없습니다: {path}") from error
    # (OSError, UnicodeError, json.JSONDecodeError)를 잡아 처리합니다. as 뒤의 이름에는 발생한
    # 예외 객체가 담깁니다.
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"평가 쿼리 파일을 읽을 수 없습니다: {path}") from error

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(raw, list).
    if not isinstance(raw, list):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("datasets/evaluation_queries.json의 최상위 값은 배열이어야 합니다.")

    # queries에 리스트(순서가 있고 수정 가능)을 대입합니다.
    queries: list[EvaluationQuery] = []
    # set()의 반환값을 query_ids에 대입합니다.
    query_ids: set[str] = set()
    # for 반복문: 대상의 항목을 하나씩 (position, item)에 대입하며 아래 블록을 실행합니다.
    for position, item in enumerate(raw, start=1):
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(item, dict).
        if not isinstance(item, dict):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"평가 쿼리 {position}번은 객체여야 합니다.")
        # _required_text()의 반환값을 query_id에 대입합니다.
        query_id = _required_text(item, "query_id", position)
        # _required_text()의 반환값을 query에 대입합니다.
        query = _required_text(item, "query", position)
        # _required_text()의 반환값을 raw_type에 대입합니다.
        raw_type = _required_text(item, "query_type", position)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: raw_type not in _QUERY_TYPES.
        if raw_type not in _QUERY_TYPES:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"평가 쿼리 {query_id}의 query_type이 올바르지 않습니다: {raw_type}")
        # item.get()의 반환값을 raw_relevant에 대입합니다.
        raw_relevant = item.get("relevant_document_ids")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(raw_relevant, list) or
        # not raw_relevant.
        if not isinstance(raw_relevant, list) or not raw_relevant:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(
                f"평가 쿼리 {query_id}에는 하나 이상의 relevant_document_ids가 필요합니다."
            )
        # tuple()의 반환값을 relevant에 대입합니다.
        relevant = tuple(str(value).strip() for value in raw_relevant)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: any((not value for value in
        # relevant)).
        if any(not value for value in relevant):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"평가 쿼리 {query_id}의 relevant_document_ids에 빈 값이 있습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: query_id in query_ids.
        if query_id in query_ids:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"중복된 query_id입니다: {query_id}")
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        query_ids.add(query_id)
        # 리스트 끝에 항목 하나를 추가합니다.
        queries.append(
            EvaluationQuery(
                query_id=query_id,
                query=query,
                query_type=cast(QueryType, raw_type),
                relevant_document_ids=tuple(dict.fromkeys(relevant)),
            )
        )

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not queries.
    if not queries:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("평가 쿼리가 비어 있습니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return tuple(queries)


# _required_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: item, key, position.
# 반환 타입 힌트: 문자열(str).
def _required_text(item: dict[str, Any], key: str, position: int) -> str:
    # item.get()의 반환값을 value에 대입합니다.
    value = item.get(key)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, str) or not
    # value.strip().
    if not isinstance(value, str) or not value.strip():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(f"평가 쿼리 {position}번의 {key}은 비어 있지 않은 문자열이어야 합니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value.strip()
