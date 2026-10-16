# 파이썬 공부 | scripts/tests/unit/test_llm_contract.py
# llm_contract 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any, cast

import pytest

from app.core.context import RequestContext
from app.core.errors import LLMBadResponse, LLMTimeout
from app.llm.base import LLMClient, LLMResponse, LLMUsage, Message, ToolCall
from app.llm.fake import FakeLLMClient

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase1


# ActiveCancellation: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class ActiveCancellation:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: cancelled.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, *, cancelled: bool = False) -> None:
        # 오른쪽 식을 계산한 값을 self._cancelled에 대입합니다.
        self._cancelled = cancelled

    # raise_if_cancelled(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def raise_if_cancelled(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._cancelled.
        if self._cancelled:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise InterruptedError("cancelled")


# _context(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: cancelled.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: RequestContext.
def _context(*, cancelled: bool = False) -> RequestContext:
    # 아래 함수()의 반환값을 context에 대입합니다.
    context = type("Context", (), {"cancel": ActiveCancellation(cancelled=cancelled)})()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return cast(RequestContext, context)


# pytest가 test_value_objects_follow_provider_neutral_contract()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_value_objects_follow_provider_neutral_contract() -> None:
    # LLMUsage()의 반환값을 usage에 대입합니다.
    usage = LLMUsage(10, 5, Decimal("0.0012"), 42)
    # LLMResponse()의 반환값을 response에 대입합니다.
    response = LLMResponse("답변", (), usage, "fake-model", "stop")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.text == "답변"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.usage.cost_usd == Decimal("0.0012")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(FrozenInstanceError):
        # response.model에 문자열을 대입합니다.
        response.model = "changed"  # type: ignore[misc]


# pytest가 test_valid_message_roles()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: message.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    "message",
    [
        Message("system", "규칙"),
        Message("user", "질문"),
        Message("assistant", "답변"),
        Message(
            "assistant",
            "",
            tool_calls=(ToolCall("call_1", "search", {"query": "Jarvis"}),),
        ),
        Message("tool", "결과", tool_call_id="call_1", name="search"),
    ],
)
def test_valid_message_roles(message: Message) -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert message.content or message.tool_calls


# pytest가 test_tool_message_requires_call_id_and_other_roles_forbid_it()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_tool_message_requires_call_id_and_other_roles_forbid_it() -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="require tool_call_id"):
        # Message()을 호출해 작업을 수행합니다.
        Message("tool", "결과")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="only for tool"):
        # Message()을 호출해 작업을 수행합니다.
        Message("user", "질문", tool_call_id="call_1")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="require name"):
        # Message()을 호출해 작업을 수행합니다.
        Message("tool", "결과", tool_call_id="call_1")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="only for assistant"):
        # Message()을 호출해 작업을 수행합니다.
        Message("user", "질문", tool_calls=(ToolCall("call_1", "search", {}),))


# pytest가 test_message_and_tool_call_reject_invalid_runtime_shapes()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: factory.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises((TypeError, ValueError)):
        # factory()을 호출해 작업을 수행합니다.
        factory()


# pytest가 test_usage_rejects_negative_or_non_finite_values()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: usage.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # LLMUsage()을 호출해 작업을 수행합니다.
        LLMUsage(*usage)


# pytest가 test_usage_rejects_wrong_runtime_types()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: usage.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(TypeError):
        # LLMUsage()을 호출해 작업을 수행합니다.
        LLMUsage(*usage)


# pytest가 test_response_rejects_error_unknown_and_inconsistent_finish_reasons()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_response_rejects_error_unknown_and_inconsistent_finish_reasons() -> None:
    # LLMUsage()의 반환값을 usage에 대입합니다.
    usage = LLMUsage(0, 0, Decimal("0"), 0)
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall("call_1", "search", {"query": "test"})

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse, match="예외"):
        # LLMResponse()을 호출해 작업을 수행합니다.
        LLMResponse(None, (), usage, "model", "error")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse, match="알 수 없는"):
        # LLMResponse()을 호출해 작업을 수행합니다.
        LLMResponse(None, (), usage, "model", cast(Any, "unknown"))
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse, match="호출 정보"):
        # LLMResponse()을 호출해 작업을 수행합니다.
        LLMResponse(None, (), usage, "model", "tool_calls")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse, match="일치"):
        # LLMResponse()을 호출해 작업을 수행합니다.
        LLMResponse("text", (call,), usage, "model", "stop")


