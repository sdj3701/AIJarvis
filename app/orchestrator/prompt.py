"""Versioned Phase 1 prompt assembly with deterministic context compaction."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config.models import ContextSettings
from app.core.context import CancelToken
from app.core.errors import PromptTooLong
from app.llm.base import Message

_VERSION_PATTERN = re.compile(r"^<!--\s*version:\s*([0-9]+)\s*-->$")
_DEFAULT_PROMPT_PATH = Path(__file__).with_name("prompts") / "system_core.md"


class TokenCounter(Protocol):
    def count_tokens(self, messages: Sequence[Message]) -> int: ...


@dataclass(frozen=True, slots=True)
class PromptPlan:
    messages: tuple[Message, ...]
    prompt_version: str
    input_tokens: int
    history_tokens: int
    history_cap: int
    compressed: bool
    compressed_turns: int


class ExtractiveHistoryCompressor:
    """Collapse old turns locally; no extra model request or external state is used."""

    def compress(self, turns: Sequence[Sequence[Message]]) -> str:
        lines = [f"[이전 대화 {len(turns)}턴 압축]"]
        for turn in turns:
            for message in turn:
                label = "사용자" if message.role == "user" else "자비스"
                content = " ".join(message.content.split())
                if len(content) > 240:
                    content = content[:237] + "..."
                lines.append(f"{label}: {content}")
        return "\n".join(lines)


class PromptAssembler:
    """Build system → compacted history → current-user messages in fixed order."""

    def __init__(
        self,
        counter: TokenCounter,
        context: ContextSettings,
        *,
        prompt_path: Path = _DEFAULT_PROMPT_PATH,
        compressor: ExtractiveHistoryCompressor | None = None,
    ) -> None:
        self._counter = counter
        self._context = context
        self._system_text, self._version = _load_prompt(prompt_path)
        self._compressor = compressor or ExtractiveHistoryCompressor()

    @property
    def prompt_version(self) -> str:
        return self._version

    def build(
        self,
        *,
        current_user_text: str,
        history: Sequence[Message] = (),
        cancel: CancelToken | None = None,
    ) -> PromptPlan:
        if not isinstance(current_user_text, str) or not current_user_text.strip():
            raise ValueError("현재 사용자 발화는 비어 있을 수 없습니다")
        if cancel is not None:
            cancel.raise_if_cancelled()

        turns = _history_turns(history)
        system = Message("system", self._system_text)
        current = Message("user", current_user_text)
        system_tokens = self._count((system,))
        current_tokens = self._count((current,))
        fixed_tokens = system_tokens + current_tokens + self._context.reserve_output_tokens
        if fixed_tokens > self._context.max_input_tokens:
            raise PromptTooLong(
                "입력이 너무 깁니다. 내용을 나누어 다시 입력하세요.",
                {
                    "system_tokens": system_tokens,
                    "current_tokens": current_tokens,
                    "max_input_tokens": self._context.max_input_tokens,
                },
            )

        available = (
            self._context.max_input_tokens
            - system_tokens
            - self._context.reserve_output_tokens
        )
        history_cap = int(available * self._context.history_share)
        protected_turn_count = min(self._context.keep_recent_turns, len(turns))
        protected_turns = turns[-protected_turn_count:] if protected_turn_count else []
        old_turns = turns[:-protected_turn_count] if protected_turn_count else turns
        protected = tuple(message for turn in protected_turns for message in turn)
        protected_tokens = self._count(protected)
        remaining_total = self._context.max_input_tokens - fixed_tokens - protected_tokens
        if remaining_total < 0:
            raise PromptTooLong(
                "최근 대화와 현재 입력이 컨텍스트 한도를 넘었습니다. /clear 후 다시 입력하세요.",
                {
                    "protected_turns": protected_turn_count,
                    "protected_tokens": protected_tokens,
                    "max_input_tokens": self._context.max_input_tokens,
                },
            )

        history_messages: tuple[Message, ...]
        compressed = False
        compressed_turns = 0
        full_history = tuple(history)
        full_history_tokens = self._count(full_history)
        if full_history_tokens <= min(history_cap, self._context.max_input_tokens - fixed_tokens):
            history_messages = full_history
        else:
            compressed = bool(old_turns)
            compressed_turns = len(old_turns)
            summary_cap = min(max(0, history_cap - protected_tokens), remaining_total)
            summary = self._summary_message(old_turns, token_cap=summary_cap)
            history_messages = (() if summary is None else (summary,)) + protected

        messages = (system, *history_messages, current)
        input_tokens = self._count(messages)
        if input_tokens + self._context.reserve_output_tokens > self._context.max_input_tokens:
            raise PromptTooLong(
                "프롬프트가 컨텍스트 한도를 초과했습니다. /clear 후 다시 입력하세요."
            )
        if cancel is not None:
            cancel.raise_if_cancelled()
        return PromptPlan(
            messages=messages,
            prompt_version=self._version,
            input_tokens=input_tokens,
            history_tokens=self._count(history_messages),
            history_cap=history_cap,
            compressed=compressed,
            compressed_turns=compressed_turns,
        )

    def _summary_message(
        self,
        turns: Sequence[Sequence[Message]],
        *,
        token_cap: int,
    ) -> Message | None:
        if not turns or token_cap <= 0:
            return None
        text = self._compressor.compress(turns)
        candidate = Message("assistant", text)
        if self._count((candidate,)) <= token_cap:
            return candidate

        low = 0
        high = len(text)
        best: Message | None = None
        while low <= high:
            middle = (low + high) // 2
            suffix = "..." if middle < len(text) else ""
            attempt = Message("assistant", text[:middle].rstrip() + suffix)
            if self._count((attempt,)) <= token_cap:
                best = attempt
                low = middle + 1
            else:
                high = middle - 1
        return best if best is not None and best.content else None

    def _count(self, messages: Sequence[Message]) -> int:
        return self._counter.count_tokens(messages) if messages else 0


def _load_prompt(path: Path) -> tuple[str, str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("시스템 프롬프트 파일을 읽을 수 없습니다") from error
    lines = text.splitlines()
    if not lines:
        raise ValueError("시스템 프롬프트가 비어 있습니다")
    match = _VERSION_PATTERN.fullmatch(lines[0])
    if match is None:
        raise ValueError("시스템 프롬프트 첫 줄에 정수 version이 필요합니다")
    if not text.strip():
        raise ValueError("시스템 프롬프트가 비어 있습니다")
    return text, match.group(1)


def _history_turns(history: Sequence[Message]) -> list[tuple[Message, Message]]:
    if len(history) % 2 != 0:
        raise ValueError("완료된 히스토리는 user/assistant 쌍이어야 합니다")
    turns: list[tuple[Message, Message]] = []
    for index in range(0, len(history), 2):
        user = history[index]
        assistant = history[index + 1]
        if user.role != "user" or assistant.role != "assistant":
            raise ValueError("히스토리 메시지 순서는 user/assistant여야 합니다")
        turns.append((user, assistant))
    return turns
