from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any, cast

import pytest

from app.core.context import RequestContext
from app.core.errors import LLMBadResponse, LLMTimeout
from app.llm.base import LLMClient, LLMResponse, LLMUsage, Message, ToolCall
from app.llm.fake import FakeLLMClient

pytestmark = pytest.mark.phase1


class ActiveCancellation:
    def __init__(self, *, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise InterruptedError("cancelled")


def _context(*, cancelled: bool = False) -> RequestContext:
    context = type("Context", (), {"cancel": ActiveCancellation(cancelled=cancelled)})()
    return cast(RequestContext, context)


def test_value_objects_follow_provider_neutral_contract() -> None:
    usage = LLMUsage(10, 5, Decimal("0.0012"), 42)
    response = LLMResponse("답변", (), usage, "fake-model", "stop")

    assert response.text == "답변"
    assert response.usage.cost_usd == Decimal("0.0012")
    with pytest.raises(FrozenInstanceError):
        response.model = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "message",
    [
        Message("system", "규칙"),
        Message("user", "질문"),
        Message("assistant", "답변"),
        Message("tool", "결과", tool_call_id="call_1", name="search"),
    ],
)
def test_valid_message_roles(message: Message) -> None:
    assert message.content


def test_tool_message_requires_call_id_and_other_roles_forbid_it() -> None:
    with pytest.raises(ValueError, match="require tool_call_id"):
        Message("tool", "결과")
    with pytest.raises(ValueError, match="only for tool"):
        Message("user", "질문", tool_call_id="call_1")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Message(cast(Any, "invalid"), "내용"),
        lambda: Message("user", cast(Any, 123)),
        lambda: Message("user", "내용", name=""),
        lambda: ToolCall(cast(Any, 1), "tool", {}),
        lambda: ToolCall("", "tool", {}),
        lambda: ToolCall("call", "tool", cast(Any, [])),
    ],
)
def test_message_and_tool_call_reject_invalid_runtime_shapes(factory: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.parametrize(
    "usage",
    [
        (-1, 0, Decimal("0"), 0),
        (0, -1, Decimal("0"), 0),
        (0, 0, Decimal("-0.01"), 0),
        (0, 0, Decimal("NaN"), 0),
        (0, 0, Decimal("0"), -1),
    ],
)
def test_usage_rejects_negative_or_non_finite_values(
    usage: tuple[int, int, Decimal, int],
) -> None:
    with pytest.raises(ValueError):
        LLMUsage(*usage)


@pytest.mark.parametrize(
    "usage",
    [
        (cast(Any, True), 0, Decimal("0"), 0),
        (0, cast(Any, 1.5), Decimal("0"), 0),
        (0, 0, cast(Any, "0"), 0),
        (0, 0, Decimal("0"), cast(Any, False)),
    ],
)
def test_usage_rejects_wrong_runtime_types(usage: tuple[Any, Any, Any, Any]) -> None:
    with pytest.raises(TypeError):
        LLMUsage(*usage)


def test_response_rejects_error_unknown_and_inconsistent_finish_reasons() -> None:
    usage = LLMUsage(0, 0, Decimal("0"), 0)
    call = ToolCall("call_1", "search", {"query": "test"})

    with pytest.raises(LLMBadResponse, match="예외"):
        LLMResponse(None, (), usage, "model", "error")
    with pytest.raises(LLMBadResponse, match="알 수 없는"):
        LLMResponse(None, (), usage, "model", cast(Any, "unknown"))
    with pytest.raises(LLMBadResponse, match="호출 정보"):
        LLMResponse(None, (), usage, "model", "tool_calls")
    with pytest.raises(LLMBadResponse, match="일치"):
        LLMResponse("text", (call,), usage, "model", "stop")


@pytest.mark.parametrize(
    "response",
    [
        lambda usage: LLMResponse(cast(Any, 1), (), usage, "model", "stop"),
        lambda usage: LLMResponse(None, cast(Any, []), usage, "model", "stop"),
        lambda usage: LLMResponse(None, (), cast(Any, {}), "model", "stop"),
        lambda usage: LLMResponse(None, (), usage, "", "stop"),
    ],
)
def test_response_rejects_invalid_runtime_shapes(response: Any) -> None:
    with pytest.raises(LLMBadResponse):
        response(LLMUsage(0, 0, Decimal("0"), 0))


def test_fake_client_scripts_responses_and_records_prompts() -> None:
    usage = LLMUsage(3, 2, Decimal("0.0001"), 7)
    client: LLMClient = FakeLLMClient().reply("첫 답변", usage=usage).reply("둘째 답변")
    first_prompt = [Message("user", "첫 질문")]
    second_prompt = [Message("user", "둘째 질문")]

    first = client.complete(messages=first_prompt, timeout_s=1, ctx=_context())
    second = client.complete(messages=second_prompt, timeout_s=1, ctx=_context())

    assert first.text == "첫 답변"
    assert first.usage == usage
    assert second.text == "둘째 답변"
    assert client.calls == [first_prompt, second_prompt]
    assert isinstance(client, FakeLLMClient)
    assert client.script == []


def test_fake_client_exhaustion_and_scripted_exception_fail_immediately() -> None:
    client = FakeLLMClient()
    with pytest.raises(AssertionError, match="예상하지 못한 추가 호출"):
        client.complete(messages=[], timeout_s=1, ctx=_context())

    timeout = LLMTimeout("시간 초과")
    client.raise_(timeout)
    with pytest.raises(LLMTimeout) as captured:
        client.complete(messages=[], timeout_s=1, ctx=_context())
    assert captured.value is timeout


def test_phase_one_fake_rejects_tool_calls() -> None:
    client = FakeLLMClient().call_tool("web_search", query="날씨")

    with pytest.raises(LLMBadResponse, match="Phase 1"):
        client.complete(messages=[Message("user", "검색")], timeout_s=1, ctx=_context())

    assert client.calls == [[Message("user", "검색")]]


def test_fake_checks_cancellation_before_consuming_script() -> None:
    client = FakeLLMClient().reply("소비되면 안 됨")

    with pytest.raises(InterruptedError):
        client.complete(messages=[], timeout_s=1, ctx=_context(cancelled=True))

    assert len(client.script) == 1
    assert client.calls == []


def test_fake_token_count_is_deterministic() -> None:
    messages = [Message("system", "abcd"), Message("user", "한글")]

    assert FakeLLMClient().count_tokens(messages) == 6


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_s": 0},
        {"timeout_s": float("inf")},
        {"timeout_s": True},
        {"timeout_s": 1, "temperature": -0.1},
        {"timeout_s": 1, "temperature": 2.1},
        {"timeout_s": 1, "temperature": True},
        {"timeout_s": 1, "max_output_tokens": 0},
        {"timeout_s": 1, "max_output_tokens": 1.5},
    ],
)
def test_fake_rejects_invalid_provider_independent_limits(kwargs: dict[str, Any]) -> None:
    client = FakeLLMClient().reply("답변")

    with pytest.raises(ValueError):
        client.complete(messages=[], ctx=_context(), **kwargs)

    assert len(client.script) == 1


def test_fake_requires_model_name() -> None:
    with pytest.raises(ValueError, match="model"):
        FakeLLMClient(model="")
