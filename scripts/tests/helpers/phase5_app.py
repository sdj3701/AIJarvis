# 파이썬 공부 | scripts/tests/helpers/phase5_app.py
# 에이전트 통합 테스트에서 사용할 앱과 실행 환경을 구성합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Shared Phase 5 test application fixture with multi-step FakeLLM scripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
import yaml

from app.core.clock import Clock
from app.llm.base import LLMUsage
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.orchestrator.recovery import recover_tasks
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock
from tests.fakes.search import FakeSearchProvider

# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)
# 오른쪽 식을 계산한 값을 ApprovalMode에 대입합니다.
ApprovalMode = Literal["approve", "deny"]


# Phase5App: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class Phase5App:
    # runtime: Runtime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    runtime: Runtime
    # chat: ChatOrchestrator 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    chat: ChatOrchestrator
    # llm: FakeLLMClient 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    llm: FakeLLMClient
    # search: FakeSearchProvider 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    search: FakeSearchProvider
    # data_root: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    data_root: Path

    # handle(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, approval.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 문자열(str).
    def handle(
        self,
        text: str,
        *,
        approval: ApprovalMode = "approve",
    ) -> str:
        # self.chat.handle_turn()의 반환값을 outcome에 대입합니다.
        outcome = self.chat.handle_turn(text)
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while outcome.pending_approval is not None and outcome.pending_tool_call is not None:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: approval == 'deny'.
            if approval == "deny":
                # self.chat.discard_pending_approval()을 호출해 작업을 수행합니다.
                self.chat.discard_pending_approval(cause="user_deny")
                # '작업을 실행하지 않았습니다.'을 반환하고 이 함수의 실행을 끝냅니다.
                return "작업을 실행하지 않았습니다."
            # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
            verdict = outcome.pending_approval
            # self.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
            ticket = self.runtime.approval_store.grant(
                verdict,
                ctx=self.chat.pending_context,  # type: ignore[arg-type]
                method=(
                    "user_typed_phrase"
                    if verdict.decision == "typed_confirm"
                    else "user_text"
                ),
            )
            # self.chat.resume_after_approval()의 반환값을 outcome에 대입합니다.
            outcome = self.chat.resume_after_approval(ticket)
        # 오른쪽 식을 계산한 값을 self._last_outcome에 대입합니다.
        self._last_outcome = outcome
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return outcome.text

    # last_task_id(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: str | None.
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def last_task_id(self) -> str | None:
        # getattr()의 반환값을 outcome에 대입합니다.
        outcome = getattr(self, "_last_outcome", None)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return None if outcome is None else outcome.task_id

    # recover_tasks(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def recover_tasks(self) -> None:
        # recover_tasks()을 호출해 작업을 수행합니다.
        recover_tasks(self.runtime.task_store, self.runtime.events)


