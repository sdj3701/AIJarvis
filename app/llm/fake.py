"""Deterministic scripted LLM client for offline tests."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.core.context import RequestContext
from app.core.errors import LLMBadResponse
from app.llm.base import (
    LLMResponse,
    LLMUsage,
    Message,
    ToolCall,
    ToolSpec,
    validate_request_limits,
)

ScriptItem = LLMResponse | Exception
ZERO_USAGE = LLMUsage(0, 0, Decimal("0"), 0)


class FakeLLMClient:
    """Return queued responses and record every prompt without network access."""

    name = "fake"

    def __init__(self, *, model: str = "fake-model") -> None:
        if not model:
            raise ValueError("fake model must be non-empty")
        self.model = model
        self.script: list[ScriptItem] = []
        self.calls: list[list[Message]] = []

    def reply(self, text: str, *, usage: LLMUsage | None = None) -> FakeLLMClient:
        self.script.append(
            LLMResponse(
                text=text,
                tool_calls=(),
                usage=usage or ZERO_USAGE,
                model=self.model,
                finish_reason="stop",
            )
        )
        return self

    def call_tool(self, name: str, **arguments: object) -> FakeLLMClient:
        self.script.append(
            LLMResponse(
                text=None,
                tool_calls=(
                    ToolCall(
                        id=f"fake_call_{len(self.script) + 1}",
                        name=name,
                        arguments=dict(arguments),
                    ),
                ),
                usage=ZERO_USAGE,
                model=self.model,
                finish_reason="tool_calls",
            )
        )
        return self

    def raise_(self, error: Exception) -> FakeLLMClient:
        self.script.append(error)
        return self

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
        del tools
        validate_request_limits(
            timeout_s=timeout_s,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        ctx.cancel.raise_if_cancelled()
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError("FakeLLMClient: 예상하지 못한 추가 호출")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if item.tool_calls:
            raise LLMBadResponse("Phase 1에서는 도구 호출 응답을 처리하지 않습니다.")
        return item

    def count_tokens(self, messages: Sequence[Message]) -> int:
        """Use a stable character count; provider tokenizers are tested separately."""
        return sum(len(message.content) for message in messages)