# pytest가 test_response_rejects_invalid_runtime_shapes()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: response.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMBadResponse):
        # response()을 호출해 작업을 수행합니다.
        response(LLMUsage(0, 0, Decimal("0"), 0))


# pytest가 test_fake_client_scripts_responses_and_records_prompts()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_fake_client_scripts_responses_and_records_prompts() -> None:
    # LLMUsage()의 반환값을 usage에 대입합니다.
    usage = LLMUsage(3, 2, Decimal("0.0001"), 7)
    # 아래 함수()의 반환값을 client에 대입합니다.
    client: LLMClient = FakeLLMClient().reply("첫 답변", usage=usage).reply("둘째 답변")
    # first_prompt에 리스트(순서가 있고 수정 가능)을 대입합니다.
    first_prompt = [Message("user", "첫 질문")]
    # second_prompt에 리스트(순서가 있고 수정 가능)을 대입합니다.
    second_prompt = [Message("user", "둘째 질문")]

    # client.complete()의 반환값을 first에 대입합니다.
    first = client.complete(messages=first_prompt, timeout_s=1, ctx=_context())
    # client.complete()의 반환값을 second에 대입합니다.
    second = client.complete(messages=second_prompt, timeout_s=1, ctx=_context())

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.text == "첫 답변"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.usage == usage
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.text == "둘째 답변"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert client.calls == [first_prompt, second_prompt]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(client, FakeLLMClient)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert client.script == []


# pytest가 test_fake_client_exhaustion_and_scripted_exception_fail_immediately()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_fake_client_exhaustion_and_scripted_exception_fail_immediately() -> None:
    # FakeLLMClient()의 반환값을 client에 대입합니다.
    client = FakeLLMClient()
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(AssertionError, match="예상하지 못한 추가 호출"):
        # client.complete()을 호출해 작업을 수행합니다.
        client.complete(messages=[], timeout_s=1, ctx=_context())

    # LLMTimeout()의 반환값을 timeout에 대입합니다.
    timeout = LLMTimeout("시간 초과")
    # client.raise_()을 호출해 작업을 수행합니다.
    client.raise_(timeout)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(LLMTimeout) as captured:
        # client.complete()을 호출해 작업을 수행합니다.
        client.complete(messages=[], timeout_s=1, ctx=_context())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value is timeout


# pytest가 test_fake_returns_tool_calls_for_phase_four()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_fake_returns_tool_calls_for_phase_four() -> None:
    # FakeLLMClient().call_tool()의 반환값을 client에 대입합니다.
    client = FakeLLMClient().call_tool("web_search", query="날씨")

    # client.complete()의 반환값을 response에 대입합니다.
    response = client.complete(messages=[Message("user", "검색")], timeout_s=1, ctx=_context())

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert response.tool_calls[0].name == "web_search"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert client.calls == [[Message("user", "검색")]]


# pytest가 test_fake_checks_cancellation_before_consuming_script()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_fake_checks_cancellation_before_consuming_script() -> None:
    # FakeLLMClient().reply()의 반환값을 client에 대입합니다.
    client = FakeLLMClient().reply("소비되면 안 됨")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(InterruptedError):
        # client.complete()을 호출해 작업을 수행합니다.
        client.complete(messages=[], timeout_s=1, ctx=_context(cancelled=True))

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(client.script) == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert client.calls == []


# pytest가 test_fake_token_count_is_deterministic()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_fake_token_count_is_deterministic() -> None:
    # messages에 리스트(순서가 있고 수정 가능)을 대입합니다.
    messages = [Message("system", "abcd"), Message("user", "한글")]

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert FakeLLMClient().count_tokens(messages) == 6


# pytest가 test_fake_rejects_invalid_provider_independent_limits()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: kwargs.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # FakeLLMClient().reply()의 반환값을 client에 대입합니다.
    client = FakeLLMClient().reply("답변")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError):
        # client.complete()을 호출해 작업을 수행합니다.
        client.complete(messages=[], ctx=_context(), **kwargs)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(client.script) == 1


# pytest가 test_fake_requires_model_name()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_fake_requires_model_name() -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="model"):
        # FakeLLMClient()을 호출해 작업을 수행합니다.
        FakeLLMClient(model="")
