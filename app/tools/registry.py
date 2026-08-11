"""JSON Schema validation and tool registry loading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.config.models import ToolDefinition, ToolPolicy
from app.core.errors import ToolArgInvalid, ToolNotFound
from app.tools.base import Tool, ToolSpec

_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")
_WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "maxLength": 300},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 8},
    },
}
_DOC_SEARCH_SCHEMA = dict(_WEB_SEARCH_SCHEMA)
_FETCH_URL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["url"],
    "properties": {
        "url": {"type": "string", "maxLength": 2048, "pattern": "^https?://"},
    },
}
_STATIC_SCHEMAS: dict[str, dict[str, Any]] = {
    "web_search": _WEB_SEARCH_SCHEMA,
    "doc_search": _DOC_SEARCH_SCHEMA,
    "fetch_url": _FETCH_URL_SCHEMA,
}


def schema_for_definition(defn: ToolDefinition) -> dict[str, Any]:
    static = _STATIC_SCHEMAS.get(defn.name)
    if static is not None:
        return static
    if defn.name == "open_app":
        apps = sorted((defn.app_map or {}).keys())
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["app"],
            "properties": {
                "app": {"type": "string", "enum": apps},
            },
        }
    if defn.name == "open_folder":
        roots = sorted(defn.allowed_roots or [])
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["root", "relative_path"],
            "properties": {
                "root": {"type": "string", "enum": roots},
                "relative_path": {"type": "string", "maxLength": 512},
            },
        }
    if defn.name == "open_url":
        return dict(_FETCH_URL_SCHEMA)
    if defn.name == "create_file":
        roots = sorted(defn.allowed_roots or [])
        max_content = defn.max_content_bytes or 200_000
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
    return {"type": "object", "additionalProperties": False}


@dataclass
class ToolRegistry:
    tools: dict[str, Tool]
    specs: dict[str, ToolSpec]

    def get(self, name: str) -> Tool:
        tool = self.tools.get(name)
        if tool is None:
            raise ToolNotFound(f"등록되지 않은 도구입니다: {name}")
        return tool

    def enabled_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(spec for spec in self.specs.values() if spec.enabled)

    def llm_tool_specs(self) -> tuple[ToolSpec, ...]:
        return self.enabled_specs()


def validate_tool_args(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolArgInvalid("도구 인자는 객체여야 합니다.")
    if schema.get("additionalProperties") is False:
        allowed = set(schema.get("properties", {}))
        unknown = set(args) - allowed
        if unknown:
            raise ToolArgInvalid(f"알 수 없는 인자: {sorted(unknown)}")
    required = schema.get("required", [])
    missing = [name for name in required if name not in args]
    if missing:
        raise ToolArgInvalid(f"필수 인자가 없습니다: {missing}")

    normalized: dict[str, Any] = {}
    properties = schema.get("properties", {})
    for key, value in args.items():
        if key not in properties:
            continue
        prop = properties[key]
        normalized[key] = _validate_property(key, value, prop)
    for key in required:
        if key not in normalized and key in args:
            normalized[key] = _validate_property(key, args[key], properties[key])
    return normalized


def _validate_property(name: str, value: Any, schema: dict[str, Any]) -> Any:
    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            raise ToolArgInvalid(f"{name}은 문자열이어야 합니다.")
        if _CONTROL_CHARS.search(value):
            raise ToolArgInvalid(f"{name}에 제어 문자가 포함되어 있습니다.")
        max_len = schema.get("maxLength")
        if max_len is not None and len(value) > max_len:
            raise ToolArgInvalid(f"{name} 길이가 {max_len}을 초과했습니다.")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise ToolArgInvalid(f"{name} 형식이 올바르지 않습니다.")
        enum = schema.get("enum")
        if enum is not None and value not in enum:
            raise ToolArgInvalid(f"{name} 값이 허용 목록에 없습니다.")
        return value
    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolArgInvalid(f"{name}은 정수여야 합니다.")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ToolArgInvalid(f"{name}은 {minimum} 이상이어야 합니다.")
        if maximum is not None and value > maximum:
            raise ToolArgInvalid(f"{name}은 {maximum} 이하여야 합니다.")
        return value
    if expected == "boolean":
        if not isinstance(value, bool):
            raise ToolArgInvalid(f"{name}은 boolean이어야 합니다.")
        return value
    raise ToolArgInvalid(f"지원하지 않는 스키마 타입: {expected}")


def _to_spec(defn: ToolDefinition) -> ToolSpec:
    schema = schema_for_definition(defn)
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


def spec_from_definition(defn: ToolDefinition) -> ToolSpec:
    return _to_spec(defn)


def build_registry(
    policy: ToolPolicy,
    *,
    phase: int,
    implementations: dict[str, Tool],
) -> ToolRegistry:
    tools: dict[str, Tool] = {}
    specs: dict[str, ToolSpec] = {}
    for defn in policy.tools:
        if not defn.enabled or defn.phase > phase:
            continue
        impl = implementations.get(defn.name)
        if impl is None:
            continue
        spec = _to_spec(defn)
        specs[defn.name] = spec
        tools[defn.name] = impl
    return ToolRegistry(tools=tools, specs=specs)


def validate_structured_output(tool_name: str, data: dict[str, Any]) -> None:
    if tool_name == "web_search":
        _validate_web_search(data)
    elif tool_name == "doc_search":
        _validate_doc_search(data)
    elif tool_name == "fetch_url":
        _validate_fetch_url(data)


def _validate_web_search(data: dict[str, Any]) -> None:
    if "query" not in data or "hits" not in data:
        raise ToolArgInvalid("web_search 출력에 query와 hits가 필요합니다.")
    if not isinstance(data["hits"], list):
        raise ToolArgInvalid("web_search hits는 배열이어야 합니다.")
    for hit in data["hits"]:
        for key in ("title", "url", "snippet", "fetched_at"):
            if key not in hit:
                raise ToolArgInvalid(f"web_search hit에 {key}가 필요합니다.")


def _validate_doc_search(data: dict[str, Any]) -> None:
    if "query" not in data or "hits" not in data:
        raise ToolArgInvalid("doc_search 출력에 query와 hits가 필요합니다.")
    for hit in data["hits"]:
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
            if key not in hit:
                raise ToolArgInvalid(f"doc_search hit에 {key}가 필요합니다.")


def _validate_fetch_url(data: dict[str, Any]) -> None:
    for key in (
        "requested_url",
        "final_url",
        "title",
        "content",
        "content_type",
        "fetched_at",
        "truncated",
    ):
        if key not in data:
            raise ToolArgInvalid(f"fetch_url 출력에 {key}가 필요합니다.")
