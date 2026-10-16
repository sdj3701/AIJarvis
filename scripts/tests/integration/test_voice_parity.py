# 파이썬 공부 | scripts/tests/integration/test_voice_parity.py
# voice_parity 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Integration tests for voice/text parity, safety boundaries, and privacy filtering."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.errors import ApprovalMismatch, JarvisError
from app.llm.base import LLMUsage
from app.llm.fake import FakeLLMClient
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.safety.approval import ApprovalTicket
from app.voice.base import Transcript
from app.voice.controller import MISHEARD_TEXT, VoiceController
from app.wiring import Runtime, build
from scripts.bootstrap import create_tree
from tests.fakes.audio import FakeTTSEngine
from tests.fakes.clock import FrozenClock

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase7

# timezone()의 반환값을 KST에 대입합니다.
KST = timezone(timedelta(hours=9), name="KST")
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=KST)


# FakeListenerWithCommands: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeListenerWithCommands:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: commands, barge_ins.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        commands: list[str | Transcript],
        *,
        barge_ins: list[bool] | None = None,
    ) -> None:
        # list()의 반환값을 self._commands에 대입합니다.
        self._commands = list(commands)
        # list()의 반환값을 self._barge_ins에 대입합니다.
        self._barge_ins = list(barge_ins or [])
        # self.wakes에 숫자 등 고정된 값을 대입합니다.
        self.wakes = 0

    # await_turn_start(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # *args는 추가 위치 인자를 튜플로 모읍니다.
    # **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def await_turn_start(self, *args: Any, **kwargs: Any) -> Any:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del args, kwargs
        from app.voice.controller import TurnStart

        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self.wakes += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return TurnStart("standalone", None)

    # listen_for_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # *args는 추가 위치 인자를 튜플로 모읍니다.
    # **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: Transcript.
    def listen_for_command(self, *args: Any, **kwargs: Any) -> Transcript:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del args, kwargs
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self._commands.
        if not self._commands:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return Transcript("", "ko", 0, None)
        # self._commands.pop()의 반환값을 item에 대입합니다.
        item = self._commands.pop(0)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(item, Transcript).
        if isinstance(item, Transcript):
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return item
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Transcript(item, "ko", 800, 0.9, -0.2, 0.01)

    # wait_for_barge_in(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: speech_done, spoken_text.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def wait_for_barge_in(self, speech_done: Any, *, spoken_text: str = "") -> bool:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del speech_done, spoken_text
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return self._barge_ins.pop(0) if self._barge_ins else False


# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


# SafeFakeLLMClient: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: FakeLLMClient.
class SafeFakeLLMClient(FakeLLMClient):
    # complete(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages, tools, timeout_s, ctx, temperature, max_output_tokens.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def complete(
        self,
        *,
        messages: Any,
        tools: Any = (),
        timeout_s: float,
        ctx: Any,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> Any:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.script.
        if not self.script:
            from app.llm.base import LLMResponse, LLMUsage
            # summary_json에 문자열을 대입합니다.
            summary_json = (
                '{"schema_version": 1, "summary": "대화 요약", '
                '"fact_candidates": [], "corrections": []}'
            )
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return LLMResponse(
                text=summary_json,
                tool_calls=(),
                usage=LLMUsage(0, 0, Decimal("0"), 0),
                model=self.model,
                finish_reason="stop",
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return super().complete(
            messages=messages,
            tools=tools,
            timeout_s=timeout_s,
            ctx=ctx,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_schema=response_schema,
        )


# _setup_test_app(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, replies, tool_calls.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[Runtime, ChatOrchestrator, FakeLLMClient].
def _setup_test_app(
    config_dir: Path,
    *,
    replies: list[str] | None = None,
    tool_calls: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[Runtime, ChatOrchestrator, FakeLLMClient]:
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = config_dir / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # Path()의 반환값을 root에 대입합니다.
    root = Path(document["paths"]["data_root"])
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)

    # SafeFakeLLMClient()의 반환값을 llm에 대입합니다.
    llm = SafeFakeLLMClient()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_calls.
    if tool_calls:
        # for 반복문: 대상의 항목을 하나씩 (name, args)에 대입하며 아래 블록을 실행합니다.
        for name, args in tool_calls:
            # llm.call_tool()을 호출해 작업을 수행합니다.
            llm.call_tool(name, **args)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: replies.
    elif replies:
        # for 반복문: 대상의 항목을 하나씩 rep에 대입하며 아래 블록을 실행합니다.
        for rep in replies:
            # llm.reply()을 호출해 작업을 수행합니다.
            llm.reply(rep, usage=LLMUsage(10, 10, Decimal("0"), 1))
    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
    else:
        # llm.reply()을 호출해 작업을 수행합니다.
        llm.reply("확인했습니다.", usage=LLMUsage(10, 10, Decimal("0"), 1))

    # FrozenClock()의 반환값을 clock에 대입합니다.
    clock = FrozenClock(NOW)
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(config_dir, clock=clock, llm=llm)
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
    return runtime, chat, llm


# pytest가 test_voice_text_turn_parity()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_text_turn_parity(config_dir: Path) -> None:
    """Check that identical text received via voice and text yields equivalent outcomes."""
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat, _)에 나누어 담습니다.
    runtime, chat, _ = _setup_test_app(
        config_dir,
        replies=["안녕하세요. 무엇을 도와드릴까요?", "안녕하세요. 무엇을 도와드릴까요?"],
    )

    # chat.handle_turn()의 반환값을 text_outcome에 대입합니다.
    text_outcome = chat.handle_turn("안녕하세요", channel="text")
    # chat.handle_turn()의 반환값을 voice_outcome에 대입합니다.
    voice_outcome = chat.handle_turn("안녕하세요", channel="voice")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert text_outcome.ok is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert voice_outcome.ok is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert text_outcome.text == voice_outcome.text

    # 오른쪽 식을 계산한 값을 records에 대입합니다.
    records = runtime.sessions.read_raw(chat.session_id).records
    # 오른쪽 식을 계산한 값을 channels에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    channels = [r.channel for r in records if r.role == "user"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert channels == ["text", "voice"]


