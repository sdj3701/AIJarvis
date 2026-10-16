# 파이썬 공부 | scripts/tests/unit/test_voice_controller.py
# voice_controller 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for wake word to acknowledgement to voice chat orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from threading import Event
from typing import Any

import pytest

from app.orchestrator.loop import TurnOutcome
from app.telemetry.masking import LogMasker
from app.voice.barge_in_gate import BargeInGateDecision
from app.voice.base import AudioFrame, Transcript
from app.voice.controller import LocalVoiceListener, VoiceController
from app.voice.microphone import SpeechCapturePolicy
from app.voice.stt import RecognitionUpdate
from tests.fakes.clock import FrozenClock

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase7
# datetime()의 반환값을 NOW에 대입합니다.
NOW = datetime(2026, 8, 11, 21, 0, tzinfo=timezone(timedelta(hours=9)))


# FakeListener: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeListener:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: commands, barge_ins, inline_commands.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        commands: list[str],
        *,
        barge_ins: list[bool] | None = None,
        inline_commands: list[str] | None = None,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self.commands에 대입합니다.
        self.commands = commands
        # 오른쪽 식을 계산한 값을 self.barge_ins에 대입합니다.
        self.barge_ins = barge_ins or []
        # 오른쪽 식을 계산한 값을 self.inline_commands에 대입합니다.
        self.inline_commands = inline_commands or []
        # self.barge_texts에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.barge_texts: list[str] = []
        # self.wakes에 숫자 등 고정된 값을 대입합니다.
        self.wakes = 0

    # await_turn_start(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def await_turn_start(self) -> Any:
        from app.voice.controller import TurnStart

        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self.wakes += 1
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.inline_commands.
        if self.inline_commands:
            # self.inline_commands.pop()의 반환값을 text에 대입합니다.
            text = self.inline_commands.pop(0)
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return TurnStart(
                "inline_command",
                Transcript(text, "ko", 800, 0.9, -0.2, 0.01),
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return TurnStart("standalone", None)

    # wait_for_wake(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Transcript.
    def wait_for_wake(self) -> Transcript:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self.wakes += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Transcript("자비스", "ko", 500, None)

    # listen_for_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Transcript.
    def listen_for_command(self) -> Transcript:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Transcript(self.commands.pop(0), "ko", 800, None)

    # wait_for_barge_in(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: speech_done, spoken_text.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def wait_for_barge_in(self, speech_done: Event, *, spoken_text: str = "") -> bool:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del speech_done
        # 리스트 끝에 항목 하나를 추가합니다.
        self.barge_texts.append(spoken_text)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return self.barge_ins.pop(0) if self.barge_ins else False


# FakeTTS: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeTTS:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.spoken에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.spoken: list[str] = []
        # self.closed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = False
        # self.cancelled에 숫자 등 고정된 값을 대입합니다.
        self.cancelled = 0

    # speak(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def speak(self, text: str, *, ctx: Any = None) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del ctx
        # 리스트 끝에 항목 하나를 추가합니다.
        self.spoken.append(text)

    # cancel(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def cancel(self) -> None:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self.cancelled += 1

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # self.closed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = True


# FakeChat: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeChat:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: answer.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, answer: str) -> None:
        # 오른쪽 식을 계산한 값을 self.answer에 대입합니다.
        self.answer = answer
        # self.calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.calls: list[tuple[str, str]] = []
        # self.ended을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.ended = False

    # handle_turn(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, channel.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: TurnOutcome.
    def handle_turn(self, text: str, *, channel: str = "text") -> TurnOutcome:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.calls.append((text, channel))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return TurnOutcome(True, self.answer, "req", "turn", 1, 1, Decimal("0"))

    # end(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: reason.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def end(self, *, reason: str = "bye") -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del reason
        # self.ended을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.ended = True


# FakeEvents: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeEvents:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.types에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.types: list[str] = []
        # self.records에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.records: list[tuple[str, Any]] = []

    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Any) -> None:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.types.append(event_type)
        # 리스트 끝에 항목 하나를 추가합니다.
        self.records.append((event_type, payload))


# FakeStreamingRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeStreamingRecognizer:
    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm.
    # 반환 타입 힌트: RecognitionUpdate.
    def feed(self, pcm: bytes) -> RecognitionUpdate:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del pcm
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("자 비스", True)

    # finish(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: RecognitionUpdate.
    def finish(self) -> RecognitionUpdate:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("", True)


# FakeStreamingSTT: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeStreamingSTT:
    # stream(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrases.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: FakeStreamingRecognizer.
    def stream(self, *, phrases: Any = None) -> FakeStreamingRecognizer:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del phrases
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return FakeStreamingRecognizer()


# PartialStreamingRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class PartialStreamingRecognizer:
    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm.
    # 반환 타입 힌트: RecognitionUpdate.
    def feed(self, pcm: bytes) -> RecognitionUpdate:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del pcm
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("자비스", False)

    # finish(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: RecognitionUpdate.
    def finish(self) -> RecognitionUpdate:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("", True)


# PartialStreamingSTT: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class PartialStreamingSTT:
    # stream(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrases.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: PartialStreamingRecognizer.
    def stream(self, *, phrases: Any = None) -> PartialStreamingRecognizer:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del phrases
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return PartialStreamingRecognizer()


# CompletingPartialRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CompletingPartialRecognizer:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: speech_done.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, speech_done: Event) -> None:
        # 오른쪽 식을 계산한 값을 self._speech_done에 대입합니다.
        self._speech_done = speech_done

    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm.
    # 반환 타입 힌트: RecognitionUpdate.
    def feed(self, pcm: bytes) -> RecognitionUpdate:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del pcm
        # self._speech_done.set()을 호출해 작업을 수행합니다.
        self._speech_done.set()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("자비스", False)

    # finish(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: RecognitionUpdate.
    def finish(self) -> RecognitionUpdate:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("", True)


# CompletingPartialSTT: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CompletingPartialSTT:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: speech_done.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, speech_done: Event) -> None:
        # 오른쪽 식을 계산한 값을 self._speech_done에 대입합니다.
        self._speech_done = speech_done

    # stream(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrases.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: CompletingPartialRecognizer.
    def stream(self, *, phrases: Any = None) -> CompletingPartialRecognizer:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del phrases
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CompletingPartialRecognizer(self._speech_done)


# CompletingSelfFinalRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CompletingSelfFinalRecognizer:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: speech_done.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, speech_done: Event) -> None:
        # 오른쪽 식을 계산한 값을 self._speech_done에 대입합니다.
        self._speech_done = speech_done

    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm.
    # 반환 타입 힌트: RecognitionUpdate.
    def feed(self, pcm: bytes) -> RecognitionUpdate:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del pcm
        # self._speech_done.set()을 호출해 작업을 수행합니다.
        self._speech_done.set()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("자비스 프로젝트", True)

    # finish(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: RecognitionUpdate.
    def finish(self) -> RecognitionUpdate:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("", True)


# CompletingSelfFinalSTT: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CompletingSelfFinalSTT:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: speech_done.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, speech_done: Event) -> None:
        # 오른쪽 식을 계산한 값을 self._speech_done에 대입합니다.
        self._speech_done = speech_done

    # stream(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrases.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: CompletingSelfFinalRecognizer.
    def stream(self, *, phrases: Any = None) -> CompletingSelfFinalRecognizer:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del phrases
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return CompletingSelfFinalRecognizer(self._speech_done)


# FakeCommandSTT: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeCommandSTT:
    # active_device에 문자열을 대입합니다.
    active_device = "cuda"
    # fallback_reason을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    fallback_reason: str | None = None

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: transcript.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, transcript: Transcript | None = None) -> None:
        # 오른쪽 식을 계산한 값을 self.transcript에 대입합니다.
        self.transcript = transcript or Transcript("질문", "ko", 1_000, 0.8, -0.2, 0.01)
        # self.frames에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        self.frames: tuple[AudioFrame, ...] = ()

    # transcribe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frames, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Transcript.
    def transcribe(self, frames: Any, *, ctx: Any = None) -> Transcript:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del ctx
        # tuple()의 반환값을 self.frames에 대입합니다.
        self.frames = tuple(frames)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.transcript


