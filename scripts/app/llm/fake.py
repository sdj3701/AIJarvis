# 파이썬 공부 | scripts/app/llm/fake.py
# 실제 AI 대신 미리 정한 응답을 돌려주는 테스트용 클라이언트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Deterministic scripted LLM client for offline tests."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

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

# 오른쪽 식을 계산한 값을 ScriptItem에 대입합니다.
ScriptItem = LLMResponse | Exception
# LLMUsage()의 반환값을 ZERO_USAGE에 대입합니다.
ZERO_USAGE = LLMUsage(0, 0, Decimal("0"), 0)


# FakeLLMClient: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeLLMClient:
    """Return queued responses and record every prompt without network access."""

    # name에 문자열을 대입합니다.
    name = "fake"

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: model.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, *, model: str = "fake-model") -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not model.
        if not model:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("fake model must be non-empty")
        # 오른쪽 식을 계산한 값을 self.model에 대입합니다.
        self.model = model
        # self.script에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.script: list[ScriptItem] = []
        # self.calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.calls: list[list[Message]] = []
        # self.tool_specs에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.tool_specs: list[tuple[ToolSpec, ...]] = []

    # reply(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, usage.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: FakeLLMClient.
    def reply(self, text: str, *, usage: LLMUsage | None = None) -> FakeLLMClient:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.script.append(
            LLMResponse(
                text=text,
                tool_calls=(),
                usage=usage or ZERO_USAGE,
                model=self.model,
                finish_reason="stop",
            )
        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # call_tool(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: name.
    # **arguments는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: FakeLLMClient.
    def call_tool(self, name: str, **arguments: object) -> FakeLLMClient:
        # 리스트 끝에 항목 하나를 추가합니다.
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
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # raise_(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: error.
    # 반환 타입 힌트: FakeLLMClient.
    def raise_(self, error: Exception) -> FakeLLMClient:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.script.append(error)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # complete(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages, tools, timeout_s, ctx, temperature, max_output_tokens.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: LLMResponse.
    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        timeout_s: float,
        ctx: RequestContext,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        # validate_request_limits()으로 입력 형식과 허용 조건을 검사합니다.
        validate_request_limits(
            timeout_s=timeout_s,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
        ctx.cancel.raise_if_cancelled()
        # 리스트 끝에 항목 하나를 추가합니다.
        self.calls.append(list(messages))
        # 리스트 끝에 항목 하나를 추가합니다.
        self.tool_specs.append(tuple(tools))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.script.
        if not self.script:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise AssertionError("FakeLLMClient: 예상하지 못한 추가 호출")
        # self.script.pop()의 반환값을 item에 대입합니다.
        item = self.script.pop(0)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(item, Exception).
        if isinstance(item, Exception):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise item
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: item.tool_calls.
        if item.tool_calls:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return item
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: item.text is None.
        if item.text is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("FakeLLMClient: text 응답이 없습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return item

    # count_tokens(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages.
    # 반환 타입 힌트: 정수(int).
    def count_tokens(self, messages: Sequence[Message]) -> int:
        """Use a stable character count; provider tokenizers are tested separately."""
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return sum(len(message.content) for message in messages)
