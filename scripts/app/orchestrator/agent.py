# 파이썬 공부 | scripts/app/orchestrator/agent.py
# AI 판단, 실행 전 검사, 도구 실행, 결과 관찰을 여러 단계로 반복합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Multi-step agent loop: Decide → Validate → Act → Observe → Final."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Literal

from app.budget import BudgetGuard, estimate_llm_cost
from app.config.models import Settings
from app.core.context import RequestContext
from app.core.errors import ApprovalRequired, JarvisError, LLMBadResponse, PolicyDenied
from app.llm.base import LLMClient, LLMResponse, LLMUsage, Message, ToolCall
from app.orchestrator.envelope import wrap_untrusted_content
from app.orchestrator.prompt import PromptAssembler
from app.orchestrator.research import load_tools_prompt
from app.orchestrator.tasks import (
    CachedStepResult,
    StepRecord,
    StepState,
    TaskState,
    TaskStore,
    idempotency_key,
)
from app.safety.approval import ApprovalTicket
from app.safety.gate import SafetyGate, Verdict
from app.tools.base import ToolResult, ToolSpec
from app.tools.registry import ToolRegistry, validate_tool_args
from app.tools.runner import ToolRunner

# frozenset()의 반환값을 _SIDE_EFFECT_TOOLS에 대입합니다.
_SIDE_EFFECT_TOOLS = frozenset(
    {"create_file", "open_app", "close_app", "open_folder", "open_url", "run_skill"}
)
# frozenset()의 반환값을 _NEVER_AUTO_RETRY에 대입합니다.
_NEVER_AUTO_RETRY = frozenset({"open_app", "open_folder", "create_file", "run_skill", "open_url"})

# _GOAL_PATTERNS에 딕셔너리(키와 값의 쌍)을 대입합니다.
_GOAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "create_file": ("저장", "파일", "notes", "메모", "write", "save", "만들", "작성"),
    "open_folder": ("폴더", "folder", "디렉", "열어"),
    "open_app": ("앱", "app", "실행", "메모장", "계산기"),
    "close_app": ("종료해", "종료시켜", "꺼줘", "닫아줘"),
    "open_url": ("url", "링크", "link", "사이트", "웹페이지"),
    "run_skill": ("스크립트", "skill", "스킬"),
}


# AgentStopReason: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class AgentStopReason:
    # reason: Literal['final', 'max_steps', 'task_timeout', 'step_timeout', 'approval_pending',
    # 'error', 'cancelled'] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    reason: Literal[
        "final",
        "max_steps",
        "task_timeout",
        "step_timeout",
        "approval_pending",
        "error",
        "cancelled",
    ]
    # detail을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    detail: str | None = None


# AgentResult: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class AgentResult:
    # ok: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ok: bool
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # task_id: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    task_id: str
    # steps: tuple[StepRecord, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    steps: tuple[StepRecord, ...]
    # stop: AgentStopReason 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    stop: AgentStopReason
    # usage: LLMUsage 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    usage: LLMUsage
    # pending_approval을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    pending_approval: Verdict | None = None
    # pending_tool_call을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    pending_tool_call: ToolCall | None = None
    # pending_step_no을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    pending_step_no: int | None = None
    # pending_observations에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    pending_observations: tuple[Message, ...] = ()
    # pending_base_messages에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    pending_base_messages: tuple[Message, ...] = ()


# _AGENT_GOAL_SIDE_EFFECT에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
_AGENT_GOAL_SIDE_EFFECT = ("저장", "notes", "폴더", "파일", "열어", "만들")
# _AGENT_GOAL_SEARCH에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
_AGENT_GOAL_SEARCH = ("검색", "찾아", "조사", "알려")


# should_run_agent_goal(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 참/거짓(bool).
def should_run_agent_goal(text: str) -> bool:
    """Detect multi-step goals that should use the agent loop, not research auto-path."""
    # text.strip()의 반환값을 stripped에 대입합니다.
    stripped = text.strip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not stripped.
    if not stripped:
        # False을 반환하고 이 함수의 실행을 끝냅니다.
        return False
    # any()의 반환값을 has_search에 대입합니다.
    has_search = any(marker in stripped for marker in _AGENT_GOAL_SEARCH)
    # any()의 반환값을 has_side_effect에 대입합니다.
    has_side_effect = any(marker in stripped for marker in _AGENT_GOAL_SIDE_EFFECT)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return has_search and has_side_effect