# FakeMicrophone: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeMicrophone:
    # overflows에 숫자 등 고정된 값을 대입합니다.
    overflows = 0

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self._sent을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._sent = False

    # __enter__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: FakeMicrophone.
    def __enter__(self) -> FakeMicrophone:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # next_frame(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: AudioFrame | None.
    def next_frame(self, *, timeout_s: float = 0.5) -> AudioFrame | None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del timeout_s
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._sent.
        if self._sent:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # self._sent을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self._sent = True
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return AudioFrame((4_000).to_bytes(2, "little", signed=True) * 160, 16_000)

    # __exit__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: exc_type, exc_value, traceback.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del exc_type, exc_value, traceback


# OpenBargeInGate: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class OpenBargeInGate:
    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frame.
    # 반환 타입 힌트: BargeInGateDecision.
    def feed(self, frame: AudioFrame) -> BargeInGateDecision:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return BargeInGateDecision(
            frames=(frame,),
            level_dbfs=frame.rms_dbfs,
            baseline_dbfs=-60,
            voice=True,
            onset=True,
            open=True,
            reset_recognizer=False,
        )


# _open_barge_in_gate(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: OpenBargeInGate.
def _open_barge_in_gate() -> OpenBargeInGate:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return OpenBargeInGate()


# CompletingClosedBargeInGate: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CompletingClosedBargeInGate:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: speech_done.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, speech_done: Event) -> None:
        # 오른쪽 식을 계산한 값을 self._speech_done에 대입합니다.
        self._speech_done = speech_done

    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frame.
    # 반환 타입 힌트: BargeInGateDecision.
    def feed(self, frame: AudioFrame) -> BargeInGateDecision:
        # self._speech_done.set()을 호출해 작업을 수행합니다.
        self._speech_done.set()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return BargeInGateDecision(
            frames=(),
            level_dbfs=frame.rms_dbfs,
            baseline_dbfs=-30,
            voice=False,
            onset=False,
            open=False,
            reset_recognizer=False,
        )


# FailOnFeedRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FailOnFeedRecognizer:
    # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm.
    # 반환 타입 힌트: RecognitionUpdate.
    def feed(self, pcm: bytes) -> RecognitionUpdate:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del pcm
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise AssertionError("closed gate must not feed the recognizer")

    # finish(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: RecognitionUpdate.
    def finish(self) -> RecognitionUpdate:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return RecognitionUpdate("", True)


# FailOnFeedSTT: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FailOnFeedSTT:
    # stream(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrases.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: FailOnFeedRecognizer.
    def stream(self, *, phrases: Any = None) -> FailOnFeedRecognizer:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del phrases
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return FailOnFeedRecognizer()


# _masker(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: LogMasker.
def _masker() -> LogMasker:
    from app.config.models import MaskPolicy

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return LogMasker([], MaskPolicy(replacement="[{label}]", keep_tail={}))


