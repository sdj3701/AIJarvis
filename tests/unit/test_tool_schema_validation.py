"""Tests for search tool JSON schema and structured output contracts."""

from __future__ import annotations

import pytest

from app.core.errors import ToolArgInvalid
from app.tools.registry import validate_structured_output, validate_tool_args

pytestmark = pytest.mark.phase3

WEB_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "maxLength": 300},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 8},
    },
}


def test_search_output_contracts() -> None:
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


def test_unknown_arg_rejected() -> None:
    with pytest.raises(ToolArgInvalid):
        validate_tool_args(WEB_SCHEMA, {"query": "x", "evil": True})


def test_control_chars_rejected() -> None:
    with pytest.raises(ToolArgInvalid):
        validate_tool_args(WEB_SCHEMA, {"query": "bad\x00query"})


def test_open_and_close_app_schema_validation() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["app"],
        "properties": {
            "app": {"type": "string", "enum": ["calc", "notepad"]},
        },
    }
    # Valid app
    assert validate_tool_args(schema, {"app": "notepad"}) == {"app": "notepad"}

    # Invalid unlisted app
    with pytest.raises(ToolArgInvalid):
        validate_tool_args(schema, {"app": "chrome"})

    # Missing required 'app'
    with pytest.raises(ToolArgInvalid):
        validate_tool_args(schema, {})

    # Unknown parameter injection
    with pytest.raises(ToolArgInvalid):
        validate_tool_args(schema, {"app": "notepad", "extra_arg": "hack"})


def test_create_file_schema_validation() -> None:
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
    valid_args = {
        "root": "notes",
        "relative_path": "meeting.txt",
        "content": "hello world",
        "overwrite": True,
    }
    assert validate_tool_args(schema, valid_args) == valid_args

    # Unlisted root
    with pytest.raises(ToolArgInvalid):
        validate_tool_args(schema, {**valid_args, "root": "system32"})

    # Content length exceeded
    with pytest.raises(ToolArgInvalid):
        validate_tool_args(schema, {**valid_args, "content": "x" * 1001})

    # Non-boolean overwrite
    with pytest.raises(ToolArgInvalid):
        validate_tool_args(schema, {**valid_args, "overwrite": "yes"})

