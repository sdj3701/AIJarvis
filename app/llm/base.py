"""Provider-neutral LLM value objects and client protocol."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol, TypeAlias

from app.core.context import RequestContext
from app.core.errors import LLMBadResponse

Role = Literal["system", "user", "assistant", "tool"]
FinishReason = Literal["stop", "tool_calls", "length", "filtered", "error"]
ToolSpec: TypeAlias = Any


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str
    tool_call_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("message content must be a string")
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("unsupported message role")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages require tool_call_id")
        if self.role != "tool" and self.tool_call_id is not None:
            raise ValueError("tool_call_id is valid only for tool messages")
        if self.name is not None and (not isinstance(self.name, str) or not self.name):
            raise ValueError("message name cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not isinstance(self.name, str):
            raise TypeError("tool call id and name must be strings")
        if not self.id or not self.name:
            raise ValueError("tool call id and name must be non-empty")
        if not isinstance(self.arguments, dict):
            raise TypeError("tool call arguments must be a dictionary")


@dataclass(frozen=True, slots=True)
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    latency_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.prompt_tokens, int) or isinstance(self.prompt_tokens, bool):
            raise TypeError("prompt_tokens must be an integer")
        if self.prompt_tokens < 0:
            raise ValueError("prompt_tokens must be a non-negative integer")
        if not isinstance(self.completion_tokens, int) or isinstance(self.completion_tokens, bool):
            raise TypeError("completion_tokens must be an integer")
        if self.completion_tokens < 0:
            raise ValueError("completion_tokens must be a non-negative integer")
        if not isinstance(self.latency_ms, int) or isinstance(self.latency_ms, bool):
            raise TypeError("latency_ms must be an integer")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be a non-negative integer")
        if not isinstance(self.cost_usd, Decimal):
            raise TypeError("cost_usd must be Decimal")
        if not self.cost_usd.is_finite() or self.cost_usd < 0:
            raise ValueError("cost_usd must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    usage: LLMUsage
    model: str
    finish_reason: FinishReason

    def __post_init__(self) -> None:
        if self.text is not None and not isinstance(self.text, str):
            raise LLMBadResponse("LLM 응답 본문 형식이 올바르지 않습니다.")
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(item, ToolCall) for item in self.tool_calls
        ):
            raise LLMBadResponse("LLM 도구 호출 형식이 올바르지 않습니다.")
        if not isinstance(self.usage, LLMUsage):
            raise LLMBadResponse("LLM 사용량 형식이 올바르지 않습니다.")
        if not isinstance(self.model, str) or not self.model:
            raise LLMBadResponse("LLM 응답에 모델 식별자가 없습니다.")
        if self.finish_reason not in {"stop", "tool_calls", "length", "filtered", "error"}:
            raise LLMBadResponse("알 수 없는 LLM 종료 사유입니다.")
        if self.finish_reason == "error":
            raise LLMBadResponse("LLM 오류 응답은 예외로 처리해야 합니다.")
        if self.finish_reason == "tool_calls" and not self.tool_calls:
            raise LLMBadResponse("도구 호출 종료 응답에 호출 정보가 없습니다.")
        if self.tool_calls and self.finish_reason != "tool_calls":
            raise LLMBadResponse("도구 호출과 종료 사유가 일치하지 않습니다.")


class LLMClient(Protocol):
    name: str

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        timeout_s: float,
        ctx: RequestContext,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse: ...

    def count_tokens(self, messages: Sequence[Message]) -> int: ...


def validate_request_limits(
    *,
    timeout_s: float,
    temperature: float | None,
    max_output_tokens: int | None,
) -> None:
    """Validate provider-independent request limits shared by clients."""
    if isinstance(timeout_s, bool) or timeout_s <= 0 or not math.isfinite(timeout_s):
        raise ValueError("timeout_s must be finite and positive")
    if temperature is not None and (
        isinstance(temperature, bool) or not math.isfinite(temperature) or not 0 <= temperature <= 2
    ):
        raise ValueError("temperature must be between 0 and 2")
    if max_output_tokens is not None and (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens <= 0
    ):
        raise ValueError("max_output_tokens must be a positive integer")