# pytest가 test_voice_controller_flow_parity()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_controller_flow_parity(config_dir: Path) -> None:
    """Check end-to-end voice flow via VoiceController invoking ChatOrchestrator."""
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat, _)에 나누어 담습니다.
    runtime, chat, _ = _setup_test_app(
        config_dir,
        replies=["메모장을 실행했습니다."],
    )

    # FakeListenerWithCommands()의 반환값을 listener에 대입합니다.
    listener = FakeListenerWithCommands(["메모장 열어줘"])
    # FakeTTSEngine()의 반환값을 tts에 대입합니다.
    tts = FakeTTSEngine()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # VoiceController()의 반환값을 controller에 대입합니다.
    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,
        masker=runtime.masker,
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=200,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=output,
    )

    # controller.run()의 반환값을 exit_code에 대입합니다.
    exit_code = controller.run(max_interactions=1)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert listener.wakes == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "무엇을 도와드릴까요." in tts.spoken
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.has_pending_approval()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any("앱 실행" in s for s in tts.spoken)
    # output.getvalue()의 반환값을 output_val에 대입합니다.
    output_val = output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[Whisper 확정] 메모장 열어줘" in output_val or "인식: 메모장 열어줘" in output_val


# pytest가 test_voice_high_risk_approval_blocked()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_high_risk_approval_blocked(config_dir: Path) -> None:
    """Verify that a high-risk tool approval is strictly blocked on the voice channel."""
    # create_args에 딕셔너리(키와 값의 쌍)을 대입합니다.
    create_args = {
        "root": "notes",
        "relative_path": "test.md",
        "content": "내용",
        "overwrite": True,
    }
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat, _llm)에 나누어 담습니다.
    runtime, chat, _llm = _setup_test_app(
        config_dir,
        tool_calls=[
            ("create_file", create_args),
            ("create_file", create_args),
        ],
    )

    # 1. Calling high risk tool directly on voice channel is immediately blocked
    # chat.handle_turn()의 반환값을 voice_outcome에 대입합니다.
    voice_outcome = chat.handle_turn("파일 덮어써서 만들어줘", channel="voice")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "음성 채널에서는 high 위험 작업을 실행할 수 없습니다" in voice_outcome.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert voice_outcome.pending_approval is None

    # 2. Calling on text channel produces pending approval
    # chat.handle_turn()의 반환값을 text_outcome에 대입합니다.
    text_outcome = chat.handle_turn("파일 덮어써서 만들어줘", channel="text")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert text_outcome.pending_approval is not None
    # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
    verdict = text_outcome.pending_approval
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict.risk == "high"

    # 3. Attempting to grant approval for high risk on voice channel fails
    from dataclasses import replace

    # replace()의 반환값을 voice_ctx에 대입합니다.
    voice_ctx = replace(chat.pending_context, channel="voice")  # type: ignore[arg-type]
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(
        ApprovalMismatch,
        match="음성 채널에서는 high 위험 작업을 승인할 수 없습니다",
    ):
        # runtime.approval_store.grant()을 호출해 작업을 수행합니다.
        runtime.approval_store.grant(
            verdict,
            ctx=voice_ctx,
            method="user_typed_phrase",
        )

    # 4. Text channel typed phrase approval succeeds
    # runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = runtime.approval_store.grant(
        verdict,
        ctx=chat.pending_context,  # type: ignore[arg-type]
        method="user_typed_phrase",
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(ticket, ApprovalTicket)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ticket.channel == "text"


