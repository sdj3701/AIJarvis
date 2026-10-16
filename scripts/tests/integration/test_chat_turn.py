# 파이썬 공부 | scripts/tests/integration/test_chat_turn.py
# chat_turn 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Integration tests for the Phase 1 write-ahead chat flow."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.cli import run_cli
from app.llm.base import LLMResponse, LLMUsage, Message, ToolSpec
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.memory.summarizer import SessionSummarizer
from app.orchestrator.loop import ChatOrchestrator
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.clock import FrozenClock

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase1
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


# EventingFakeLLM: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: FakeLLMClient.
class EventingFakeLLM(FakeLLMClient):
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: before_call.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, *, before_call: Callable[[], None] | None = None) -> None:
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__()
        # 오른쪽 식을 계산한 값을 self.before_call에 대입합니다.
        self.before_call = before_call

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
        ctx: Any,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        # prompt_version에 문자열을 대입합니다.
        prompt_version = "unversioned"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: messages and messages[0].role ==
        # 'system'.
        if messages and messages[0].role == "system":
            # 오른쪽 식을 계산한 값을 first_line에 대입합니다.
            first_line = messages[0].content.splitlines()[0]
            # 아래 함수()의 반환값을 prompt_version에 대입합니다.
            prompt_version = first_line.removeprefix("<!-- version: ").removesuffix(" -->")
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        ctx.events.emit(
            "llm.request",
            {
                "model": self.model,
                "attempt": 1,
                "prompt_tokens_est": self.count_tokens(messages),
                "prompt_version": prompt_version,
                "tool_count": 0,
                "memory_record_ids": list(ctx.memory_record_ids),
            },
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.before_call is not None.
        if self.before_call is not None:
            # self.before_call()을 호출해 작업을 수행합니다.
            self.before_call()
        # super().complete()의 반환값을 response에 대입합니다.
        response = super().complete(
            messages=messages,
            tools=tools,
            timeout_s=timeout_s,
            ctx=ctx,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_schema=response_schema,
        )
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        ctx.events.emit(
            "llm.response",
            {
                "model": response.model,
                "finish_reason": response.finish_reason,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "cost_usd": format(response.usage.cost_usd, "f"),
                "latency_ms": response.usage.latency_ms,
                "tool_call_names": [],
            },
        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return response


# config_dir(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    # 오른쪽 식을 계산한 값을 destination에 대입합니다.
    destination = tmp_path / "config"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    destination.mkdir()
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("settings", "tools", "privacy"):
        # shutil.copyfile()을 호출해 작업을 수행합니다.
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = destination / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # str()의 반환값을 document['paths']['data_root']에 대입합니다.
    document["paths"]["data_root"] = str(root)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return destination


# _runtime(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, llm.
# 반환 타입 힌트: Runtime.
def _runtime(config_dir: Path, llm: FakeLLMClient) -> Runtime:
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=FrozenClock(NOW), llm=llm)
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(runtime.memory_db, created_at=NOW)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return runtime


# _chat(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: runtime, verify_model, summarizer.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: ChatOrchestrator.
def _chat(
    runtime: Runtime,
    *,
    verify_model: Callable[[], object] | None = None,
    summarizer: SessionSummarizer | None = None,
) -> ChatOrchestrator:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ChatOrchestrator(
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
        verify_model=verify_model,
        metrics=runtime.metrics,
        summarizer=summarizer or runtime.summarizer,
    )


# _events(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: runtime.
# 반환 타입 힌트: list[dict[str, Any]].
def _events(runtime: Runtime) -> list[dict[str, Any]]:
    # records에 리스트(순서가 있고 수정 가능)을 대입합니다.
    records: list[dict[str, Any]] = []
    # 오른쪽 식을 계산한 값을 logs에 대입합니다.
    logs = runtime.config.settings.paths.data_root / "logs"
    # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
    for path in sorted(logs.glob("events-*.jsonl")):
        # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
        records.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return records


# pytest가 test_user_raw_and_event_are_flushed_before_llm_and_ids_are_bound()을 실행해 아래 상황이
# 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_user_raw_and_event_are_flushed_before_llm_and_ids_are_bound(config_dir: Path) -> None:
    # observed에 딕셔너리(키와 값의 쌍)을 대입합니다.
    observed: dict[str, bool] = {}
    # EventingFakeLLM().reply()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM().reply(
        "안녕하세요",
        usage=LLMUsage(12, 3, Decimal("0.00"), 25),
    )
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime)
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()

    # inspect_write_ahead_state(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def inspect_write_ahead_state() -> None:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert chat.session_id is not None
        # runtime.sessions.read_raw()의 반환값을 raw에 대입합니다.
        raw = runtime.sessions.read_raw(chat.session_id)
        # 오른쪽 식을 계산한 값을 observed['raw_user']에 대입합니다.
        observed["raw_user"] = len(raw.records) == 1 and raw.records[0].role == "user"
        # 오른쪽 식을 계산한 값을 observed['user_event']에 대입합니다.
        observed["user_event"] = "user.input" in [
            record["event_type"] for record in _events(runtime)
        ]

    # 오른쪽 식을 계산한 값을 llm.before_call에 대입합니다.
    llm.before_call = inspect_write_ahead_state
    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("내 전화번호는 010-1234-5678입니다")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.ok is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.text == "안녕하세요"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert observed == {"raw_user": True, "user_event": True}
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert llm.calls[0][-1].content == "내 전화번호는 010-1234-5678입니다"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.session_id is not None
    # 오른쪽 식을 계산한 값을 raw에 대입합니다.
    raw = runtime.sessions.read_raw(chat.session_id).records
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "010-1234-5678" not in raw[0].content
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [record.role for record in raw] == ["user", "assistant"]
    # 오른쪽 식을 계산한 값을 turn_events에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    turn_events = [
        record
        for record in _events(runtime)
        if record["event_type"] in {"user.input", "llm.request", "llm.response"}
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [record["event_type"] for record in turn_events] == [
        "user.input",
        "llm.request",
        "llm.response",
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert {record["request_id"] for record in turn_events} == {outcome.request_id}
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert {record["turn_id"] for record in turn_events} == {outcome.turn_id}


# pytest가 test_three_turns_keep_context_and_create_checkpoint()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_three_turns_keep_context_and_create_checkpoint(config_dir: Path) -> None:
    # EventingFakeLLM()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM()
    # for 반복문: 대상의 항목을 하나씩 index에 대입하며 아래 블록을 실행합니다.
    for index in range(3):
        # llm.reply()을 호출해 작업을 수행합니다.
        llm.reply(
            f"답변-{index}",
            usage=LLMUsage(10 + index, 2, Decimal("0.00"), 10),
        )
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime)

    # for 반복문: 대상의 항목을 하나씩 index에 대입하며 아래 블록을 실행합니다.
    for index in range(3):
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert chat.handle_turn(f"질문-{index}").text == f"답변-{index}"

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [message.content for message in llm.calls[2][-5:]] == [
        "질문-0",
        "답변-0",
        "질문-1",
        "답변-1",
        "질문-2",
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.session_id is not None
    # runtime.sessions.get_session()의 반환값을 session에 대입합니다.
    session = runtime.sessions.get_session(chat.session_id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session.turn_count == 3
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session.tokens_in == 33
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session.tokens_out == 6
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "session.checkpoint" in [record["event_type"] for record in _events(runtime)]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.metrics.p95_ms("llm.latency", window=200) == 10
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.metrics.p95_ms("turn.latency", window=200) == 0


# pytest가 test_clear_drops_prompt_history_but_keeps_raw_audit()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_clear_drops_prompt_history_but_keeps_raw_audit(config_dir: Path) -> None:
    # EventingFakeLLM().reply('첫 답').reply()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM().reply("첫 답").reply("둘째 답")
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime)
    # chat.handle_turn()을 호출해 작업을 수행합니다.
    chat.handle_turn("첫 질문")
    # chat.clear()을 호출해 작업을 수행합니다.
    chat.clear()
    # chat.handle_turn()을 호출해 작업을 수행합니다.
    chat.handle_turn("둘째 질문")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [message.role for message in llm.calls[1]] == ["system", "user"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert llm.calls[1][-1].content == "둘째 질문"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.session_id is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [record.role for record in runtime.sessions.read_raw(chat.session_id).records] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


# pytest가 test_voice_channel_is_preserved_in_raw_context_and_metrics()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_channel_is_preserved_in_raw_context_and_metrics(config_dir: Path) -> None:
    # EventingFakeLLM().reply()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM().reply("음성 답변")
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime)

    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("음성 질문", channel="voice")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.text == "음성 답변"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.session_id is not None
    # 오른쪽 식을 계산한 값을 raw에 대입합니다.
    raw = runtime.sessions.read_raw(chat.session_id).records
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [record.channel for record in raw] == ["voice", "voice"]
    # next()의 반환값을 user_event에 대입합니다.
    user_event = next(record for record in _events(runtime) if record["event_type"] == "user.input")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert user_event["payload"]["channel"] == "voice"


# pytest가 test_llm_error_becomes_user_message_raw_note_and_error_event()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_llm_error_becomes_user_message_raw_note_and_error_event(config_dir: Path) -> None:
    from app.core.errors import LLMTimeout

    # EventingFakeLLM().raise_()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM().raise_(LLMTimeout("로컬 모델 응답 시간이 초과되었습니다."))
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime)

    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn("실패 확인")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.ok is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "초과" in outcome.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.history == ()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.session_id is not None
    # 오른쪽 식을 계산한 값을 raw에 대입합니다.
    raw = runtime.sessions.read_raw(chat.session_id).records
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [record.role for record in raw] == ["user", "system_note"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert raw[-1].meta == {"status": "error", "error_type": "LLMTimeout"}
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "error" in [record["event_type"] for record in _events(runtime)]


# pytest가 test_model_verifier_runs_once_after_input_is_saved()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_model_verifier_runs_once_after_input_is_saved(config_dir: Path) -> None:
    # EventingFakeLLM().reply('첫 답').reply()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM().reply("첫 답").reply("둘째 답")
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
    calls: list[int] = []
    # chat: ChatOrchestrator 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    chat: ChatOrchestrator

    # verify(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 반환 타입 힌트: object.
    def verify() -> object:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert chat.session_id is not None
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert runtime.sessions.read_raw(chat.session_id).records[-1].role == "user"
        # 리스트 끝에 항목 하나를 추가합니다.
        calls.append(1)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return object()

    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime, verify_model=verify)
    # chat.handle_turn()을 호출해 작업을 수행합니다.
    chat.handle_turn("첫 질문")
    # chat.handle_turn()을 호출해 작업을 수행합니다.
    chat.handle_turn("둘째 질문")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert calls == [1]