# goal_permits_side_effect(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: goal, tool_name.
# 반환 타입 힌트: 참/거짓(bool).
def goal_permits_side_effect(goal: str, tool_name: str) -> bool:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name not in _SIDE_EFFECT_TOOLS.
    if tool_name not in _SIDE_EFFECT_TOOLS:
        # True을 반환하고 이 함수의 실행을 끝냅니다.
        return True
    # _GOAL_PATTERNS.get()의 반환값을 patterns에 대입합니다.
    patterns = _GOAL_PATTERNS.get(tool_name, ())
    # goal.lower()의 반환값을 lowered에 대입합니다.
    lowered = goal.lower()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return any(pattern in lowered or pattern in goal for pattern in patterns)


# format_step_breakdown(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: steps, max_steps.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def format_step_breakdown(steps: Sequence[StepRecord], *, max_steps: int) -> str:
    # 오른쪽 식을 계산한 값을 completed에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    completed = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "succeeded"]
    # 오른쪽 식을 계산한 값을 failed에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    failed = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "failed"]
    # 오른쪽 식을 계산한 값을 cancelled에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    cancelled = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "cancelled"]
    # 오른쪽 식을 계산한 값을 executed에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    executed = {s.step_no for s in steps}
    # 오른쪽 식을 계산한 값을 not_run에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    not_run = [
        str(number)
        for number in range(1, max_steps + 1)
        if number not in executed
    ]
    # lines에 리스트(순서가 있고 수정 가능)을 대입합니다.
    lines = ["## 단계 현황"]
    # 리스트 끝에 항목 하나를 추가합니다.
    lines.append("완료: " + (", ".join(completed) if completed else "없음"))
    # 리스트 끝에 항목 하나를 추가합니다.
    lines.append("실패: " + (", ".join(failed) if failed else "없음"))
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: cancelled.
    if cancelled:
        # 리스트 끝에 항목 하나를 추가합니다.
        lines.append("취소: " + ", ".join(cancelled))
    # 리스트 끝에 항목 하나를 추가합니다.
    lines.append("미실행: " + (", ".join(not_run) if not_run else "없음"))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return "\n".join(lines)


