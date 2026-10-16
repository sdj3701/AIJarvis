# 파이썬 공부 | scripts/app/orchestrator/rulebook.py
# 응답 규칙을 읽고 검증하여 일관된 정책으로 제공합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Validated, immutable response policy; never loaded from conversation memory."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.core.errors import ConfigError

# 오른쪽 식을 계산한 값을 DEFAULT_RULEBOOK에 대입합니다.
DEFAULT_RULEBOOK = Path(__file__).with_name("prompts") / "response_rulebook.md"


# UniqueLoader: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: yaml.SafeLoader.
class UniqueLoader(yaml.SafeLoader):
    # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
    pass


# _mapping(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: loader, node.
# 반환 타입 힌트: dict[str, Any].
def _mapping(loader: UniqueLoader, node: yaml.MappingNode) -> dict[str, Any]:
    # result에 딕셔너리(키와 값의 쌍)을 대입합니다.
    result: dict[str, Any] = {}
    # for 반복문: 대상의 항목을 하나씩 (key_node, value_node)에 대입하며 아래 블록을 실행합니다.
    for key_node, value_node in node.value:
        # loader.construct_object()의 반환값을 key에 대입합니다.
        key = loader.construct_object(key_node)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(key, str) or key in
        # result.
        if not isinstance(key, str) or key in result:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("duplicate or non-string key")
        # loader.construct_object()의 반환값을 result[key]에 대입합니다.
        result[key] = loader.construct_object(value_node)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return result


# UniqueLoader.add_constructor()을 호출해 작업을 수행합니다.
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


# Rulebook: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class Rulebook:
    # version: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    version: int
    # sha256: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sha256: str
    # max_chars: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    max_chars: int
    # body: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    body: str

    # system_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def system_text(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        return (
            f"[response_rulebook version={self.version} sha256={self.sha256}]\n"
            f"기본 출력: 한국어 한 문장, {self.max_chars}자 이내; 안전 예외는 유지.\n{self.body}"
        )


# load_rulebook(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: Rulebook.
def load_rulebook(path: Path = DEFAULT_RULEBOOK) -> Rulebook:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with path.open("rb") as stream:
            # stream.read()의 반환값을 raw에 대입합니다.
            raw = stream.read(16385)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(raw) > 16384.
        if len(raw) > 16384:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("too large")
        # raw.decode('utf-8').replace()의 반환값을 text에 대입합니다.
        text = raw.decode("utf-8").replace("\r\n", "\n")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not text.startswith('---\n').
        if not text.startswith("---\n"):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("missing front matter")
        # 언패킹: 오른쪽 결과를 순서대로 (header, body)에 나누어 담습니다.
        header, body = text[4:].split("\n---\n", 1)
        # yaml.load()의 반환값을 data에 대입합니다.
        data = yaml.load(header, Loader=UniqueLoader)
        # expected에 딕셔너리(키와 값의 쌍)을 대입합니다.
        expected = {
            "schema_version": 1, "language": "ko", "default_style": "conclusion_only",
            "max_sentences": 1, "detail_on_request": True,
            "speech_style": "conclusion_only", "safety_exceptions": True,
        }
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(data, dict) or set(data) != {*expected, "rulebook_version", "max_chars"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("invalid fields")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if any(type(data[k]) is not type(v) or data[k] != v for k, v in expected.items()):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("unsupported policy")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if type(data["rulebook_version"]) is not int or data["rulebook_version"] < 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("invalid version")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if type(data["max_chars"]) is not int or not 40 <= data["max_chars"] <= 100:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("invalid length")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not body.strip().
        if not body.strip():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("empty rules")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Rulebook(data["rulebook_version"], hashlib.sha256(raw).hexdigest(),
                        data["max_chars"], body.strip())
    # (OSError, UnicodeError, ValueError, yaml.YAMLError)를 잡아 처리합니다. as 뒤의 이름에는
    # 발생한 예외 객체가 담깁니다.
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "응답 룰북을 읽거나 검증할 수 없습니다. 파일을 확인하고 재시작하세요."
        ) from error
