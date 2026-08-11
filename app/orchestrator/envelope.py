"""Untrusted content envelope helpers for LLM prompt injection mitigation."""

from __future__ import annotations

from datetime import datetime


def escape_untrusted_body(text: str) -> str:
    """Escape envelope-like tags inside untrusted body text."""
    escaped = text.replace("</untrusted_content>", "&lt;/untrusted_content&gt;")
    return escaped.replace("<untrusted_content", "&lt;untrusted_content")


def wrap_untrusted_content(
    *,
    source: str,
    source_kind: str,
    fetched_at: datetime,
    body: str,
    chunk: str | None = None,
) -> str:
    attrs = (
        f'source="{_escape_attr(source)}" '
        f'source_kind="{_escape_attr(source_kind)}" '
        f'fetched_at="{fetched_at.isoformat(timespec="seconds")}" '
        'trust="none"'
    )
    if chunk is not None:
        attrs += f' chunk="{_escape_attr(chunk)}"'
    safe_body = escape_untrusted_body(body)
    return f"<untrusted_content {attrs}>\n{safe_body}\n</untrusted_content>"


def _escape_attr(value: str) -> str:
    return value.replace('"', "&quot;")
