# 파이썬 공부 | scripts/app/tools/registry.py
# 사용 가능한 도구를 이름으로 등록하고 찾아 실행할 수 있게 합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""JSON Schema validation and tool registry loading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.config.models import ToolDefinition, ToolPolicy
from app.core.errors import ToolArgInvalid, ToolNotFound
from app.tools.base import Tool, ToolSpec

# re.compile()의 반환값을 _CONTROL_CHARS에 대입합니다.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")
# _WEB_SEARCH_SCHEMA에 딕셔너리(키와 값의 쌍)을 대입합니다.
_WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "maxLength": 300},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 8},
    },
}
# dict()의 반환값을 _DOC_SEARCH_SCHEMA에 대입합니다.
_DOC_SEARCH_SCHEMA = dict(_WEB_SEARCH_SCHEMA)
# _FETCH_URL_SCHEMA에 딕셔너리(키와 값의 쌍)을 대입합니다.
_FETCH_URL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["url"],
    "properties": {
        "url": {"type": "string", "maxLength": 2048, "pattern": "^https?://"},
    },
}
# _STATIC_SCHEMAS에 딕셔너리(키와 값의 쌍)을 대입합니다.
_STATIC_SCHEMAS: dict[str, dict[str, Any]] = {
    "web_search": _WEB_SEARCH_SCHEMA,
    "doc_search": _DOC_SEARCH_SCHEMA,
    "fetch_url": _FETCH_URL_SCHEMA,
}


# schema_for_definition(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: defn.
# 반환 타입 힌트: dict[str, Any].
def schema_for_definition(defn: ToolDefinition) -> dict[str, Any]:
    # _STATIC_SCHEMAS.get()의 반환값을 static에 대입합니다.
    static = _STATIC_SCHEMAS.get(defn.name)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: static is not None.
    if static is not None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return static
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: defn.name in {'open_app', 'close_app'}.
    if defn.name in {"open_app", "close_app"}:
        # sorted()의 반환값을 apps에 대입합니다.
        apps = sorted((defn.app_map or {}).keys())
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["app"],
            "properties": {
                "app": ({"type": "string", "maxLength": 256}
                        if defn.name == "open_app" else {"type": "string", "enum": apps}),
                **({"force": {"type": "boolean"}} if defn.name == "close_app" else {}),
            },
        }
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: defn.name == 'open_folder'.
    if defn.name == "open_folder":
        # sorted()의 반환값을 roots에 대입합니다.
        roots = sorted(defn.allowed_roots or [])
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["root", "relative_path"],
            "properties": {
                "root": {"type": "string", "enum": roots},
                "relative_path": {"type": "string", "maxLength": 512},
            },
        }
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: defn.name == 'open_url'.
    if defn.name == "open_url":
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return dict(_FETCH_URL_SCHEMA)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: defn.name == 'create_file'.
    if defn.name == "create_file":
        # sorted()의 반환값을 roots에 대입합니다.
        roots = sorted(defn.allowed_roots or [])
        # 오른쪽 식을 계산한 값을 max_content에 대입합니다.
        max_content = defn.max_content_bytes or 200_000
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["root", "relative_path", "content"],
            "properties": {
                "root": {"type": "string", "enum": roots},
                "relative_path": {"type": "string", "maxLength": 512},
                "content": {"type": "string", "maxLength": max_content},
                "overwrite": {"type": "boolean"},
            },
        }
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return {"type": "object", "additionalProperties": False}