# pytest가 test_wake_word_speaks_exact_acknowledgement_then_answer()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_wake_word_speaks_exact_acknowledgement_then_answer() -> None:
    # FakeListener()의 반환값을 listener에 대입합니다.
    listener = FakeListener(["대한민국 수도는 어디야"])
    # FakeTTS()의 반환값을 tts에 대입합니다.
    tts = FakeTTS()
    # FakeChat()의 반환값을 chat에 대입합니다.
    chat = FakeChat("서울입니다.")
    # FakeEvents()의 반환값을 events에 대입합니다.
    events = FakeEvents()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # VoiceController()의 반환값을 controller에 대입합니다.
    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,  # type: ignore[arg-type]
        masker=_masker(),
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=400,
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert controller.run(max_interactions=1) == 0

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tts.spoken == ["무엇을 도와드릴까요.", "서울입니다."]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.calls == [("대한민국 수도는 어디야", "voice")]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "인식: 대한민국 수도는 어디야" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.types == ["tts.result", "tts.result"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.ended is True and tts.closed is True


# pytest가 test_spoken_exit_does_not_call_llm()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_spoken_exit_does_not_call_llm() -> None:
    # FakeTTS()의 반환값을 tts에 대입합니다.
    tts = FakeTTS()
    # FakeChat()의 반환값을 chat에 대입합니다.
    chat = FakeChat("사용되면 안 됨")
    # VoiceController()의 반환값을 controller에 대입합니다.
    controller = VoiceController(
        listener=FakeListener(["종료"]),  # type: ignore[arg-type]
        tts=tts,
        chat=chat,  # type: ignore[arg-type]
        masker=_masker(),
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=400,
        events=FakeEvents(),
        clock=FrozenClock(NOW),
        output_stream=StringIO(),
    )

    # controller.run()을 호출해 작업을 수행합니다.
    controller.run()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.calls == []
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tts.spoken == ["무엇을 도와드릴까요.", "안전하게 종료합니다."]


# pytest가 test_answer_barge_in_cancels_tts_and_accepts_next_question_without_new_wake()을 실행해
# 아래
# 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_answer_barge_in_cancels_tts_and_accepts_next_question_without_new_wake() -> None:
    # FakeListener()의 반환값을 listener에 대입합니다.
    listener = FakeListener(
        ["첫 번째 질문", "두 번째 질문"],
        barge_ins=[True, False],
    )
    # FakeTTS()의 반환값을 tts에 대입합니다.
    tts = FakeTTS()
    # FakeChat()의 반환값을 chat에 대입합니다.
    chat = FakeChat("답변입니다.")
    # FakeEvents()의 반환값을 events에 대입합니다.
    events = FakeEvents()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # VoiceController()의 반환값을 controller에 대입합니다.
    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,  # type: ignore[arg-type]
        masker=_masker(),
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=400,
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert controller.run(max_interactions=2) == 0

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert listener.wakes == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.calls == [("첫 번째 질문", "voice"), ("두 번째 질문", "voice")]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tts.spoken == [
        "무엇을 도와드릴까요.",
        "답변입니다.",
        "무엇을 도와드릴까요.",
        "답변입니다.",
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tts.cancelled == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert listener.barge_texts == ["답변입니다.", "답변입니다."]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[1][1]["state"] == "interrupted"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[답변 중단] 새 질문을 받을 준비를 합니다." in output.getvalue()


# pytest가 test_voice_and_once_modes_are_mutually_exclusive()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_voice_and_once_modes_are_mutually_exclusive() -> None:
    from app.__main__ import _parser

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(SystemExit):
        # _parser().parse_args()을 호출해 작업을 수행합니다.
        _parser().parse_args(["--voice", "--once", "질문"])


# pytest가 test_local_listener_accepts_spaced_wake_word_and_emits_mic_state()을 실행해 아래 상황이
# 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_local_listener_accepts_spaced_wake_word_and_emits_mic_state() -> None:
    # FakeEvents()의 반환값을 events에 대입합니다.
    events = FakeEvents()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # FakeCommandSTT()의 반환값을 command_stt에 대입합니다.
    command_stt = FakeCommandSTT(Transcript("자비스", "ko", 500, 0.9, -0.2, 0.01))
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=FakeStreamingSTT(),  # type: ignore[arg-type]
        command_stt=command_stt,  # type: ignore[arg-type]
        microphone_factory=FakeMicrophone,  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 250, 250, 15_000),
        barge_in_gate_factory=_open_barge_in_gate,  # type: ignore[arg-type]
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # listener.await_turn_start()의 반환값을 turn에 대입합니다.
    turn = listener.await_turn_start()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert turn.mode == "standalone"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert turn.command is None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.types[0] == "voice.recording"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[0][1]["state"] == "started"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[마이크 켜짐]" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "(장치: 테스트 마이크)" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[STT 확정] 자 비스" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[호출 확정]" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[마이크 꺼짐]" in output.getvalue()


# pytest가 test_wake_session_stops_vosk_after_wake_so_follow_on_words_are_not_forced()을 실행해
# 아래 상황이
# 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_wake_session_stops_vosk_after_wake_so_follow_on_words_are_not_forced() -> None:
    # OneShotWakeRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class OneShotWakeRecognizer:
        # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 별도 결과 없음(None).
        def __init__(self) -> None:
            # self.feeds에 숫자 등 고정된 값을 대입합니다.
            self.feeds = 0

        # feed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 입력: pcm.
        # 반환 타입 힌트: RecognitionUpdate.
        def feed(self, pcm: bytes) -> RecognitionUpdate:
            # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
            # 아닙니다.
            del pcm
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            self.feeds += 1
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.feeds == 1.
            if self.feeds == 1:
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return RecognitionUpdate("자비스", True)
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise AssertionError("Vosk must not receive audio after wake is confirmed")

        # finish(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: RecognitionUpdate.
        def finish(self) -> RecognitionUpdate:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return RecognitionUpdate("", True)

    # OneShotWakeSTT: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class OneShotWakeSTT:
        # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 별도 결과 없음(None).
        def __init__(self) -> None:
            # OneShotWakeRecognizer()의 반환값을 self.recognizer에 대입합니다.
            self.recognizer = OneShotWakeRecognizer()

        # stream(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 입력: phrases.
        # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
        # 반환 타입 힌트: OneShotWakeRecognizer.
        def stream(self, *, phrases: Any = None) -> OneShotWakeRecognizer:
            # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
            # 아닙니다.
            del phrases
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self.recognizer

    # _audio_frame()의 반환값을 loud에 대입합니다.
    loud = _audio_frame(4_000)
    # _audio_frame()의 반환값을 quiet에 대입합니다.
    quiet = _audio_frame(0)
    # frames에 리스트(순서가 있고 수정 가능)을 대입합니다.
    frames = [loud, loud, quiet, quiet, quiet, quiet]
    # FakeCommandSTT()의 반환값을 command_stt에 대입합니다.
    command_stt = FakeCommandSTT(
        Transcript("자비스 가나다", "ko", 1_500, 0.9, -0.2, 0.01)
    )
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # OneShotWakeSTT()의 반환값을 wake_stt에 대입합니다.
    wake_stt = OneShotWakeSTT()
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=wake_stt,  # type: ignore[arg-type]
        command_stt=command_stt,  # type: ignore[arg-type]
        microphone_factory=lambda: SequenceMicrophone(frames),  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 500, 250, 15_000),
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=FakeEvents(),
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # listener.await_turn_start()의 반환값을 turn에 대입합니다.
    turn = listener.await_turn_start()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert wake_stt.recognizer.feeds == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert turn.mode == "inline_command"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert turn.command is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert turn.command.text == "가나다"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[호출 확정]" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[한 문장 명령] 가나다" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert output.getvalue().count("[STT 확정] 자비스") == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[STT 확정] 자비스 자비스" not in output.getvalue()


