"""Pure wake-word matching helpers for false-wake reduction and inline commands."""

from __future__ import annotations

import re
from typing import Literal

WakeMatchKind = Literal["none", "standalone", "prefix"]

_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]")


def normalize_spoken_command(text: str) -> str:
    return _NON_WORD.sub("", text).casefold()


def wake_match_kind(text: str, wake_word: str) -> WakeMatchKind:
    normalized = normalize_spoken_command(text)
    wake = normalize_spoken_command(wake_word)
    if not normalized or not wake:
        return "none"
    if normalized == wake:
        return "standalone"
    if normalized.startswith(wake):
        return "prefix"
    return "none"


def _strip_one_leading_wake(text: str, wake_word: str) -> str:
    stripped = text.strip()
    wake = wake_word.strip()
    if not stripped or not wake:
        return stripped
    kind = wake_match_kind(stripped, wake)
    if kind == "none":
        return stripped
    if kind == "standalone":
        return ""
    pattern = re.compile(
        rf"^[\s.,!?·]*{re.escape(wake)}(?:\s+|[\s.,!?·]+)",
        re.IGNORECASE,
    )
    remainder = pattern.sub("", stripped, count=1).strip()
    if remainder:
        return remainder
    compact_wake = normalize_spoken_command(wake)
    tokens = stripped.split()
    consumed = ""
    index = 0
    while index < len(tokens) and normalize_spoken_command(consumed) != compact_wake:
        consumed += tokens[index]
        index += 1
    if normalize_spoken_command(consumed) == compact_wake:
        return " ".join(tokens[index:]).strip()
    return stripped


def strip_leading_wake_word(text: str, wake_word: str) -> str:
    """Remove one or more leading wake words; empty when only wake remains."""
    current = text.strip()
    if not current:
        return ""
    # Guard against "자비스 자비스 …" artifacts from wake grammar or prompt bias.
    for _ in range(4):
        kind = wake_match_kind(current, wake_word)
        if kind == "none":
            return current
        if kind == "standalone":
            return ""
        nxt = _strip_one_leading_wake(current, wake_word)
        if nxt == current:
            return current
        current = nxt
    return current