# build_phase5_app(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, llm, max_steps, step_timeout_s, total_timeout_s, native_tool_calling_enabled,
# clock.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Phase5App.
def build_phase5_app(
    config_dir: Path,
    *,
    llm: FakeLLMClient | None = None,
    max_steps: int | None = None,
    step_timeout_s: float | None = None,
    total_timeout_s: float | None = None,
    native_tool_calling_enabled: bool = False,
    clock: Clock | None = None,
) -> Phase5App:
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = config_dir / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # Path()의 반환값을 root에 대입합니다.
    root = Path(document["paths"]["data_root"])
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: max_steps is not None.
    if max_steps is not None:
        # 오른쪽 식을 계산한 값을 document['agent']['max_steps']에 대입합니다.
        document["agent"]["max_steps"] = max_steps
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: step_timeout_s is not None.
    if step_timeout_s is not None:
        # 오른쪽 식을 계산한 값을 document['agent']['step_timeout_s']에 대입합니다.
        document["agent"]["step_timeout_s"] = step_timeout_s
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: total_timeout_s is not None.
    if total_timeout_s is not None:
        # 오른쪽 식을 계산한 값을 document['agent']['total_timeout_s']에 대입합니다.
        document["agent"]["total_timeout_s"] = total_timeout_s
    # 오른쪽 식을 계산한 값을 document['llm']['native_tool_calling_enabled']에 대입합니다.
    document["llm"]["native_tool_calling_enabled"] = native_tool_calling_enabled
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # 오른쪽 식을 계산한 값을 fake_llm에 대입합니다.
    fake_llm = llm or FakeLLMClient().reply(
        "확인했습니다.",
        usage=LLMUsage(1, 1, Decimal("0"), 1),
    )
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=clock or FrozenClock(NOW), llm=fake_llm)
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(runtime.memory_db, created_at=NOW)
    # FakeSearchProvider()의 반환값을 search에 대입합니다.
    search = FakeSearchProvider()
    # search.add_hit()을 호출해 작업을 수행합니다.
    search.add_hit(
        title="Jarvis 테스트",
        url="https://example.com/jarvis",
        snippet="Jarvis는 로컬 AI 비서입니다.",
        fetched_at=NOW,
    )
    # runtime.tool_runner.registry.tools.get()의 반환값을 web_tool에 대입합니다.
    web_tool = runtime.tool_runner.registry.tools.get("web_search")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: web_tool is not None.
    if web_tool is not None:
        # 오른쪽 식을 계산한 값을 web_tool.provider에 대입합니다.
        web_tool.provider = search  # type: ignore[attr-defined]
    # ChatOrchestrator()의 반환값을 chat에 대입합니다.
    chat = ChatOrchestrator(
        settings=runtime.config.settings,
        llm=runtime.llm,
        sessions=runtime.sessions,
        budget=runtime.budget,
        masker=runtime.masker,
        events=runtime.events,
        clock=runtime.clock,
        sleeper=runtime.sleeper,
        random=runtime.random,
        ids=runtime.ids,
        metrics=runtime.metrics,
        summarizer=runtime.summarizer,
        indexer=runtime.indexer,
        research=runtime.research,
        tool_runner=runtime.tool_runner,
        safety_gate=runtime.safety_gate,
        approval_store=runtime.approval_store,
        audit_writer=runtime.audit_writer,
        task_store=runtime.task_store,
    )
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Phase5App(
        runtime=runtime,
        chat=chat,
        llm=fake_llm,
        search=search,
        data_root=root,
    )


# golden_task_script(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: filename.
# 반환 타입 힌트: FakeLLMClient.
def golden_task_script(filename: str = "quantum-summary.md") -> FakeLLMClient:
    # summary에 문자열을 대입합니다.
    summary = (
        "핵심 요약: Jarvis는 로컬 AI 비서입니다 [1]. "
        "근거 [1] Jarvis 테스트 — https://example.com/jarvis (2026-08-11 확인). "
        "상태: 근거 부족"
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (
        FakeLLMClient()
        .call_tool("web_search", query="양자컴퓨팅")
        .call_tool(
            "create_file",
            root="notes",
            relative_path=filename,
            content=summary,
        )
        .call_tool("open_folder", root="notes", relative_path="")
        .reply(
            "검색·저장·폴더 열기를 완료했습니다.",
            usage=LLMUsage(10, 20, Decimal("0"), 1),
        )
    )


# phase5_app(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir.
# 반환 타입 힌트: Phase5App.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def phase5_app(config_dir: Path) -> Phase5App:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return build_phase5_app(config_dir)


# inject_create_file_script(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: FakeLLMClient.
def inject_create_file_script() -> FakeLLMClient:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (
        FakeLLMClient()
        .call_tool("web_search", query="양자컴퓨팅")
        .call_tool(
            "create_file",
            root="notes",
            relative_path="evil.md",
            content="injected",
        )
        .reply("done", usage=LLMUsage(1, 1, Decimal("0"), 1))
    )