# pytest가 test_inline_wake_command_skips_acknowledgement()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_inline_wake_command_skips_acknowledgement() -> None:
    # FakeListener()의 반환값을 listener에 대입합니다.
    listener = FakeListener([], inline_commands=["수돗물의 성분에 대해서 알려줘"])
    # FakeTTS()의 반환값을 tts에 대입합니다.
    tts = FakeTTS()
    # FakeChat()의 반환값을 chat에 대입합니다.
    chat = FakeChat("수돗물에는 미네랄이 있습니다.")
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # VoiceController()의 반환값을 controller에 대입합니다.
    controller = VoiceController(
        listener=listener,  # type: ignore[arg-type]
        tts=tts,
        chat=chat,  # type: ignore[arg-type]
        masker=_masker(),
        acknowledgement="무엇을 도와드릴까요.",
        max_tts_chars=400,
        events=FakeEvents(),
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert controller.run(max_interactions=1) == 0

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert listener.wakes == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert tts.spoken == ["수돗물에는 미네랄이 있습니다."]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert chat.calls == [("수돗물의 성분에 대해서 알려줘", "voice")]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "무엇을 도와드릴까요." not in tts.spoken


# pytest가 test_hotkey_barge_in_cancels_tts()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_hotkey_barge_in_cancels_tts() -> None:
    # HotkeyOnce: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class HotkeyOnce:
        # poll(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 참/거짓(bool).
        def poll(self) -> bool:
            # True을 반환하고 이 함수의 실행을 끝냅니다.
            return True

        # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 별도 결과 없음(None).
        def close(self) -> None:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None

    # FakeEvents()의 반환값을 events에 대입합니다.
    events = FakeEvents()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=FailOnFeedSTT(),  # type: ignore[arg-type]
        command_stt=FakeCommandSTT(),  # type: ignore[arg-type]
        microphone_factory=FakeMicrophone,  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 750, 500, 15_000),
        barge_in_gate_factory=_open_barge_in_gate,  # type: ignore[arg-type]
        interrupt_hotkey_factory=HotkeyOnce,  # type: ignore[arg-type]
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert listener.wait_for_barge_in(Event()) is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[단축키 끼어들기]" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[1][1]["source"] == "hotkey"


