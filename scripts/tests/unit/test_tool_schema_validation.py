# 파이썬 공부 | scripts/tests/unit/test_tool_schema_validation.py
# tool_schema_validation 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for search tool JSON schema and structured output contracts."""

from __future__ import annotations

import pytest

from app.core.errors import ToolArgInvalid
from app.tools.registry import validate_structured_output, validate_tool_args

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase3

# WEB_SCHEMA에 딕셔너리(키와 값의 쌍)을 대입합니다.
WEB_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "maxLength": 300},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 8},
    },
}


# pytest가 test_search_output_contracts()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_search_output_contracts() -> None:
    # validate_structured_output()으로 입력 형식과 허용 조건을 검사합니다.
    validate_structured_output(
        "web_search",
        {
            "query": "jarvis",
            "hits": [
                {
                    "title": "t",
                    "url": "https://example.com",
                    "snippet": "s",
                    "published_at": None,
                    "fetched_at": "2026-08-10T21:00:00+09:00",
                }
            ],
        },
    )
    # validate_structured_output()으로 입력 형식과 허용 조건을 검사합니다.
    validate_structured_output(
        "doc_search",
        {
            "query": "memory",
            "hits": [
                {
                    "chunk_id": "chk_1",
                    "doc_id": "doc_1",
                    "relative_path": "public\\guide.md",
                    "ordinal": 0,
                    "text": "본문",
                    "start_char": 0,
                    "end_char": 2,
                    "transfer_class": "api_allowed",
                    "score": 0.5,
                }
            ],
        },
    )


# pytest가 test_unknown_arg_rejected()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_unknown_arg_rejected() -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolArgInvalid):
        # validate_tool_args()으로 입력 형식과 허용 조건을 검사합니다.
        validate_tool_args(WEB_SCHEMA, {"query": "x", "evil": True})


# pytest가 test_control_chars_rejected()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_control_chars_rejected() -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolArgInvalid):
        # validate_tool_args()으로 입력 형식과 허용 조건을 검사합니다.
        validate_tool_args(WEB_SCHEMA, {"query": "bad\x00query"})


# pytest가 test_open_and_close_app_schema_validation()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_open_and_close_app_schema_validation() -> None:
    # schema에 딕셔너리(키와 값의 쌍)을 대입합니다.
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["app"],
        "properties": {
            "app": {"type": "string", "enum": ["calc", "notepad"]},
        },
    }
    # Valid app
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert validate_tool_args(schema, {"app": "notepad"}) == {"app": "notepad"}

    # Invalid unlisted app
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolArgInvalid):
        # validate_tool_args()으로 입력 형식과 허용 조건을 검사합니다.
        validate_tool_args(schema, {"app": "chrome"})

    # Missing required 'app'
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolArgInvalid):
        # validate_tool_args()으로 입력 형식과 허용 조건을 검사합니다.
        validate_tool_args(schema, {})

    # Unknown parameter injection
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolArgInvalid):
        # validate_tool_args()으로 입력 형식과 허용 조건을 검사합니다.
        validate_tool_args(schema, {"app": "notepad", "extra_arg": "hack"})


# pytest가 test_create_file_schema_validation()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_create_file_schema_validation() -> None:
    # schema에 딕셔너리(키와 값의 쌍)을 대입합니다.
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["root", "relative_path", "content"],
        "properties": {
            "root": {"type": "string", "enum": ["notes", "docs"]},
            "relative_path": {"type": "string", "maxLength": 512},
            "content": {"type": "string", "maxLength": 1000},
            "overwrite": {"type": "boolean"},
        },
    }
    # Valid call
    # valid_args에 딕셔너리(키와 값의 쌍)을 대입합니다.
    valid_args = {
        "root": "notes",
        "relative_path": "meeting.txt",
        "content": "hello world",
        "overwrite": True,
    }
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert validate_tool_args(schema, valid_args) == valid_args

    # Unlisted root
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolArgInvalid):
        # validate_tool_args()으로 입력 형식과 허용 조건을 검사합니다.
        validate_tool_args(schema, {**valid_args, "root": "system32"})

    # Content length exceeded
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolArgInvalid):
        # validate_tool_args()으로 입력 형식과 허용 조건을 검사합니다.
        validate_tool_args(schema, {**valid_args, "content": "x" * 1001})

    # Non-boolean overwrite
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ToolArgInvalid):
        # validate_tool_args()으로 입력 형식과 허용 조건을 검사합니다.
        validate_tool_args(schema, {**valid_args, "overwrite": "yes"})