# pytest가 test_voice_sensitive_info_not_spoken()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_sensitive_info_not_spoken(config_dir: Path) -> None:
    """Verify that secrets and PII_HIGH in response text are never spoken by TTS."""
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat, _)에 나누어 담습니다.
    runtime, chat, _ = _setup_test_app(
        config_dir,
        replies=["API 키는 sk-ant-api03-1234567890abcdef1234567890abcdef 입니다."],
    )

    # FakeListenerWithCommands()의 반환값을 listener에 대입합니다.
    listener = FakeListenerWithCommands(["키 보여줘"])
    # FakeTTSEngine()의 반환값을 tts에 대입합니다.
    tts = FakeTTSEngine()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # VoiceController()의 반환값을 controller에 대입합니다.
    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,
        masker=runtime.masker,
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=200,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=output,
    )

    # controller.run()을 호출해 작업을 수행합니다.
    controller.run(max_interactions=1)

    # for 반복문: 대상의 항목을 하나씩 spoken에 대입하며 아래 블록을 실행합니다.
    for spoken in tts.spoken:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "sk-ant" not in spoken
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "1234567890" not in spoken

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any("민감한 내용이 포함되어 화면으로만 표시합니다" in s for s in tts.spoken)


# pytest가 test_voice_barge_in_cancellation()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_barge_in_cancellation(config_dir: Path) -> None:
    """Verify that speaking can be interrupted and cancelled by wake detection."""
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat, _)에 나누어 담습니다.
    runtime, chat, _ = _setup_test_app(
        config_dir,
        replies=["첫 번째 매우 긴 설명 답변입니다.", "두 번째 질문에 대한 답변입니다."],
    )

    # FakeListenerWithCommands()의 반환값을 listener에 대입합니다.
    listener = FakeListenerWithCommands(
        ["첫 질문", "두 번째 질문"],
        barge_ins=[True, False],
    )
    # FakeTTSEngine()의 반환값을 tts에 대입합니다.
    tts = FakeTTSEngine()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # VoiceController()의 반환값을 controller에 대입합니다.
    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,
        masker=runtime.masker,
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=200,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=output,
    )

    # controller.run()을 호출해 작업을 수행합니다.
    controller.run(max_interactions=2)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tts.cancelled >= 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[답변 중단]" in output.getvalue()


# pytest가 test_voice_quality_guard_rejects_garbage()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_quality_guard_rejects_garbage(config_dir: Path) -> None:
    """Verify that empty or low-confidence STT results do not reach Orchestrator."""
    # 언패킹: 오른쪽 결과를 순서대로 (runtime, chat, _)에 나누어 담습니다.
    runtime, chat, _ = _setup_test_app(config_dir, replies=["정상 답변"])

    # First command is empty transcript, second is valid command
    # Transcript()의 반환값을 garbage_transcript에 대입합니다.
    garbage_transcript = Transcript("", "ko", 100, None)
    # Transcript()의 반환값을 valid_transcript에 대입합니다.
    valid_transcript = Transcript("정상 질문", "ko", 800, 0.9, -0.2, 0.01)

    # FakeListenerWithCommands()의 반환값을 listener에 대입합니다.
    listener = FakeListenerWithCommands([garbage_transcript, valid_transcript])
    # FakeTTSEngine()의 반환값을 tts에 대입합니다.
    tts = FakeTTSEngine()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()

    # VoiceController()의 반환값을 controller에 대입합니다.
    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,
        masker=runtime.masker,
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=200,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=output,
    )

    # controller.run()을 호출해 작업을 수행합니다.
    controller.run(max_interactions=1)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert MISHEARD_TEXT in tts.spoken
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "정상 답변" in tts.spoken


# pytest가 test_voice_device_failure_isolated()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_device_failure_isolated(config_dir: Path) -> None:
    """Verify that microphone stream failure does not crash or corrupt database state."""
    # 언패킹: 오른쪽 결과를 순서대로 (_runtime, chat, _)에 나누어 담습니다.
    _runtime, chat, _ = _setup_test_app(config_dir)

    from app.voice.microphone import MicrophoneStream

    # BrokenBackend: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class BrokenBackend:
        # devices(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 어떤 타입이든 허용(Any).
        def devices(self) -> Any:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ()

        # default_input(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 어떤 타입이든 허용(Any).
        def default_input(self) -> Any:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

    # MicrophoneStream()의 반환값을 mic에 대입합니다.
    mic = MicrophoneStream("none", backend=BrokenBackend())  # type: ignore[arg-type]
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisError, match="설정한 마이크를 찾지 못했습니다"), mic:
        # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
        pass

    # Chat orchestrator still works reliably via text
    # chat.handle_turn()의 반환값을 turn에 대입합니다.
    turn = chat.handle_turn("텍스트로 대화", channel="text")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert turn.ok is True