# SequenceMicrophone: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SequenceMicrophone:
    # overflows에 숫자 등 고정된 값을 대입합니다.
    overflows = 0

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: frames.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, frames: list[AudioFrame]) -> None:
        # 오른쪽 식을 계산한 값을 self.frames에 대입합니다.
        self.frames = frames

    # __enter__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: SequenceMicrophone.
    def __enter__(self) -> SequenceMicrophone:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # next_frame(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: AudioFrame | None.
    def next_frame(self, *, timeout_s: float = 0.5) -> AudioFrame | None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del timeout_s
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return self.frames.pop(0) if self.frames else None

    # __exit__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: exc_type, exc_value, traceback.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del exc_type, exc_value, traceback


# _audio_frame(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: amplitude.
# 반환 타입 힌트: AudioFrame.
def _audio_frame(amplitude: int) -> AudioFrame:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return AudioFrame(amplitude.to_bytes(2, "little", signed=True) * 4_000, 16_000)


# pytest가 test_local_listener_uses_silence_boundary_then_whisper_quality()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_local_listener_uses_silence_boundary_then_whisper_quality() -> None:
    # 오른쪽 식을 계산한 값을 frames에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    frames = [_audio_frame(value) for value in (0, 4_000, 4_000, 0, 0, 0)]
    # FakeCommandSTT()의 반환값을 command_stt에 대입합니다.
    command_stt = FakeCommandSTT(
        Transcript("오늘 날짜를 알려줘", "ko", 1_500, 0.8, -0.2, 0.01)
    )
    # FakeEvents()의 반환값을 events에 대입합니다.
    events = FakeEvents()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=FakeStreamingSTT(),  # type: ignore[arg-type]
        command_stt=command_stt,  # type: ignore[arg-type]
        microphone_factory=lambda: SequenceMicrophone(frames),  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 750, 500, 5_000),
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # listener.listen_for_command()의 반환값을 transcript에 대입합니다.
    transcript = listener.listen_for_command()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.text == "오늘 날짜를 알려줘"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sum(frame.duration_ms for frame in command_stt.frames) == 1_500
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.types == ["voice.recording", "voice.recording", "stt.result"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[-1][1]["state"] == "accepted"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[마이크 음량]" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[녹음 종료] 연속 무음을 감지했습니다." in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[Whisper 확정] 오늘 날짜를 알려줘" in output.getvalue()


# pytest가 test_local_listener_rejects_low_quality_whisper_text()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_local_listener_rejects_low_quality_whisper_text() -> None:
    # 오른쪽 식을 계산한 값을 frames에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    frames = [_audio_frame(value) for value in (4_000, 4_000, 0, 0, 0)]
    # FakeCommandSTT()의 반환값을 command_stt에 대입합니다.
    command_stt = FakeCommandSTT(
        Transcript("엉뚱한 문장", "ko", 1_250, 0.1, -2.0, 0.8)
    )
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=FakeStreamingSTT(),  # type: ignore[arg-type]
        command_stt=command_stt,  # type: ignore[arg-type]
        microphone_factory=lambda: SequenceMicrophone(frames),  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 750, 500, 5_000),
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=FakeEvents(),
        clock=FrozenClock(NOW),
        output_stream=StringIO(),
    )

    # listener.listen_for_command()의 반환값을 transcript에 대입합니다.
    transcript = listener.listen_for_command()

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.text == ""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.avg_logprob == -2.0


# pytest가 test_local_listener_detects_final_wake_word_during_tts()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_local_listener_detects_final_wake_word_during_tts() -> None:
    # FakeEvents()의 반환값을 events에 대입합니다.
    events = FakeEvents()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=FakeStreamingSTT(),  # type: ignore[arg-type]
        command_stt=FakeCommandSTT(),  # type: ignore[arg-type]
        microphone_factory=FakeMicrophone,  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 750, 500, 15_000),
        barge_in_gate_factory=_open_barge_in_gate,  # type: ignore[arg-type]
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # listener.wait_for_barge_in()의 반환값을 detected에 대입합니다.
    detected = listener.wait_for_barge_in(Event())

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert detected is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.types == ["voice.barge_in", "voice.barge_in", "voice.barge_in"]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[1][1]["state"] == "detected"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[말 끼어들기] '자비스'를 감지했습니다." in output.getvalue()


