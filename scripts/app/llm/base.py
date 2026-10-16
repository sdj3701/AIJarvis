# 파이썬 공부 | scripts/app/llm/base.py
# AI에 보내는 메시지, 도구 호출, 응답, 사용량의 자료형과 공통 규약을 정의합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Provider-neutral LLM value objects and client protocol."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol, TypeAlias

from app.core.context import RequestContext
from app.core.errors import LLMBadResponse

# 오른쪽 식을 계산한 값을 Role에 대입합니다.
Role = Literal["system", "user", "assistant", "tool"]
# 오른쪽 식을 계산한 값을 FinishReason에 대입합니다.
FinishReason = Literal["stop", "tool_calls", "length", "filtered", "error"]
# 오른쪽 식을 계산한 값을 ToolSpec에 대입합니다.
ToolSpec: TypeAlias = Any


# Message: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class Message:
    # role: Role 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    role: Role
    # content: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    content: str
    # tool_call_id을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    tool_call_id: str | None = None
    # name을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    name: str | None = None
    # tool_calls에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    tool_calls: tuple[ToolCall, ...] = ()

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.content, str).
        if not isinstance(self.content, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("message content must be a string")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.role not in {'system', 'user',
        # 'assistant', 'tool'}.
        if self.role not in {"system", "user", "assistant", "tool"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("unsupported message role")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.role == 'tool' and (not
        # self.tool_call_id).
        if self.role == "tool" and not self.tool_call_id:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("tool messages require tool_call_id")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.role != 'tool' and
        # self.tool_call_id is not None.
        if self.role != "tool" and self.tool_call_id is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("tool_call_id is valid only for tool messages")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(item, ToolCall) for item in self.tool_calls
        ):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("message tool_calls must be a tuple of ToolCall")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.role != 'assistant' and
        # self.tool_calls.
        if self.role != "assistant" and self.tool_calls:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("tool_calls are valid only for assistant messages")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.name is not None and (not isinstance(self.name, str) or not self.name):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("message name cannot be empty")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.role == 'tool' and (not
        # self.name).
        if self.role == "tool" and not self.name:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("tool messages require name")


# ToolCall: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ToolCall:
    # id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    id: str
    # name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    name: str
    # arguments: dict[str, Any] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    arguments: dict[str, Any]

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.id, str) or not
        # isinstance(self.name,
        # str).
        if not isinstance(self.id, str) or not isinstance(self.name, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("tool call id and name must be strings")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.id or not self.name.
        if not self.id or not self.name:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("tool call id and name must be non-empty")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.arguments, dict).
        if not isinstance(self.arguments, dict):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("tool call arguments must be a dictionary")


# LLMUsage: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class LLMUsage:
    # prompt_tokens: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    prompt_tokens: int
    # completion_tokens: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    completion_tokens: int
    # cost_usd: Decimal 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    cost_usd: Decimal
    # latency_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    latency_ms: int

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(self.prompt_tokens, int) or isinstance(self.prompt_tokens, bool):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("prompt_tokens must be an integer")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.prompt_tokens < 0.
        if self.prompt_tokens < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("prompt_tokens must be a non-negative integer")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(self.completion_tokens, int) or isinstance(self.completion_tokens, bool):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("completion_tokens must be an integer")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.completion_tokens < 0.
        if self.completion_tokens < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("completion_tokens must be a non-negative integer")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(self.latency_ms, int) or isinstance(self.latency_ms, bool):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("latency_ms must be an integer")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.latency_ms < 0.
        if self.latency_ms < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("latency_ms must be a non-negative integer")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.cost_usd,
        # Decimal).
        if not isinstance(self.cost_usd, Decimal):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise TypeError("cost_usd must be Decimal")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.cost_usd.is_finite() or
        # self.cost_usd < 0.
        if not self.cost_usd.is_finite() or self.cost_usd < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("cost_usd must be finite and non-negative")


# LLMResponse: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class LLMResponse:
    # text: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str | None
    # tool_calls: tuple[ToolCall, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    tool_calls: tuple[ToolCall, ...]
    # usage: LLMUsage 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    usage: LLMUsage
    # model: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    model: str
    # finish_reason: FinishReason 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    finish_reason: FinishReason

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.text is not None and (not
        # isinstance(self.text,
        # str)).
        if self.text is not None and not isinstance(self.text, str):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("LLM 응답 본문 형식이 올바르지 않습니다.")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(item, ToolCall) for item in self.tool_calls
        ):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("LLM 도구 호출 형식이 올바르지 않습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.usage, LLMUsage).
        if not isinstance(self.usage, LLMUsage):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("LLM 사용량 형식이 올바르지 않습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(self.model, str) or not
        # self.model.
        if not isinstance(self.model, str) or not self.model:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("LLM 응답에 모델 식별자가 없습니다.")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.finish_reason not in {"stop", "tool_calls", "length", "filtered", "error"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("알 수 없는 LLM 종료 사유입니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.finish_reason == 'error'.
        if self.finish_reason == "error":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("LLM 오류 응답은 예외로 처리해야 합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.finish_reason == 'tool_calls' and
        # (not
        # self.tool_calls).
        if self.finish_reason == "tool_calls" and not self.tool_calls:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("도구 호출 종료 응답에 호출 정보가 없습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.tool_calls and self.finish_reason
        # != 'tool_calls'.
        if self.tool_calls and self.finish_reason != "tool_calls":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise LLMBadResponse("도구 호출과 종료 사유가 일치하지 않습니다.")


# LLMClient: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class LLMClient(Protocol):
    # name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    name: str

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
    ) -> LLMResponse: ...

    # count_tokens(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages.
    # 반환 타입 힌트: 정수(int).
    def count_tokens(self, messages: Sequence[Message]) -> int: ...


# validate_request_limits(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: timeout_s, temperature, max_output_tokens.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def validate_request_limits(
    *,
    timeout_s: float,
    temperature: float | None,
    max_output_tokens: int | None,
) -> None:
    """Validate provider-independent request limits shared by clients."""
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if isinstance(timeout_s, bool) or timeout_s <= 0 or not math.isfinite(timeout_s):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("timeout_s must be finite and positive")
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if temperature is not None and (
        isinstance(temperature, bool) or not math.isfinite(temperature) or not 0 <= temperature <= 2
    ):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("temperature must be between 0 and 2")
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if max_output_tokens is not None and (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens <= 0
    ):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("max_output_tokens must be a positive integer")
