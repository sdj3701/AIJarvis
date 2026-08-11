"""Tests for canonical JSON and tool-bound argument hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.canonical import args_hash, canonical_json

pytestmark = pytest.mark.phase0


def test_canonical_json_sorts_keys_and_uses_compact_utf8() -> None:
    first = canonical_json({"한글": [True, None, 3], "a": "값"})
    second = canonical_json({"a": "값", "한글": [True, None, 3]})

    assert first == second
    assert first == '{"a":"값","한글":[true,null,3]}'.encode()


def test_canonical_json_normalizes_unicode_to_nfc() -> None:
    decomposed = "e\u0301"
    composed = "é"

    assert canonical_json({decomposed: decomposed}) == canonical_json({composed: composed})


def test_canonical_json_rejects_keys_that_collide_after_normalization() -> None:
    with pytest.raises(ValueError):
        canonical_json({"e\u0301": 1, "é": 2})


@pytest.mark.parametrize("value", [0.1, {"nested": [1, 2.0]}, float("nan")])
def test_canonical_json_rejects_float_everywhere(value: object) -> None:
    with pytest.raises(TypeError):
        canonical_json(value)


@pytest.mark.parametrize("value", [{1: "non-string-key"}, Path("already-normalized")])
def test_canonical_json_rejects_unsupported_types(value: object) -> None:
    with pytest.raises(TypeError):
        canonical_json(value)


def test_args_hash_includes_tool_name_and_null_separator() -> None:
    arguments = {"path": "D:\\Jarvis\\docs\\note.md", "overwrite": False}
    expected = hashlib.sha256(
        b"create_file\x00" + canonical_json(arguments)
    ).hexdigest()

    assert args_hash("create_file", arguments) == expected
    assert args_hash("create_file", arguments) != args_hash("other_tool", arguments)


@pytest.mark.parametrize("tool_name", ["", "OpenApp", "has-dash", "nul\x00name"])
def test_args_hash_rejects_invalid_tool_name(tool_name: str) -> None:
    with pytest.raises(ValueError):
        args_hash(tool_name, {})