# pytest가 test_barge_in_closed_gate_does_not_feed_vosk()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_barge_in_closed_gate_does_not_feed_vosk() -> None:
    # Event()의 반환값을 speech_done에 대입합니다.
    speech_done = Event()
    # FakeEvents()의 반환값을 events에 대입합니다.
    events = FakeEvents()
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=FailOnFeedSTT(),  # type: ignore[arg-type]
        command_stt=FakeCommandSTT(),  # type: ignore[arg-type]
        microphone_factory=FakeMicrophone,  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 750, 500, 15_000),
        barge_in_gate_factory=lambda: CompletingClosedBargeInGate(  # type: ignore[arg-type]
            speech_done
        ),
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=events,
        clock=FrozenClock(NOW),
        output_stream=StringIO(),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert listener.wait_for_barge_in(speech_done) is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[-1][1]["gate_frames"] == 0


# pytest가 test_local_listener_detects_partial_wake_word_during_tts()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_local_listener_detects_partial_wake_word_during_tts() -> None:
    # FakeEvents()의 반환값을 events에 대입합니다.
    events = FakeEvents()
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=PartialStreamingSTT(),  # type: ignore[arg-type]
        command_stt=FakeCommandSTT(),  # type: ignore[arg-type]
        microphone_factory=FakeMicrophone,  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 750, 500, 15_000),
        barge_in_gate_factory=_open_barge_in_gate,  # type: ignore[arg-type]
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=events,
        clock=FrozenClock(NOW),
        output_stream=output,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert listener.wait_for_barge_in(Event(), spoken_text="서울은 대한민국의 수도입니다.")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert events.records[1][1]["recognition_state"] == "partial"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[끼어들기 STT 부분] 자비스" in output.getvalue()


# pytest가 test_barge_in_does_not_trigger_on_answer_sentence_containing_jarvis()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_barge_in_does_not_trigger_on_answer_sentence_containing_jarvis() -> None:
    # Event()의 반환값을 speech_done에 대입합니다.
    speech_done = Event()
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=CompletingPartialSTT(speech_done),  # type: ignore[arg-type]
        command_stt=FakeCommandSTT(),  # type: ignore[arg-type]
        microphone_factory=FakeMicrophone,  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 750, 500, 15_000),
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=FakeEvents(),
        clock=FrozenClock(NOW),
        output_stream=StringIO(),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert (
        listener.wait_for_barge_in(
            speech_done,
            spoken_text="자비스 프로젝트의 현재 상태를 설명합니다.",
        )
        is False
    )


# pytest가 test_barge_in_does_not_trigger_on_final_tts_sentence_containing_jarvis()을 실행해 아래
# 상황이
# 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_barge_in_does_not_trigger_on_final_tts_sentence_containing_jarvis() -> None:
    # Event()의 반환값을 speech_done에 대입합니다.
    speech_done = Event()
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
    listener = LocalVoiceListener(
        wake_stt=CompletingSelfFinalSTT(speech_done),  # type: ignore[arg-type]
        command_stt=FakeCommandSTT(),  # type: ignore[arg-type]
        microphone_factory=FakeMicrophone,  # type: ignore[arg-type]
        wake_word="자비스",
        capture_policy=SpeechCapturePolicy(500, -42, 750, 500, 15_000),
        barge_in_gate_factory=_open_barge_in_gate,  # type: ignore[arg-type]
        min_avg_logprob=-1.0,
        max_no_speech_probability=0.6,
        device_label="테스트 마이크",
        events=FakeEvents(),
        clock=FrozenClock(NOW),
        output_stream=StringIO(),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert (
        listener.wait_for_barge_in(
            speech_done,
            spoken_text="자비스 프로젝트의 현재 상태를 설명합니다.",
        )
        is False
    )
