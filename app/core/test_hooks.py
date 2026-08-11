"""Development-only abrupt-exit hooks used by the Phase 1 crash gate."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from decimal import Decimal

from app.core.context import RequestContext
from app.llm.base import LLMResponse, LLMUsage, Message, ToolSpec

CRASH_POINTS = frozenset(
    {"user.input", "llm.request", "llm.response", "memory.write", "session.checkpoint"}
)


class CrashTestHook:
    """Terminate only when both development mode and an exact allowlisted point are set."""

    def __init__(
        self,
        target: str | None,
        *,
        enabled: bool,
        terminate: Callable[[int], None] = os._exit,
    ) -> None:
        self._target = target if target in CRASH_POINTS else None
        self._enabled = enabled and self._target is not None
        self._terminate = terminate

    @classmethod
    def from_environment(cls, *, dev_mode: bool) -> CrashTestHook:
        return cls(os.environ.get("JARVIS_TEST_KILL_AFTER"), enabled=dev_mode)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def after(self, point: str) -> None:
        if self._enabled and point == self._target:
            self._terminate(97)


class CrashTestLLMClient:
    """Deterministic eventing fake selected only by the guarded crash-test environment."""

    name = "crash-test-fake"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        timeout_s: float,
        ctx: RequestContext,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        del tools, timeout_s, temperature, max_output_tokens
        ctx.cancel.raise_if_cancelled()
        prompt_tokens = self.count_tokens(messages)
        prompt_version = "1" if messages and messages[0].role == "system" else "unversioned"
        ctx.events.emit(
            "llm.request",
            {
                "model": self.name,
                "attempt": 1,
                "prompt_tokens_est": prompt_tokens,
                "prompt_version": prompt_version,
                "tool_count": 0,
                "memory_record_ids": [],
            },
        )
        usage = LLMUsage(prompt_tokens, 4, Decimal("0"), 1)
        response = LLMResponse("테스트 응답", (), usage, self.name, "stop")
        ctx.events.emit(
            "llm.response",
            {
                "model": self.name,
                "finish_reason": "stop",
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cost_usd": "0",
                "latency_ms": 1,
                "tool_call_names": [],
            },
        )
        return response

    def count_tokens(self, messages: Sequence[Message]) -> int:
        return sum(len(message.content) for message in messages)
