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