# AgentRunner: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class AgentRunner:
    """Execute bounded multi-step tool loops with task persistence."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: settings, llm, tasks, tool_runner, safety_gate, registry, budget, prompt.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        tasks: TaskStore,
        tool_runner: ToolRunner,
        safety_gate: SafetyGate,
        registry: ToolRegistry,
        budget: BudgetGuard,
        prompt: PromptAssembler,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self._settings에 대입합니다.
        self._settings = settings
        # 오른쪽 식을 계산한 값을 self._llm에 대입합니다.
        self._llm = llm
        # 오른쪽 식을 계산한 값을 self._tasks에 대입합니다.
        self._tasks = tasks
        # 오른쪽 식을 계산한 값을 self._tool_runner에 대입합니다.
        self._tool_runner = tool_runner
        # 오른쪽 식을 계산한 값을 self._safety_gate에 대입합니다.
        self._safety_gate = safety_gate
        # 오른쪽 식을 계산한 값을 self._registry에 대입합니다.
        self._registry = registry
        # 오른쪽 식을 계산한 값을 self._budget에 대입합니다.
        self._budget = budget
        # 오른쪽 식을 계산한 값을 self._prompt에 대입합니다.
        self._prompt = prompt

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: goal, ctx, task_id, initial_response, initial_tool_call, initial_observations,
    # initial_base_messages, resume_step_no, resume_ticket.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: AgentResult.
    def run(
        self,
        *,
        goal: str,
        ctx: RequestContext,
        task_id: str,
        initial_response: LLMResponse | None = None,
        initial_tool_call: ToolCall | None = None,
        initial_observations: Sequence[Message] = (),
        initial_base_messages: Sequence[Message] = (),
        resume_step_no: int | None = None,
        resume_ticket: ApprovalTicket | None = None,
    ) -> AgentResult:
        # 오른쪽 식을 계산한 값을 agent_cfg에 대입합니다.
        agent_cfg = self._settings.agent
        # ctx.clock.now()의 반환값을 now에 대입합니다.
        now = ctx.clock.now()
        # ctx.clock.monotonic_ms()의 반환값을 run_started_ms에 대입합니다.
        run_started_ms = ctx.clock.monotonic_ms()
        # self._tasks.get_task()의 반환값을 task에 대입합니다.
        task = self._tasks.get_task(task_id)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: task is None.
        if task is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"unknown task: {task_id}")

        # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
        self._tasks.update_task_state(task_id, "running", now=now)
        # replace()의 반환값을 ctx에 대입합니다.
        ctx = replace(ctx, task_id=task_id)

        # list()의 반환값을 observations에 대입합니다.
        observations = list(initial_observations)
        # tuple()의 반환값을 base_messages에 대입합니다.
        base_messages = tuple(initial_base_messages)
        # LLMUsage()의 반환값을 usage_total에 대입합니다.
        usage_total = LLMUsage(0, 0, Decimal("0"), 0)
        # 오른쪽 식을 계산한 값을 step_no에 대입합니다.
        step_no = resume_step_no or (len(self._tasks.list_steps(task_id)) + 1)
        # 오른쪽 식을 계산한 값을 pending_call에 대입합니다.
        pending_call = initial_tool_call
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: initial_response is not None.
        if initial_response is not None:
            # _single_tool_call()의 반환값을 pending_call에 대입합니다.
            pending_call = _single_tool_call(initial_response)
            # 리스트 끝에 항목 하나를 추가합니다.
            observations.append(_assistant_tool_message(initial_response))
            # _merge_usage()의 반환값을 usage_total에 대입합니다.
            usage_total = _merge_usage(usage_total, initial_response.usage)
            # self._budget.record_llm()을 호출해 작업을 수행합니다.
            self._budget.record_llm(initial_response.usage, ctx=ctx)
        # AgentStopReason()의 반환값을 stop에 대입합니다.
        stop = AgentStopReason("final")

        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while step_no <= agent_cfg.max_steps:
            # _elapsed_seconds()의 반환값을 elapsed_s에 대입합니다.
            elapsed_s = _elapsed_seconds(ctx, run_started_ms)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: elapsed_s >=
            # agent_cfg.total_timeout_s.
            if elapsed_s >= agent_cfg.total_timeout_s:
                # AgentStopReason()의 반환값을 stop에 대입합니다.
                stop = AgentStopReason("task_timeout", "전체 작업 시간이 초과되었습니다.")
                # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
                self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                break
            # ctx.clock.monotonic_ms()의 반환값을 step_started_ms에 대입합니다.
            step_started_ms = ctx.clock.monotonic_ms()
            # min()의 반환값을 step_limit_s에 대입합니다.
            step_limit_s = min(
                agent_cfg.step_timeout_s,
                max(0.001, agent_cfg.total_timeout_s - elapsed_s),
            )

            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: pending_call is None.
            if pending_call is None:
                # self._decide()의 반환값을 response에 대입합니다.
                response = self._decide(
                    goal,
                    observations,
                    base_messages=base_messages,
                    ctx=ctx,
                    timeout_s=min(self._settings.llm.timeout_s, step_limit_s),
                )
                # _merge_usage()의 반환값을 usage_total에 대입합니다.
                usage_total = _merge_usage(usage_total, response.usage)
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _elapsed_seconds(ctx,
                # step_started_ms) >=
                # step_limit_s.
                if _elapsed_seconds(ctx, step_started_ms) >= step_limit_s:
                    # AgentStopReason()의 반환값을 stop에 대입합니다.
                    stop = AgentStopReason("step_timeout", "단계 실행 시간이 초과되었습니다.")
                    # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
                    self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                    # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                    break
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: response.tool_calls.
                if response.tool_calls:
                    # _single_tool_call()의 반환값을 pending_call에 대입합니다.
                    pending_call = _single_tool_call(response)
                    # 리스트 끝에 항목 하나를 추가합니다.
                    observations.append(_assistant_tool_message(response))
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: response.text is not None.
                elif response.text is not None:
                    # 오른쪽 식을 계산한 값을 final_text에 대입합니다.
                    final_text = response.text
                    # self._tasks.list_steps()의 반환값을 steps에 대입합니다.
                    steps = self._tasks.list_steps(task_id)
                    # format_step_breakdown()의 반환값을 breakdown에 대입합니다.
                    breakdown = format_step_breakdown(steps, max_steps=agent_cfg.max_steps)
                    # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
                    self._tasks.update_task_state(task_id, "succeeded", now=ctx.clock.now())
                    # self._emit_stop()을 호출해 작업을 수행합니다.
                    self._emit_stop(ctx, task_id, "final", steps)
                    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                    return AgentResult(
                        ok=True,
                        text=f"{final_text}\n\n{breakdown}",
                        task_id=task_id,
                        steps=steps,
                        stop=AgentStopReason("final"),
                        usage=usage_total,
                    )
                # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                else:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise LLMBadResponse("LLM 응답 본문이 없습니다.")

            # 오른쪽 식을 계산한 값을 call에 대입합니다.
            call = pending_call
            # pending_call을 아직 값이 없음을 뜻하는 None으로 설정합니다.
            pending_call = None

            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # self._execute_step()의 반환값을 outcome에 대입합니다.
                outcome = self._execute_step(
                    call,
                    step_no=step_no,
                    goal=goal,
                    ctx=ctx,
                    ticket=resume_ticket if step_no == resume_step_no else None,
                )
                # resume_ticket을 아직 값이 없음을 뜻하는 None으로 설정합니다.
                resume_ticket = None
            # ApprovalRequired를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except ApprovalRequired as error:
                # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
                verdict = error.verdict
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(verdict,
                # Verdict).
                if not isinstance(verdict, Verdict):
                    # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
                    raise
                # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
                self._tasks.update_task_state(task_id, "running", now=ctx.clock.now())
                # self._tasks.list_steps()의 반환값을 steps에 대입합니다.
                steps = self._tasks.list_steps(task_id)
                # self._emit_stop()을 호출해 작업을 수행합니다.
                self._emit_stop(ctx, task_id, "approval_pending", steps)
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return AgentResult(
                    ok=False,
                    text=verdict.display,
                    task_id=task_id,
                    steps=steps,
                    stop=AgentStopReason("approval_pending"),
                    usage=usage_total,
                    pending_approval=verdict,
                    pending_tool_call=call,
                    pending_step_no=step_no,
                    pending_observations=tuple(observations),
                    pending_base_messages=base_messages,
                )
            # (PolicyDenied, JarvisError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
            # 담깁니다.
            except (PolicyDenied, JarvisError) as error:
                # 오른쪽 식을 계산한 값을 message에 대입합니다.
                # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
                message = error.user_message if isinstance(error, JarvisError) else str(error)
                # self._tasks.mark_step_finished()을 호출해 작업을 수행합니다.
                self._tasks.mark_step_finished(
                    task_id,
                    step_no,
                    state="failed",
                    result_summary=message,
                    changed_paths=(),
                    now=ctx.clock.now(),
                )
                # AgentStopReason()의 반환값을 stop에 대입합니다.
                stop = AgentStopReason("error", message)
                # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
                self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                break

            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not outcome.ok.
            if not outcome.ok:
                # AgentStopReason()의 반환값을 stop에 대입합니다.
                stop = AgentStopReason("error", outcome.error)
                # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
                self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                break
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _elapsed_seconds(ctx,
            # step_started_ms) >=
            # step_limit_s.
            if _elapsed_seconds(ctx, step_started_ms) >= step_limit_s:
                # AgentStopReason()의 반환값을 stop에 대입합니다.
                stop = AgentStopReason("step_timeout", "단계 실행 시간이 초과되었습니다.")
                # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
                self._tasks.update_task_state(task_id, "failed", now=ctx.clock.now())
                # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                break

            # self._observe()의 반환값을 observe_text에 대입합니다.
            observe_text = self._observe(outcome, call=call, ctx=ctx)
            # 리스트 끝에 항목 하나를 추가합니다.
            observations.append(
                Message("tool", observe_text, tool_call_id=call.id, name=call.name)
            )
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            ctx.events.emit(
                "agent.step",
                {
                    "task_id": task_id,
                    "step_no": step_no,
                    "decision": "tool",
                    "tool_name": call.name,
                },
            )
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            step_no += 1

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stop.reason == 'final' and step_no >
        # agent_cfg.max_steps.
        if stop.reason == "final" and step_no > agent_cfg.max_steps:
            # AgentStopReason()의 반환값을 stop에 대입합니다.
            stop = AgentStopReason("max_steps", f"최대 {agent_cfg.max_steps}단계에 도달했습니다.")

        # self._tasks.list_steps()의 반환값을 steps에 대입합니다.
        steps = self._tasks.list_steps(task_id)
        # 오른쪽 식을 계산한 값을 final_state에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        final_state: TaskState = "cancelled" if stop.reason == "cancelled" else "failed"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stop.reason in {'max_steps',
        # 'task_timeout'}.
        if stop.reason in {"max_steps", "task_timeout"}:
            # final_state에 문자열을 대입합니다.
            final_state = "failed"
        # self._tasks.update_task_state()을 호출해 작업을 수행합니다.
        self._tasks.update_task_state(task_id, final_state, now=ctx.clock.now())
        # format_step_breakdown()의 반환값을 breakdown에 대입합니다.
        breakdown = format_step_breakdown(steps, max_steps=agent_cfg.max_steps)
        # 오른쪽 식을 계산한 값을 detail에 대입합니다.
        detail = stop.detail or "작업이 중단되었습니다."
        # self._emit_stop()을 호출해 작업을 수행합니다.
        self._emit_stop(ctx, task_id, stop.reason, steps)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return AgentResult(
            ok=False,
            text=f"{detail}\n\n{breakdown}",
            task_id=task_id,
            steps=steps,
            stop=stop,
            usage=usage_total,
        )

    # _decide(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: goal, observations, base_messages, ctx, timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def _decide(
        self,
        goal: str,
        observations: Sequence[Message],
        *,
        base_messages: Sequence[Message],
        ctx: RequestContext,
        timeout_s: float,
    ) -> Any:
        # estimate_llm_cost()의 반환값을 estimated에 대입합니다.
        estimated = estimate_llm_cost(
            self._settings.llm,
            prompt_tokens=self._settings.llm.context.max_input_tokens,
            max_output_tokens=self._settings.llm.max_output_tokens,
        )
        # self._budget.check()을 호출해 작업을 수행합니다.
        self._budget.check("llm", estimated, ctx=ctx)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: base_messages.
        if base_messages:
            # messages에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
            messages = (*base_messages, *observations)
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # load_tools_prompt()의 반환값을 tools_prompt에 대입합니다.
            tools_prompt = load_tools_prompt()
            # 오른쪽 식을 계산한 값을 agent_instruction에 대입합니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            agent_instruction = (
                f"사용자 목표: {goal}\n"
                "한 번에 하나의 도구만 호출하거나, 모든 단계가 끝났으면 최종 답변을 작성하세요."
            )
            # self._prompt.build()의 반환값을 plan에 대입합니다.
            plan = self._prompt.build(
                current_user_text=agent_instruction,
                history=(),
                cancel=ctx.cancel,
                extra_system=(tools_prompt,),
            )
            # messages에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
            messages = (*plan.messages, *observations)
        # self._registry.llm_tool_specs()의 반환값을 tool_specs에 대입합니다.
        tool_specs = self._registry.llm_tool_specs()
        # self._llm.complete()의 반환값을 response에 대입합니다.
        response = self._llm.complete(
            messages=messages,
            tools=tool_specs if self._settings.llm.native_tool_calling_enabled else (),
            timeout_s=timeout_s,
            ctx=ctx,
            temperature=self._settings.llm.temperature,
            max_output_tokens=self._settings.llm.max_output_tokens,
        )
        # self._budget.record_llm()을 호출해 작업을 수행합니다.
        self._budget.record_llm(response.usage, ctx=ctx)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return response

    # _execute_step(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: call, step_no, goal, ctx, ticket.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ToolResult.
    def _execute_step(
        self,
        call: ToolCall,
        *,
        step_no: int,
        goal: str,
        ctx: RequestContext,
        ticket: ApprovalTicket | None,
    ) -> ToolResult:
        # self._registry.specs.get()의 반환값을 spec에 대입합니다.
        spec = self._registry.specs.get(call.name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: spec is None or not spec.enabled.
        if spec is None or not spec.enabled:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(f"등록되지 않은 도구입니다: {call.name}")

        # validate_tool_args()의 반환값을 validated에 대입합니다.
        validated = validate_tool_args(spec.json_schema, call.arguments)
        # ToolCall()의 반환값을 normalized_call에 대입합니다.
        normalized_call = ToolCall(id=call.id, name=call.name, arguments=validated)
        # self._safety_gate.evaluate()의 반환값을 verdict에 대입합니다.
        verdict = self._safety_gate.evaluate(normalized_call, ctx=ctx, spec=spec)

        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if call.name in _SIDE_EFFECT_TOOLS and not goal_permits_side_effect(goal, call.name):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(
                "외부 콘텐츠나 모델 제안만으로는 부작용 도구를 실행하지 않습니다. "
                "원래 사용자 요청에 해당 작업이 포함되어야 합니다."
            )

        # idempotency_key()의 반환값을 key에 대입합니다.
        key = idempotency_key(
            task_id=ctx.task_id or "",
            step_no=step_no,
            tool_name=call.name,
            args_hash=verdict.args_hash,
        )
        # self._tasks.get_succeeded_by_idempotency()의 반환값을 cached에 대입합니다.
        cached = self._tasks.get_succeeded_by_idempotency(key)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: cached is None and ctx.task_id.
        if cached is None and ctx.task_id:
            # self._tasks.find_succeeded_step()의 반환값을 prior에 대입합니다.
            prior = self._tasks.find_succeeded_step(
                ctx.task_id,
                call.name,
                verdict.args_hash,
            )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: prior is not None and
            # prior.result_summary is not
            # None.
            if prior is not None and prior.result_summary is not None:
                # CachedStepResult()의 반환값을 cached에 대입합니다.
                cached = CachedStepResult(
                    ok=True,
                    output=prior.result_summary,
                    changed_paths=prior.changed_paths,
                    error=None,
                )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: cached is not None.
        if cached is not None:
            # self._ensure_step_record()을 호출해 작업을 수행합니다.
            self._ensure_step_record(
                ctx.task_id or "",
                step_no,
                call.name,
                verdict,
                cached,
                ctx=ctx,
            )
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ToolResult(
                ok=cached.ok,
                output=cached.output,
                data=None,
                error=cached.error,
                changed_paths=cached.changed_paths,
                duration_ms=0,
                truncated=False,
                untrusted=spec.untrusted_output,
            )

        # self._tasks.get_step()의 반환값을 existing에 대입합니다.
        existing = self._tasks.get_step(ctx.task_id or "", step_no)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing is None.
        if existing is None:
            # self._tasks.create_step()을 호출해 작업을 수행합니다.
            self._tasks.create_step(
                task_id=ctx.task_id or "",
                step_no=step_no,
                tool_name=call.name,
                normalized_args=verdict.normalized_args,
            )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing.args_hash !=
        # verdict.args_hash.
        elif existing.args_hash != verdict.args_hash:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("승인된 단계와 도구 인자가 일치하지 않습니다.")

        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if verdict.decision in {"confirm", "typed_confirm"} and ticket is None:
            # ToolRunner가 승인 요청 감사 로그를 남긴 뒤 ApprovalRequired를 올린다.
            # 실제 실행 전이므로 step은 pending 상태를 유지한다.
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._run_with_retry(normalized_call, spec=spec, ctx=ctx, ticket=None)

        # self._tasks.mark_step_running()을 호출해 작업을 수행합니다.
        self._tasks.mark_step_running(ctx.task_id or "", step_no, now=ctx.clock.now())
        # self._run_with_retry()의 반환값을 result에 대입합니다.
        result = self._run_with_retry(normalized_call, spec=spec, ctx=ctx, ticket=ticket)
        # 오른쪽 식을 계산한 값을 state에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        state: StepState = "succeeded" if result.ok else "failed"
        # self._tasks.mark_step_finished()을 호출해 작업을 수행합니다.
        self._tasks.mark_step_finished(
            ctx.task_id or "",
            step_no,
            state=state,
            result_summary=result.output[:2000],
            changed_paths=result.changed_paths,
            now=ctx.clock.now(),
        )
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        ctx.events.emit(
            "tool.result",
            {
                "tool_name": call.name,
                "args_hash": verdict.args_hash,
                "ok": result.ok,
                "duration_ms": result.duration_ms,
                "changed_paths": list(result.changed_paths),
                "truncated": result.truncated,
                "error": result.error,
            },
        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return result

    # _ensure_step_record(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: task_id, step_no, tool_name, verdict, cached, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _ensure_step_record(
        self,
        task_id: str,
        step_no: int,
        tool_name: str,
        verdict: Verdict,
        cached: CachedStepResult,
        *,
        ctx: RequestContext,
    ) -> None:
        # self._tasks.get_step()의 반환값을 existing에 대입합니다.
        existing = self._tasks.get_step(task_id, step_no)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing is not None and
        # existing.state == 'succeeded'.
        if existing is not None and existing.state == "succeeded":
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: existing is None.
        if existing is None:
            # self._tasks.create_step()을 호출해 작업을 수행합니다.
            self._tasks.create_step(
                task_id=task_id,
                step_no=step_no,
                tool_name=tool_name,
                normalized_args=verdict.normalized_args,
            )
        # self._tasks.mark_step_running()을 호출해 작업을 수행합니다.
        self._tasks.mark_step_running(task_id, step_no, now=ctx.clock.now())
        # self._tasks.mark_step_finished()을 호출해 작업을 수행합니다.
        self._tasks.mark_step_finished(
            task_id,
            step_no,
            state="succeeded",
            result_summary=cached.output[:2000],
            changed_paths=cached.changed_paths,
            now=ctx.clock.now(),
        )

    # _run_with_retry(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: call, spec, ctx, ticket.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: ToolResult.
    def _run_with_retry(
        self,
        call: ToolCall,
        *,
        spec: ToolSpec,
        ctx: RequestContext,
        ticket: ApprovalTicket | None,
    ) -> ToolResult:
        # max_retries에 숫자 등 고정된 값을 대입합니다.
        max_retries = 0
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.name in {'web_search',
        # 'doc_search'} and
        # spec.idempotent.
        if call.name in {"web_search", "doc_search"} and spec.idempotent:
            # 오른쪽 식을 계산한 값을 max_retries에 대입합니다.
            max_retries = self._settings.agent.auto_retry_idempotent
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.name == 'fetch_url' and
        # spec.idempotent.
        elif call.name == "fetch_url" and spec.idempotent:
            # max_retries에 숫자 등 고정된 값을 대입합니다.
            max_retries = 1

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.name in _NEVER_AUTO_RETRY.
        if call.name in _NEVER_AUTO_RETRY:
            # max_retries에 숫자 등 고정된 값을 대입합니다.
            max_retries = 0

        # attempts에 숫자 등 고정된 값을 대입합니다.
        attempts = 0
        # last을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        last: ToolResult | None = None
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while attempts <= max_retries:
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # self._tool_runner.execute()의 반환값을 result에 대입합니다.
                result = self._tool_runner.execute(
                    call,
                    ctx=ctx,
                    ticket=ticket if attempts == 0 else None,
                )
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if result.ok or call.name not in {"web_search", "doc_search", "fetch_url"}:
                    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                    return result
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if call.name == "fetch_url" and not _is_transient_network(result.error):
                    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                    return result
                # 오른쪽 식을 계산한 값을 last에 대입합니다.
                last = result
            # ApprovalRequired를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except ApprovalRequired:
                # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
                raise
            # JarvisError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except JarvisError as error:
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if call.name == "fetch_url" and _is_transient_network(error.user_message):
                    # ToolResult()의 반환값을 last에 대입합니다.
                    last = ToolResult(
                        ok=False,
                        output=error.user_message,
                        data=None,
                        error=error.user_message,
                        changed_paths=(),
                        duration_ms=0,
                        truncated=False,
                        untrusted=True,
                    )
                # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                else:
                    # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
                    raise
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            attempts += 1
            # ticket을 아직 값이 없음을 뜻하는 None으로 설정합니다.
            ticket = None
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return last or ToolResult(
            ok=False,
            output="도구 실행에 실패했습니다.",
            data=None,
            error="retry_exhausted",
            changed_paths=(),
            duration_ms=0,
            truncated=False,
            untrusted=spec.untrusted_output,
        )

    # _observe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: result, call, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 문자열(str).
    def _observe(self, result: ToolResult, *, call: ToolCall, ctx: RequestContext) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not result.untrusted.
        if not result.untrusted:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return result.output
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return wrap_untrusted_content(
            source=call.name,
            source_kind="tool_output",
            fetched_at=ctx.clock.now(),
            body=result.output,
        )

    # _emit_stop(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ctx, task_id, reason, steps.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _emit_stop(
        self,
        ctx: RequestContext,
        task_id: str,
        reason: str,
        steps: Sequence[StepRecord],
    ) -> None:
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        ctx.events.emit(
            "agent.stop",
            {
                "task_id": task_id,
                "reason": reason,
                "steps": [
                    {
                        "step_no": step.step_no,
                        "tool_name": step.tool_name,
                        "state": step.state,
                    }
                    for step in steps
                ],
            },
        )


# _single_tool_call(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: response.
# 반환 타입 힌트: ToolCall.
def _single_tool_call(response: LLMResponse) -> ToolCall:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(response.tool_calls) != 1.
    if len(response.tool_calls) != 1:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise LLMBadResponse("한 단계에는 도구 호출 하나만 허용됩니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return response.tool_calls[0]


# _assistant_tool_message(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: response.
# 반환 타입 힌트: Message.
def _assistant_tool_message(response: LLMResponse) -> Message:
    """Retain the exact validated assistant tool-call turn for the follow-up request."""
    # _single_tool_call()을 호출해 작업을 수행합니다.
    _single_tool_call(response)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Message(
        "assistant",
        response.text or "",
        tool_calls=response.tool_calls,
    )


# _merge_usage(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: total, addition.
# 반환 타입 힌트: LLMUsage.
def _merge_usage(total: LLMUsage, addition: LLMUsage) -> LLMUsage:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return LLMUsage(
        prompt_tokens=total.prompt_tokens + addition.prompt_tokens,
        completion_tokens=total.completion_tokens + addition.completion_tokens,
        cost_usd=total.cost_usd + addition.cost_usd,
        latency_ms=total.latency_ms + addition.latency_ms,
    )


# _elapsed_seconds(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: ctx, started_ms.
# 반환 타입 힌트: 실수(float).
def _elapsed_seconds(ctx: RequestContext, started_ms: int) -> float:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return max(0.0, (ctx.clock.monotonic_ms() - started_ms) / 1000)


# _is_transient_network(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: message.
# 반환 타입 힌트: 참/거짓(bool).
def _is_transient_network(message: str | None) -> bool:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not message.
    if not message:
        # False을 반환하고 이 함수의 실행을 끝냅니다.
        return False
    # message.lower()의 반환값을 lowered에 대입합니다.
    lowered = message.lower()
    # markers에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    markers = ("timeout", "timed out", "connection", "network", "일시", "연결")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return any(marker in lowered for marker in markers)
