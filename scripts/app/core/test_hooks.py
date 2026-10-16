# 파이썬 공부 | scripts/app/core/test_hooks.py
# 복구 테스트를 위해 개발 환경에서 의도적으로 프로세스를 종료합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Development-only abrupt-exit hooks used by the Phase 1 crash gate."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from app.core.context import RequestContext
from app.llm.base import LLMResponse, LLMUsage, Message, ToolSpec

# frozenset()의 반환값을 CRASH_POINTS에 대입합니다.
CRASH_POINTS = frozenset(
    {"user.input", "llm.request", "llm.response", "memory.write", "session.checkpoint"}
)


# CrashTestHook: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CrashTestHook:
    """Terminate only when both development mode and an exact allowlisted point are set."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: target, enabled, terminate.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        target: str | None,
        *,
        enabled: bool,
        terminate: Callable[[int], None] = os._exit,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self._target에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        self._target = target if target in CRASH_POINTS else None
        # 오른쪽 식을 계산한 값을 self._enabled에 대입합니다.
        self._enabled = enabled and self._target is not None
        # 오른쪽 식을 계산한 값을 self._terminate에 대입합니다.
        self._terminate = terminate

    # from_environment(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # cls는 이 메서드를 호출한 클래스입니다.
    # 입력: dev_mode.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: CrashTestHook.
    # @classmethod: 객체 대신 클래스를 첫 인자로 받습니다.
    @classmethod
    def from_environment(cls, *, dev_mode: bool) -> CrashTestHook:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cls(os.environ.get("JARVIS_TEST_KILL_AFTER"), enabled=dev_mode)

    # enabled(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def enabled(self) -> bool:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._enabled

    # after(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: point.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def after(self, point: str) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._enabled and point ==
        # self._target.
        if self._enabled and point == self._target:
            # self._terminate()을 호출해 작업을 수행합니다.
            self._terminate(97)


# CrashTestLLMClient: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CrashTestLLMClient:
    """Deterministic eventing fake selected only by the guarded crash-test environment."""

    # name에 문자열을 대입합니다.
    name = "crash-test-fake"

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
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del tools, timeout_s, temperature, max_output_tokens
        # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
        ctx.cancel.raise_if_cancelled()
        # self.count_tokens()의 반환값을 prompt_tokens에 대입합니다.
        prompt_tokens = self.count_tokens(messages)
        # 오른쪽 식을 계산한 값을 prompt_version에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        prompt_version = "1" if messages and messages[0].role == "system" else "unversioned"
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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
        # LLMUsage()의 반환값을 usage에 대입합니다.
        usage = LLMUsage(prompt_tokens, 4, Decimal("0"), 1)
        # LLMResponse()의 반환값을 response에 대입합니다.
        response = LLMResponse("테스트 응답", (), usage, self.name, "stop")
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return response

    # count_tokens(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages.
    # 반환 타입 힌트: 정수(int).
    def count_tokens(self, messages: Sequence[Message]) -> int:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return sum(len(message.content) for message in messages)
