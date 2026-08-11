"""Canonical JSON and tool-bound argument hashes."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def canonical_json(obj: Any) -> bytes:
    """Serialize supported JSON values deterministically as normalized UTF-8."""
    normalized = _normalize(obj)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def args_hash(tool_name: str, normalized_args: dict[str, Any]) -> str:
    """Bind normalized arguments to a specific allowlisted tool name."""
    if not _TOOL_NAME_PATTERN.fullmatch(tool_name):
        raise ValueError("tool_name must be lowercase ASCII with optional underscores")
    payload = tool_name.encode("utf-8") + b"\x00" + canonical_json(normalized_args)
    return hashlib.sha256(payload).hexdigest()


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        raise TypeError("float values are forbidden in canonical policy JSON")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list | tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("canonical JSON keys collide after NFC normalization")
            normalized[normalized_key] = _normalize(item)
        return normalized
    raise TypeError(f"unsupported canonical JSON type: {type(value).__name__}")
