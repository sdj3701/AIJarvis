"""Parse CLI and simple natural-language tool intents."""

from __future__ import annotations

import re

from app.llm.base import ToolCall

_OPEN_APP = re.compile(r"^/open_app(?:\s+(?P<app>\S+))?$", re.I)
_OPEN = re.compile(r"^/open(?:\s+(?P<app>\S+))?$", re.I)
_OPEN_FOLDER = re.compile(
    r"^/open_folder(?:\s+(?P<root>\S+)(?:\s+(?P<relative>.+))?)?$",
    re.I,
)
_OPEN_URL = re.compile(r"^/open_url(?:\s+(?P<url>\S+))?$", re.I)
_CREATE_FILE = re.compile(
    r"^/create_file(?:\s+(?P<root>\S+)\s+(?P<relative>\S+)(?:\s+(?P<content>.+))?)?$",
    re.I,
)
_KO_NOTEPAD = re.compile(r"메모장")
_KO_CALC = re.compile(r"계산기")


def parse_tool_command(text: str) -> ToolCall | None:
    stripped = text.strip()
    if not stripped:
        return None

    match = _OPEN_APP.match(stripped) or _OPEN.match(stripped)
    if match is not None:
        app = (match.group("app") or "").strip().lower()
        if not app:
            return None
        return ToolCall(id="cli_open_app", name="open_app", arguments={"app": app})

    match = _OPEN_FOLDER.match(stripped)
    if match is not None:
        root = (match.group("root") or "").strip()
        relative = (match.group("relative") or ".").strip()
        if not root:
            return None
        return ToolCall(
            id="cli_open_folder",
            name="open_folder",
            arguments={"root": root, "relative_path": relative},
        )

    match = _OPEN_URL.match(stripped)
    if match is not None:
        url = (match.group("url") or "").strip()
        if not url:
            return None
        return ToolCall(id="cli_open_url", name="open_url", arguments={"url": url})

    match = _CREATE_FILE.match(stripped)
    if match is not None:
        root = (match.group("root") or "").strip()
        relative = (match.group("relative") or "").strip()
        content = match.group("content") or ""
        if not root or not relative:
            return None
        return ToolCall(
            id="cli_create_file",
            name="create_file",
            arguments={"root": root, "relative_path": relative, "content": content},
        )

    return parse_simple_korean_intent(stripped)


def parse_simple_korean_intent(text: str) -> ToolCall | None:
    lowered = text.strip()
    if "검색" in lowered or "찾아" in lowered:
        return None
    if _KO_NOTEPAD.search(lowered) and any(word in lowered for word in ("열", "실행", "켜")):
        return ToolCall(id="nl_open_app", name="open_app", arguments={"app": "notepad"})
    if _KO_CALC.search(lowered) and any(word in lowered for word in ("열", "실행", "켜")):
        return ToolCall(id="nl_open_app", name="open_app", arguments={"app": "calc"})
    return None