# pytest가 test_end_closes_session_and_records_event()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_end_closes_session_and_records_event(config_dir: Path) -> None:
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, EventingFakeLLM())
    # _chat()의 반환값을 chat에 대입합니다.
    chat = _chat(runtime)
    # chat.start()의 반환값을 session_id에 대입합니다.
    session_id = chat.start()
    # chat.end()을 호출해 작업을 수행합니다.
    chat.end(reason="bye")

    # runtime.sessions.get_session()의 반환값을 session에 대입합니다.
    session = runtime.sessions.get_session(session_id)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert session is not None and session.end_reason == "bye"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.session_id is None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert _events(runtime)[-1]["event_type"] == "session.end"


# pytest가 test_cli_dispatches_clear_budget_help_and_bye()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cli_dispatches_clear_budget_help_and_bye(config_dir: Path) -> None:
    # summary에 문자열을 대입합니다.
    summary = (
        '{"schema_version":1,"summary":"테스트","fact_candidates":[],'
        '"corrections":[],"tags":[]}'
    )
    # 아래 함수()의 반환값을 llm에 대입합니다.
    llm = EventingFakeLLM().reply("첫 답").reply("둘째 답").reply(summary)
    # _runtime()의 반환값을 runtime에 대입합니다.
    runtime = _runtime(config_dir, llm)
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # run_cli()의 반환값을 exit_code에 대입합니다.
    exit_code = run_cli(
        input_stream=StringIO("/help\n첫 질문\n/clear\n/budget\n둘째 질문\n/bye\n"),
        output_stream=output,
        chat=_chat(runtime),
    )

    # output.getvalue()의 반환값을 rendered에 대입합니다.
    rendered = output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "/clear" in rendered
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "첫 답" in rendered and "둘째 답" in rendered
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "raw 기록은 유지" in rendered
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "오늘: $0.00/1.00" in rendered
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [message.role for message in llm.calls[1]] == ["system", "user"]
