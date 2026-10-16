# 파이썬 공부 | scripts/tests/unit/test_canonical_hash.py
# canonical_hash 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for canonical JSON and tool-bound argument hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.canonical import args_hash, canonical_json

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0


# pytest가 test_canonical_json_sorts_keys_and_uses_compact_utf8()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_canonical_json_sorts_keys_and_uses_compact_utf8() -> None:
    # canonical_json()의 반환값을 first에 대입합니다.
    first = canonical_json({"한글": [True, None, 3], "a": "값"})
    # canonical_json()의 반환값을 second에 대입합니다.
    second = canonical_json({"a": "값", "한글": [True, None, 3]})

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first == second
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first == '{"a":"값","한글":[true,null,3]}'.encode()


# pytest가 test_canonical_json_normalizes_unicode_to_nfc()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_canonical_json_normalizes_unicode_to_nfc() -> None:
    # decomposed에 문자열을 대입합니다.
    decomposed = "e\u0301"
    # composed에 문자열을 대입합니다.
    composed = "é"

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert canonical_json({decomposed: decomposed}) == canonical_json({composed: composed})


# pytest가 test_canonical_json_rejects_keys_that_collide_after_normalization()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_canonical_json_rejects_keys_that_collide_after_normalization() -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # canonical_json()을 호출해 작업을 수행합니다.
        canonical_json({"e\u0301": 1, "é": 2})


# pytest가 test_canonical_json_rejects_float_everywhere()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: value.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("value", [0.1, {"nested": [1, 2.0]}, float("nan")])
def test_canonical_json_rejects_float_everywhere(value: object) -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(TypeError):
        # canonical_json()을 호출해 작업을 수행합니다.
        canonical_json(value)


# pytest가 test_canonical_json_rejects_unsupported_types()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: value.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("value", [{1: "non-string-key"}, Path("already-normalized")])
def test_canonical_json_rejects_unsupported_types(value: object) -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(TypeError):
        # canonical_json()을 호출해 작업을 수행합니다.
        canonical_json(value)


# pytest가 test_args_hash_includes_tool_name_and_null_separator()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_args_hash_includes_tool_name_and_null_separator() -> None:
    # arguments에 딕셔너리(키와 값의 쌍)을 대입합니다.
    arguments = {"path": "D:\\Jarvis\\docs\\note.md", "overwrite": False}
    # 아래 함수()의 반환값을 expected에 대입합니다.
    expected = hashlib.sha256(
        b"create_file\x00" + canonical_json(arguments)
    ).hexdigest()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert args_hash("create_file", arguments) == expected
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert args_hash("create_file", arguments) != args_hash("other_tool", arguments)


# pytest가 test_args_hash_rejects_invalid_tool_name()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tool_name.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("tool_name", ["", "OpenApp", "has-dash", "nul\x00name"])
def test_args_hash_rejects_invalid_tool_name(tool_name: str) -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # args_hash()을 호출해 작업을 수행합니다.
        args_hash(tool_name, {})
