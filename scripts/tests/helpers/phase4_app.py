# 파이썬 공부 | scripts/tests/helpers/phase4_app.py
# 통합 테스트에서 사용할 앱과 임시 실행 환경을 구성합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Shared Phase 4 test application fixture."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.llm.base import LLMUsage
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.telemetry.audit import read_audit_records
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock

# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


# Phase4App: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class Phase4App:
    # runtime: Runtime 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    runtime: Runtime
    # chat: ChatOrchestrator 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    chat: ChatOrchestrator
    # llm: FakeLLMClient 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    llm: FakeLLMClient
    # data_root: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    data_root: Path

    # say(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: 문자열(str).
    def say(self, text: str) -> str:
        # self.chat.handle_turn()의 반환값을 outcome에 대입합니다.
        outcome = self.chat.handle_turn(text)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if outcome.pending_approval is not None and outcome.pending_tool_call is not None:
            # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
            verdict = outcome.pending_approval
            # self.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
            ticket = self.runtime.approval_store.grant(
                verdict,
                ctx=self.chat.pending_context,  # type: ignore[arg-type]
                method="user_text",
            )
            # self.chat.resume_after_approval()의 반환값을 resumed에 대입합니다.
            resumed = self.chat.resume_after_approval(ticket)
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return resumed.text
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return outcome.text

    # audit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: list[dict[str, Any]].
    def audit(self) -> list[dict[str, Any]]:
        # 오른쪽 식을 계산한 값을 logs에 대입합니다.
        logs = self.data_root / "logs"
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return read_audit_records(logs)


# snapshot_tree(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: root.
# 반환 타입 힌트: dict[str, int].
def snapshot_tree(root: Path) -> dict[str, int]:
    # excluded_prefixes에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    excluded_prefixes = ("logs\\", "logs/", "memory\\raw", "memory/raw", "state\\", "state/")
    # result에 딕셔너리(키와 값의 쌍)을 대입합니다.
    result: dict[str, int] = {}
    # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
    for path in root.rglob("*"):
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not path.is_file().
        if not path.is_file():
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # str(path.relative_to(root)).replace()의 반환값을 relative에 대입합니다.
        relative = str(path.relative_to(root)).replace("/", "\\")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if any(relative.startswith(prefix) for prefix in excluded_prefixes):
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'jarvis.sqlite3' in relative.
        if "jarvis.sqlite3" in relative:
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 오른쪽 식을 계산한 값을 result[relative]에 대입합니다.
        result[relative] = path.stat().st_size
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return result


# build_phase4_app(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir.
# 반환 타입 힌트: Phase4App.
def build_phase4_app(config_dir: Path) -> Phase4App:
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = config_dir / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # Path()의 반환값을 root에 대입합니다.
    root = Path(document["paths"]["data_root"])
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)
    # FakeLLMClient().reply()의 반환값을 llm에 대입합니다.
    llm = FakeLLMClient().reply(
        "확인했습니다.",
        usage=LLMUsage(1, 1, Decimal("0"), 1),
    )
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(runtime.memory_db, created_at=NOW)
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
    )
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Phase4App(runtime=runtime, chat=chat, llm=llm, data_root=root)


# phase4_app(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir.
# 반환 타입 힌트: Phase4App.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def phase4_app(config_dir: Path) -> Phase4App:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return build_phase4_app(config_dir)


# read_lines(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: name.
# 반환 타입 힌트: list[str].
def read_lines(name: str) -> list[str]:
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = REPOSITORY_ROOT / "scripts" / "tests" / "data" / "paths" / name
    # lines에 리스트(순서가 있고 수정 가능)을 대입합니다.
    lines: list[str] = []
    # for 반복문: 대상의 항목을 하나씩 line에 대입하며 아래 블록을 실행합니다.
    for line in path.read_text(encoding="utf-8").splitlines():
        # line.strip()의 반환값을 stripped에 대입합니다.
        stripped = line.strip()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stripped and (not
        # stripped.startswith('#')).
        if stripped and not stripped.startswith("#"):
            # 리스트 끝에 항목 하나를 추가합니다.
            lines.append(stripped)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return lines