# ToolRegistry: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class ToolRegistry:
    # tools: dict[str, Tool] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tools: dict[str, Tool]
    # specs: dict[str, ToolSpec] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    specs: dict[str, ToolSpec]

    # get(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: name.
    # 반환 타입 힌트: Tool.
    def get(self, name: str) -> Tool:
        # self.tools.get()의 반환값을 tool에 대입합니다.
        tool = self.tools.get(name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool is None.
        if tool is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolNotFound(f"등록되지 않은 도구입니다: {name}")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tool

    # enabled_specs(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: tuple[ToolSpec, ...].
    def enabled_specs(self) -> tuple[ToolSpec, ...]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return tuple(spec for spec in self.specs.values() if spec.enabled)

    # llm_tool_specs(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: tuple[ToolSpec, ...].
    def llm_tool_specs(self) -> tuple[ToolSpec, ...]:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.enabled_specs()


# validate_tool_args(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: schema, args.
# 반환 타입 힌트: dict[str, Any].
def validate_tool_args(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(args, dict).
    if not isinstance(args, dict):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("도구 인자는 객체여야 합니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: schema.get('additionalProperties') is
    # False.
    if schema.get("additionalProperties") is False:
        # set()의 반환값을 allowed에 대입합니다.
        allowed = set(schema.get("properties", {}))
        # 오른쪽 식을 계산한 값을 unknown에 대입합니다.
        unknown = set(args) - allowed
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: unknown.
        if unknown:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"알 수 없는 인자: {sorted(unknown)}")
    # schema.get()의 반환값을 required에 대입합니다.
    required = schema.get("required", [])
    # 오른쪽 식을 계산한 값을 missing에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    missing = [name for name in required if name not in args]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: missing.
    if missing:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid(f"필수 인자가 없습니다: {missing}")

    # normalized에 딕셔너리(키와 값의 쌍)을 대입합니다.
    normalized: dict[str, Any] = {}
    # schema.get()의 반환값을 properties에 대입합니다.
    properties = schema.get("properties", {})
    # for 반복문: 대상의 항목을 하나씩 (key, value)에 대입하며 아래 블록을 실행합니다.
    for key, value in args.items():
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key not in properties.
        if key not in properties:
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 오른쪽 식을 계산한 값을 prop에 대입합니다.
        prop = properties[key]
        # _validate_property()의 반환값을 normalized[key]에 대입합니다.
        normalized[key] = _validate_property(key, value, prop)
    # for 반복문: 대상의 항목을 하나씩 key에 대입하며 아래 블록을 실행합니다.
    for key in required:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key not in normalized and key in args.
        if key not in normalized and key in args:
            # _validate_property()의 반환값을 normalized[key]에 대입합니다.
            normalized[key] = _validate_property(key, args[key], properties[key])
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return normalized


# _validate_property(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: name, value, schema.
# 반환 타입 힌트: 어떤 타입이든 허용(Any).
def _validate_property(name: str, value: Any, schema: dict[str, Any]) -> Any:
    # schema.get()의 반환값을 expected에 대입합니다.
    expected = schema.get("type")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: expected == 'string'.
    if expected == "string":
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, str).
        if not isinstance(value, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name}은 문자열이어야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _CONTROL_CHARS.search(value).
        if _CONTROL_CHARS.search(value):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name}에 제어 문자가 포함되어 있습니다.")
        # schema.get()의 반환값을 max_len에 대입합니다.
        max_len = schema.get("maxLength")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: max_len is not None and len(value) >
        # max_len.
        if max_len is not None and len(value) > max_len:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name} 길이가 {max_len}을 초과했습니다.")
        # schema.get()의 반환값을 pattern에 대입합니다.
        pattern = schema.get("pattern")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: pattern is not None and
        # re.fullmatch(pattern, value) is
        # None.
        if pattern is not None and re.fullmatch(pattern, value) is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name} 형식이 올바르지 않습니다.")
        # schema.get()의 반환값을 enum에 대입합니다.
        enum = schema.get("enum")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: enum is not None and value not in
        # enum.
        if enum is not None and value not in enum:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name} 값이 허용 목록에 없습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return value
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: expected == 'integer'.
    if expected == "integer":
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, int) or
        # isinstance(value, bool).
        if not isinstance(value, int) or isinstance(value, bool):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name}은 정수여야 합니다.")
        # schema.get()의 반환값을 minimum에 대입합니다.
        minimum = schema.get("minimum")
        # schema.get()의 반환값을 maximum에 대입합니다.
        maximum = schema.get("maximum")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: minimum is not None and value <
        # minimum.
        if minimum is not None and value < minimum:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name}은 {minimum} 이상이어야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: maximum is not None and value >
        # maximum.
        if maximum is not None and value > maximum:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name}은 {maximum} 이하여야 합니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return value
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: expected == 'boolean'.
    if expected == "boolean":
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, bool).
        if not isinstance(value, bool):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"{name}은 boolean이어야 합니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return value
    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
    raise ToolArgInvalid(f"지원하지 않는 스키마 타입: {expected}")


