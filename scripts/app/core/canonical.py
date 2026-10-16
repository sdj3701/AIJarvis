# 파이썬 공부 | scripts/app/core/canonical.py
# 같은 데이터가 같은 JSON과 해시를 갖도록 표현을 통일합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Canonical JSON and tool-bound argument hashes."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

# re.compile()의 반환값을 _TOOL_NAME_PATTERN에 대입합니다.
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


# canonical_json(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: obj.
# 반환 타입 힌트: 바이트 데이터(bytes).
def canonical_json(obj: Any) -> bytes:
    """Serialize supported JSON values deterministically as normalized UTF-8."""
    # _normalize()의 반환값을 normalized에 대입합니다.
    normalized = _normalize(obj)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


# args_hash(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tool_name, normalized_args.
# 반환 타입 힌트: 문자열(str).
def args_hash(tool_name: str, normalized_args: dict[str, Any]) -> str:
    """Bind normalized arguments to a specific allowlisted tool name."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not
    # _TOOL_NAME_PATTERN.fullmatch(tool_name).
    if not _TOOL_NAME_PATTERN.fullmatch(tool_name):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("tool_name must be lowercase ASCII with optional underscores")
    # 오른쪽 식을 계산한 값을 payload에 대입합니다.
    payload = tool_name.encode("utf-8") + b"\x00" + canonical_json(normalized_args)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return hashlib.sha256(payload).hexdigest()


# _normalize(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value.
# 반환 타입 힌트: 어떤 타입이든 허용(Any).
def _normalize(value: Any) -> Any:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: value is None or isinstance(value, bool |
    # int).
    if value is None or isinstance(value, bool | int):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return value
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(value, float).
    if isinstance(value, float):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise TypeError("float values are forbidden in canonical policy JSON")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(value, str).
    if isinstance(value, str):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return unicodedata.normalize("NFC", value)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(value, list | tuple).
    if isinstance(value, list | tuple):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        return [_normalize(item) for item in value]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(value, dict).
    if isinstance(value, dict):
        # normalized에 딕셔너리(키와 값의 쌍)을 대입합니다.
        normalized: dict[str, Any] = {}
        # for 반복문: 대상의 항목을 하나씩 (key, item)에 대입하며 아래 블록을 실행합니다.
        for key, item in value.items():
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(key, str).
            if not isinstance(key, str):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise TypeError("canonical JSON object keys must be strings")
            # unicodedata.normalize()의 반환값을 normalized_key에 대입합니다.
            normalized_key = unicodedata.normalize("NFC", key)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: normalized_key in normalized.
            if normalized_key in normalized:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ValueError("canonical JSON keys collide after NFC normalization")
            # _normalize()의 반환값을 normalized[normalized_key]에 대입합니다.
            normalized[normalized_key] = _normalize(item)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return normalized
    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
    raise TypeError(f"unsupported canonical JSON type: {type(value).__name__}")
