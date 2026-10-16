# 파이썬 공부 | scripts/app/tools/base.py
# 도구가 받는 요청, 돌려주는 결과, 구현해야 할 규약을 정의합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tool contracts shared by registry and Phase 3 search implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.core.context import RequestContext

# 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: TYPE_CHECKING.
if TYPE_CHECKING:
    from app.safety.approval import ApprovalTicket
    from app.safety.paths import Sandbox

# 오른쪽 식을 계산한 값을 Risk에 대입합니다.
Risk = Literal["low", "medium", "high"]
# 오른쪽 식을 계산한 값을 Capability에 대입합니다.
Capability = Literal[
    "fs_read", "fs_write", "net_http", "proc_spawn", "proc_terminate", "audio_in", "audio_out"
]
# 오른쪽 식을 계산한 값을 ExecutionMode에 대입합니다.
ExecutionMode = Literal["in_process", "managed_process", "detached_allowlisted"]


# ToolSpec: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ToolSpec:
    # name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    name: str
    # description: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    description: str
    # json_schema: dict[str, Any] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    json_schema: dict[str, Any]
    # risk: Risk 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    risk: Risk
    # capabilities: frozenset[Capability] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    capabilities: frozenset[Capability]
    # execution_mode: ExecutionMode 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    execution_mode: ExecutionMode
    # idempotent: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    idempotent: bool
    # enabled: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    enabled: bool
    # untrusted_output: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    untrusted_output: bool
    # timeout_s: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    timeout_s: float
    # phase: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    phase: int


# ToolResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ToolResult:
    # ok: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ok: bool
    # output: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    output: str
    # data: dict[str, Any] | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    data: dict[str, Any] | None
    # error: str | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    error: str | None
    # changed_paths: tuple[str, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    changed_paths: tuple[str, ...]
    # duration_ms: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    duration_ms: int
    # truncated: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    truncated: bool
    # untrusted: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    untrusted: bool


# ToolContext: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class ToolContext:
    # ctx: RequestContext 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ctx: RequestContext
    # sandbox을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    sandbox: Sandbox | None = None
    # ticket을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    ticket: ApprovalTicket | None = None
    # normalized_args을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    normalized_args: dict[str, Any] | None = None


# Tool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class Tool(Protocol):
    # spec: ToolSpec 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    spec: ToolSpec

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult: ...