# _to_spec(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: defn.
# 반환 타입 힌트: ToolSpec.
def _to_spec(defn: ToolDefinition) -> ToolSpec:
    # schema_for_definition()의 반환값을 schema에 대입합니다.
    schema = schema_for_definition(defn)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ToolSpec(
        name=defn.name,
        description=defn.description,
        json_schema=schema,
        risk=defn.risk,
        capabilities=frozenset(defn.capabilities),
        execution_mode=defn.execution_mode,
        idempotent=defn.idempotent,
        enabled=defn.enabled,
        untrusted_output=defn.untrusted_output,
        timeout_s=defn.timeout_s,
        phase=defn.phase,
    )


# spec_from_definition(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: defn.
# 반환 타입 힌트: ToolSpec.
def spec_from_definition(defn: ToolDefinition) -> ToolSpec:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return _to_spec(defn)


# build_registry(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: policy, phase, implementations.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: ToolRegistry.
def build_registry(
    policy: ToolPolicy,
    *,
    phase: int,
    implementations: dict[str, Tool],
) -> ToolRegistry:
    # tools에 딕셔너리(키와 값의 쌍)을 대입합니다.
    tools: dict[str, Tool] = {}
    # specs에 딕셔너리(키와 값의 쌍)을 대입합니다.
    specs: dict[str, ToolSpec] = {}
    # for 반복문: 대상의 항목을 하나씩 defn에 대입하며 아래 블록을 실행합니다.
    for defn in policy.tools:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not defn.enabled or defn.phase >
        # phase.
        if not defn.enabled or defn.phase > phase:
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # implementations.get()의 반환값을 impl에 대입합니다.
        impl = implementations.get(defn.name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: impl is None.
        if impl is None:
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # _to_spec()의 반환값을 spec에 대입합니다.
        spec = _to_spec(defn)
        # 오른쪽 식을 계산한 값을 specs[defn.name]에 대입합니다.
        specs[defn.name] = spec
        # 오른쪽 식을 계산한 값을 tools[defn.name]에 대입합니다.
        tools[defn.name] = impl
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ToolRegistry(tools=tools, specs=specs)


# validate_structured_output(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tool_name, data.
# 반환 타입 힌트: 별도 결과 없음(None).
def validate_structured_output(tool_name: str, data: dict[str, Any]) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'web_search'.
    if tool_name == "web_search":
        # _validate_web_search()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_web_search(data)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'doc_search'.
    elif tool_name == "doc_search":
        # _validate_doc_search()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_doc_search(data)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'fetch_url'.
    elif tool_name == "fetch_url":
        # _validate_fetch_url()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_fetch_url(data)


# _validate_web_search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_web_search(data: dict[str, Any]) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'query' not in data or 'hits' not in data.
    if "query" not in data or "hits" not in data:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("web_search 출력에 query와 hits가 필요합니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(data['hits'], list).
    if not isinstance(data["hits"], list):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("web_search hits는 배열이어야 합니다.")
    # for 반복문: 대상의 항목을 하나씩 hit에 대입하며 아래 블록을 실행합니다.
    for hit in data["hits"]:
        # for 반복문: 대상의 항목을 하나씩 key에 대입하며 아래 블록을 실행합니다.
        for key in ("title", "url", "snippet", "fetched_at"):
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key not in hit.
            if key not in hit:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ToolArgInvalid(f"web_search hit에 {key}가 필요합니다.")


# _validate_doc_search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_doc_search(data: dict[str, Any]) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'query' not in data or 'hits' not in data.
    if "query" not in data or "hits" not in data:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("doc_search 출력에 query와 hits가 필요합니다.")
    # for 반복문: 대상의 항목을 하나씩 hit에 대입하며 아래 블록을 실행합니다.
    for hit in data["hits"]:
        # for 반복문: 대상의 항목을 하나씩 key에 대입하며 아래 블록을 실행합니다.
        for key in (
            "chunk_id",
            "doc_id",
            "relative_path",
            "ordinal",
            "text",
            "start_char",
            "end_char",
            "transfer_class",
            "score",
        ):
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key not in hit.
            if key not in hit:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ToolArgInvalid(f"doc_search hit에 {key}가 필요합니다.")


# _validate_fetch_url(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_fetch_url(data: dict[str, Any]) -> None:
    # for 반복문: 대상의 항목을 하나씩 key에 대입하며 아래 블록을 실행합니다.
    for key in (
        "requested_url",
        "final_url",
        "title",
        "content",
        "content_type",
        "fetched_at",
        "truncated",
    ):
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: key not in data.
        if key not in data:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"fetch_url 출력에 {key}가 필요합니다.")
