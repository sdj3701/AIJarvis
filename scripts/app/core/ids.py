# 파이썬 공부 | scripts/app/core/ids.py
# 접두사와 ULID를 조합해 파일 이름에도 쓸 수 있는 식별자를 만듭니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""ULID-based identifiers with validated, filename-safe prefixes."""

from __future__ import annotations

import re
from typing import Protocol

from ulid import ULID

# re.compile()의 반환값을 _PREFIX_PATTERN에 대입합니다.
_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,15}$")
# re.compile()의 반환값을 _ULID_PATTERN에 대입합니다.
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


# IdGenerator: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class IdGenerator(Protocol):
    # new(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def new(self) -> str: ...


# PrefixedIdFactory: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class PrefixedIdFactory(Protocol):
    # new(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: prefix.
    # 반환 타입 힌트: 문자열(str).
    def new(self, prefix: str) -> str: ...


# SystemUlidGenerator: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SystemUlidGenerator:
    # new(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def new(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return str(ULID())


# SystemUlidGenerator()의 반환값을 _generator에 대입합니다.
_generator: IdGenerator = SystemUlidGenerator()


# 접두사와 생성된 식별자를 각각 검증한 뒤 밑줄로 연결합니다.
# 입력: prefix, generator.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def new_id(prefix: str, *, generator: IdGenerator | None = None) -> str:
    """Create ``<prefix>_<ULID>`` and reject unsafe or ambiguous components."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not _PREFIX_PATTERN.fullmatch(prefix).
    if not _PREFIX_PATTERN.fullmatch(prefix):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("ID prefix must be lowercase ASCII alphanumeric without separators")
    # (generator or _generator).new()의 반환값을 ulid에 대입합니다.
    ulid = (generator or _generator).new()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not _ULID_PATTERN.fullmatch(ulid).
    if not _ULID_PATTERN.fullmatch(ulid):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("ID generator returned an invalid ULID")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    return f"{prefix}_{ulid}"


# SystemIdFactory: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SystemIdFactory:
    """Production factory injected into the runtime wiring."""

    # new(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: prefix.
    # 반환 타입 힌트: 문자열(str).
    def new(self, prefix: str) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return new_id(prefix)
