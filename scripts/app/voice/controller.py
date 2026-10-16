# 파이썬 공부 | scripts/app/voice/controller.py
# 호출어 감지, 질문 인식, 대화 처리, 음성 출력을 순서대로 연결합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Opt-in local wake-word controller that reuses the text orchestrator."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Event, Thread
from typing import Any, Literal, Protocol, TextIO

from app.core.clock import Clock
from app.core.errors import JarvisError
from app.orchestrator.loop import ChatOrchestrator
from app.telemetry.masking import LogMasker
from app.voice.barge_in_gate import BargeInGate
from app.voice.base import AudioFrame, Transcript, TTSEngine
from app.voice.interrupt_hotkey import InterruptHotkeyFactory, NullInterruptHotkey
from app.voice.microphone import MicrophoneStream, SpeechCapture, SpeechCapturePolicy
from app.voice.stt import (
    FasterWhisperSTTEngine,
    VoskSTTEngine,
    transcript_passes_quality,
)
from app.voice.tts import prepare_speech
from app.voice.wake_match import (
    normalize_spoken_command,
    strip_leading_wake_word,
    wake_match_kind,
)

# frozenset()의 반환값을 EXIT_PHRASES에 대입합니다.
EXIT_PHRASES = frozenset({"종료", "자비스종료", "그만", "그만해"})
# MISHEARD_TEXT에 문자열을 대입합니다.
MISHEARD_TEXT = "잘 듣지 못했습니다. 다시 자비스라고 불러 주세요."
# EXIT_TEXT에 문자열을 대입합니다.
EXIT_TEXT = "안전하게 종료합니다."
# INPUT_STATUS_INTERVAL_MS에 숫자 등 고정된 값을 대입합니다.
INPUT_STATUS_INTERVAL_MS = 2_000
# LEVEL_STATUS_INTERVAL_MS에 숫자 등 고정된 값을 대입합니다.
LEVEL_STATUS_INTERVAL_MS = 500
# MAX_PREVIEW_CHARS에 숫자 등 고정된 값을 대입합니다.
MAX_PREVIEW_CHARS = 160
# WAKE_PHRASES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
WAKE_PHRASES = ("자비스", "자 비스")
# AudioFrame()의 반환값을 _SILENCE_FRAME에 대입합니다.
_SILENCE_FRAME = AudioFrame(b"\x00\x00" * 4_000, 16_000)


# VoiceEventSink: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class VoiceEventSink(Protocol):
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# TurnStart: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class TurnStart:
    # mode: Literal['standalone', 'inline_command', 'cancelled'] 타입을 기대하는 필드입니다. 이
    # 줄만으로 값이 대입되지는
    # 않습니다.
    mode: Literal["standalone", "inline_command", "cancelled"]
    # command: Transcript | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    command: Transcript | None


# LocalVoiceListener: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class LocalVoiceListener:
    """Open the microphone only while listening and discard all consumed PCM."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: wake_stt, command_stt, microphone_factory, wake_word, capture_policy,
    # barge_in_gate_factory, interrupt_hotkey_factory, min_avg_logprob,
    # max_no_speech_probability, device_label, events, clock, output_stream.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        *,
        wake_stt: VoskSTTEngine,
        command_stt: FasterWhisperSTTEngine,
        microphone_factory: Callable[[], MicrophoneStream],
        wake_word: str,
        capture_policy: SpeechCapturePolicy,
        barge_in_gate_factory: Callable[[], BargeInGate] | None = None,
        interrupt_hotkey_factory: InterruptHotkeyFactory | None = None,
        min_avg_logprob: float | None = None,
        max_no_speech_probability: float | None = None,
        device_label: str,
        events: VoiceEventSink,
        clock: Clock,
        output_stream: TextIO,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self._wake_stt에 대입합니다.
        self._wake_stt = wake_stt
        # 오른쪽 식을 계산한 값을 self._command_stt에 대입합니다.
        self._command_stt = command_stt
        # 오른쪽 식을 계산한 값을 self._microphone_factory에 대입합니다.
        self._microphone_factory = microphone_factory
        # wake_word.strip()의 반환값을 self._wake_word_text에 대입합니다.
        self._wake_word_text = wake_word.strip()
        # normalize_spoken_command()의 반환값을 self._wake_word에 대입합니다.
        self._wake_word = normalize_spoken_command(wake_word)
        # 오른쪽 식을 계산한 값을 self._capture_policy에 대입합니다.
        self._capture_policy = capture_policy
        # 오른쪽 식을 계산한 값을 self._barge_in_gate_factory에 대입합니다.
        self._barge_in_gate_factory = barge_in_gate_factory
        # 오른쪽 식을 계산한 값을 self._interrupt_hotkey_factory에 대입합니다.
        self._interrupt_hotkey_factory = interrupt_hotkey_factory
        # 오른쪽 식을 계산한 값을 self._min_avg_logprob에 대입합니다.
        self._min_avg_logprob = min_avg_logprob
        # 오른쪽 식을 계산한 값을 self._max_no_speech_probability에 대입합니다.
        self._max_no_speech_probability = max_no_speech_probability
        # 오른쪽 식을 계산한 값을 self._device_label에 대입합니다.
        self._device_label = device_label
        # 오른쪽 식을 계산한 값을 self._events에 대입합니다.
        self._events = events
        # 오른쪽 식을 계산한 값을 self._clock에 대입합니다.
        self._clock = clock
        # 오른쪽 식을 계산한 값을 self._output에 대입합니다.
        self._output = output_stream

    # await_turn_start(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: stop_event.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: TurnStart.
    def await_turn_start(self, *, stop_event: Event | None = None) -> TurnStart:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._await_wake_session(stop_event=stop_event)

    # wait_for_wake(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Transcript.
    def wait_for_wake(self) -> Transcript:
        """Compatibility helper: wait until a wake word is accepted."""
        # self._await_wake_session()의 반환값을 started에 대입합니다.
        started = self._await_wake_session()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: started.mode == 'inline_command' and
        # started.command is
        # not None.
        if started.mode == "inline_command" and started.command is not None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return Transcript(
                self._wake_word_text,
                started.command.language,
                started.command.duration_ms,
                started.command.confidence,
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Transcript(self._wake_word_text, "ko", 0, None)

    # listen_for_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: stop_event.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Transcript.
    def listen_for_command(self, *, stop_event: Event | None = None) -> Transcript:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._capture_and_transcribe_command(stop_event=stop_event)

    # wait_for_barge_in(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: speech_done, spoken_text.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def wait_for_barge_in(self, speech_done: Event, *, spoken_text: str = "") -> bool:
        """Watch wake-word results and optional hotkey while TTS is speaking."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: speech_done.is_set() or
        # self._barge_in_gate_factory is
        # None.
        if speech_done.is_set() or self._barge_in_gate_factory is None:
            # False을 반환하고 이 함수의 실행을 끝냅니다.
            return False
        # self._barge_in_gate_factory()의 반환값을 gate에 대입합니다.
        gate = self._barge_in_gate_factory()
        # self._wake_stt.stream()의 반환값을 recognizer에 대입합니다.
        recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
        # 오른쪽 식을 계산한 값을 spoken_text_contains_wake에 대입합니다.
        spoken_text_contains_wake = self._wake_word in normalize_spoken_command(spoken_text)
        # 오른쪽 식을 계산한 값을 hotkey에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        hotkey = (
            self._interrupt_hotkey_factory()
            if self._interrupt_hotkey_factory is not None
            else NullInterruptHotkey()
        )
        # detected을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        detected = False
        # interrupt_source에 문자열을 대입합니다.
        interrupt_source = ""
        # duration_ms에 숫자 등 고정된 값을 대입합니다.
        duration_ms = 0
        # last_preview에 문자열을 대입합니다.
        last_preview = ""
        # 오른쪽 식을 계산한 값을 next_level_status_ms에 대입합니다.
        next_level_status_ms = LEVEL_STATUS_INTERVAL_MS
        # partial_updates에 숫자 등 고정된 값을 대입합니다.
        partial_updates = 0
        # final_updates에 숫자 등 고정된 값을 대입합니다.
        final_updates = 0
        # gate_frames에 숫자 등 고정된 값을 대입합니다.
        gate_frames = 0
        # onset_count에 숫자 등 고정된 값을 대입합니다.
        onset_count = 0
        # voice_frames에 숫자 등 고정된 값을 대입합니다.
        voice_frames = 0
        # 오른쪽 식을 계산한 값을 peak_dbfs에 대입합니다.
        peak_dbfs = -96.0
        # microphone을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        microphone: MicrophoneStream | None = None
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        self._events.emit(
            "voice.barge_in",
            {
                "state": "started",
                "device": self._device_label,
                "duration_ms": 0,
                "gate": "adaptive_vad",
            },
        )
        # _write()을 호출해 작업을 수행합니다.
        _write(
            self._output,
            "[끼어들기 감시] 답변 중 '자비스'라고 부르거나 중단 단축키를 누르면 멈춥니다.",
        )
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with self._microphone_factory() as microphone:
                # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
                while not speech_done.is_set():
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: hotkey.poll().
                    if hotkey.poll():
                        # detected을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
                        detected = True
                        # interrupt_source에 문자열을 대입합니다.
                        interrupt_source = "hotkey"
                        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                        self._events.emit(
                            "voice.barge_in",
                            {
                                "state": "detected",
                                "device": self._device_label,
                                "duration_ms": duration_ms,
                                "source": "hotkey",
                                "gate": "hotkey",
                            },
                        )
                        # _write()을 호출해 작업을 수행합니다.
                        _write(self._output, "[단축키 끼어들기] 답변을 중단합니다.")
                        # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                        break
                    # microphone.next_frame()의 반환값을 frame에 대입합니다.
                    frame = microphone.next_frame(timeout_s=0.1)
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: frame is None.
                    if frame is None:
                        # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로
                        # 이동합니다.
                        continue
                    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                    duration_ms += frame.duration_ms
                    # gate.feed()의 반환값을 decision에 대입합니다.
                    decision = gate.feed(frame)
                    # 오른쪽 식을 계산한 값을 level_dbfs에 대입합니다.
                    level_dbfs = decision.level_dbfs
                    # max()의 반환값을 peak_dbfs에 대입합니다.
                    peak_dbfs = max(peak_dbfs, level_dbfs)
                    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                    voice_frames += int(decision.voice)
                    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                    onset_count += int(decision.onset)
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: duration_ms >=
                    # next_level_status_ms.
                    if duration_ms >= next_level_status_ms:
                        # 오른쪽 식을 계산한 값을 state에 대입합니다.
                        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을
                        # 고릅니다.
                        state = (
                            "onset"
                            if decision.onset
                            else "통과"
                            if decision.open
                            else "감시 중"
                        )
                        # 오른쪽 식을 계산한 값을 voice_state에 대입합니다.
                        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을
                        # 고릅니다.
                        voice_state = "음성" if decision.voice else "비음성"
                        # _write()을 호출해 작업을 수행합니다.
                        _write(
                            self._output,
                            f"[끼어들기 마이크] {level_dbfs:.1f} dBFS · "
                            f"기준 {decision.baseline_dbfs:.1f} dBFS · "
                            f"VAD {voice_state} · {state}",
                        )
                        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                        next_level_status_ms += LEVEL_STATUS_INTERVAL_MS
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: decision.reset_recognizer.
                    if decision.reset_recognizer:
                        # self._wake_stt.stream()의 반환값을 recognizer에 대입합니다.
                        recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
                        # last_preview에 문자열을 대입합니다.
                        last_preview = ""

                    # for 반복문: 대상의 항목을 하나씩 gated_frame에 대입하며 아래 블록을
                    # 실행합니다.
                    for gated_frame in decision.frames:
                        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                        gate_frames += 1
                        # recognizer.feed()의 반환값을 update에 대입합니다.
                        update = recognizer.feed(gated_frame.pcm)
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: update.final.
                        if update.final:
                            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                            final_updates += 1
                        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                        else:
                            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                            partial_updates += 1
                        # _preview_text()의 반환값을 preview에 대입합니다.
                        preview = _preview_text(update.text)
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: preview and preview !=
                        # last_preview.
                        if preview and preview != last_preview:
                            # 오른쪽 식을 계산한 값을 label에 대입합니다.
                            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을
                            # 고릅니다.
                            label = (
                                "끼어들기 STT 확정" if update.final else "끼어들기 STT 부분"
                            )
                            # _write()을 호출해 작업을 수행합니다.
                            _write(self._output, f"[{label}] {preview}")
                            # 오른쪽 식을 계산한 값을 last_preview에 대입합니다.
                            last_preview = preview

                        # wake_match_kind()의 반환값을 kind에 대입합니다.
                        kind = wake_match_kind(update.text, self._wake_word_text)
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다:
                        # spoken_text_contains_wake.
                        if spoken_text_contains_wake:
                            # 오른쪽 식을 계산한 값을 wake_recognized에 대입합니다.
                            wake_recognized = update.final and kind == "standalone"
                        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                        else:
                            # 오른쪽 식을 계산한 값을 wake_recognized에 대입합니다.
                            wake_recognized = kind in {"standalone", "prefix"} and (
                                update.final or kind == "standalone"
                            )
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: wake_recognized.
                        if wake_recognized:
                            # detected을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
                            detected = True
                            # interrupt_source에 문자열을 대입합니다.
                            interrupt_source = "wake_word"
                            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                            self._events.emit(
                                "voice.barge_in",
                                {
                                    "state": "detected",
                                    "device": self._device_label,
                                    "duration_ms": duration_ms,
                                    "recognition_state": (
                                        "final" if update.final else "partial"
                                    ),
                                    "source": "wake_word",
                                    "level_dbfs": round(level_dbfs, 1),
                                    "baseline_dbfs": round(decision.baseline_dbfs, 1),
                                    "gate": "open",
                                    "onset": decision.onset,
                                },
                            )
                            # _write()을 호출해 작업을 수행합니다.
                            _write(self._output, "[말 끼어들기] '자비스'를 감지했습니다.")
                            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                            break
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: update.final.
                        if update.final:
                            # self._wake_stt.stream()의 반환값을 recognizer에 대입합니다.
                            recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
                            # last_preview에 문자열을 대입합니다.
                            last_preview = ""
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: detected.
                    if detected:
                        # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                        break
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # 사용하던 연결이나 자원을 닫습니다.
            hotkey.close()
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            self._events.emit(
                "voice.barge_in",
                {
                    "state": "stopped",
                    "device": self._device_label,
                    "duration_ms": duration_ms,
                    "detected": detected,
                    "source": interrupt_source or None,
                    "overflows": 0 if microphone is None else microphone.overflows,
                    "partial_updates": partial_updates,
                    "final_updates": final_updates,
                    "gate_frames": gate_frames,
                    "onset_count": onset_count,
                    "voice_frames": voice_frames,
                    "peak_dbfs": round(peak_dbfs, 1),
                },
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return detected

    # _await_wake_session(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: stop_event.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: TurnStart.
    def _await_wake_session(self, *, stop_event: Event | None = None) -> TurnStart:
        # self._wake_stt.stream()의 반환값을 recognizer에 대입합니다.
        recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
        # SpeechCapture()의 반환값을 capture에 대입합니다.
        capture = SpeechCapture(self._capture_policy)
        # self._clock.monotonic_ms()의 반환값을 started_ms에 대입합니다.
        started_ms = self._clock.monotonic_ms()
        # duration_ms에 숫자 등 고정된 값을 대입합니다.
        duration_ms = 0
        # wake_detected을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        wake_detected = False
        # last_preview에 문자열을 대입합니다.
        last_preview = ""
        # 오른쪽 식을 계산한 값을 next_input_status_ms에 대입합니다.
        next_input_status_ms = INPUT_STATUS_INTERVAL_MS
        # microphone을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        microphone: MicrophoneStream | None = None
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        self._events.emit(
            "voice.recording",
            {"state": "started", "device": self._device_label, "duration_ms": 0},
        )
        # _write()을 호출해 작업을 수행합니다.
        _write(
            self._output,
            f"[마이크 켜짐] 웨이크워드를 듣고 있습니다. (장치: {self._device_label})",
        )
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with self._microphone_factory() as microphone:
                # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
                while True:
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stop_event is not None and
                    # stop_event.is_set().
                    if stop_event is not None and stop_event.is_set():
                        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                        return TurnStart("cancelled", None)
                    # microphone.next_frame()의 반환값을 frame에 대입합니다.
                    frame = microphone.next_frame(timeout_s=0.5)
                    # max()의 반환값을 elapsed_ms에 대입합니다.
                    elapsed_ms = max(0, self._clock.monotonic_ms() - started_ms)
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: frame is None.
                    if frame is None:
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: wake_detected and (not
                        # capture.finished).
                        if wake_detected and not capture.finished:
                            # Mic poll timeout counts as silence so trailing-silence
                            # can finish without depending on wall-clock advancement.
                            # capture.feed()을 호출해 작업을 수행합니다.
                            capture.feed(_SILENCE_FRAME)
                            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                            duration_ms += _SILENCE_FRAME.duration_ms
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: wake_detected and
                        # capture.finished.
                        if wake_detected and capture.finished:
                            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                            break
                        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을
                        # 실행합니다.
                        if wake_detected and elapsed_ms >= self._capture_policy.max_duration_ms:
                            # capture.expire()을 호출해 작업을 수행합니다.
                            capture.expire()
                            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                            break
                        # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로
                        # 이동합니다.
                        continue
                    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                    duration_ms += frame.duration_ms
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not capture.finished.
                    if not capture.finished:
                        # capture.feed()을 호출해 작업을 수행합니다.
                        capture.feed(frame)
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: wake_detected.
                    if wake_detected:
                        # Vosk wake grammar must not keep mapping later words to "자비스".
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: duration_ms >=
                        # next_input_status_ms.
                        if duration_ms >= next_input_status_ms:
                            # 오른쪽 식을 계산한 값을 state에 대입합니다.
                            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을
                            # 고릅니다.
                            state = "음성 감지" if capture.speech_started else "대기"
                            # _write()을 호출해 작업을 수행합니다.
                            _write(
                                self._output,
                                f"[호출 후 녹음] {frame.rms_dbfs:.1f} dBFS · {state} "
                                "(Whisper로 질문 인식)",
                            )
                            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                            next_input_status_ms += LEVEL_STATUS_INTERVAL_MS
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: capture.finished.
                        if capture.finished:
                            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                            break
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: elapsed_ms >=
                        # self._capture_policy.max_duration_ms.
                        if elapsed_ms >= self._capture_policy.max_duration_ms:
                            # capture.expire()을 호출해 작업을 수행합니다.
                            capture.expire()
                            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                            break
                        # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로
                        # 이동합니다.
                        continue

                    # recognizer.feed()의 반환값을 update에 대입합니다.
                    update = recognizer.feed(frame.pcm)
                    # _preview_text()의 반환값을 preview에 대입합니다.
                    preview = _preview_text(update.text)
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: preview and preview !=
                    # last_preview.
                    if preview and preview != last_preview:
                        # 오른쪽 식을 계산한 값을 label에 대입합니다.
                        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을
                        # 고릅니다.
                        label = "STT 확정" if update.final else "STT 부분"
                        # _write()을 호출해 작업을 수행합니다.
                        _write(self._output, f"[{label}] {preview}")
                        # 오른쪽 식을 계산한 값을 last_preview에 대입합니다.
                        last_preview = preview
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: duration_ms >=
                    # next_input_status_ms.
                    elif duration_ms >= next_input_status_ms:
                        # _write()을 호출해 작업을 수행합니다.
                        _write(
                            self._output,
                            f"[마이크 입력] {duration_ms / 1000:.1f}초 수신 중, "
                            "새로 인식된 텍스트 없음",
                        )
                        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                        next_input_status_ms += INPUT_STATUS_INTERVAL_MS
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: update.final.
                    if update.final:
                        # wake_match_kind()의 반환값을 kind에 대입합니다.
                        kind = wake_match_kind(update.text, self._wake_word_text)
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: kind in {'standalone',
                        # 'prefix'}.
                        if kind in {"standalone", "prefix"}:
                            # wake_detected을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
                            wake_detected = True
                            # _write()을 호출해 작업을 수행합니다.
                            _write(
                                self._output,
                                "[호출 확정] 이어서 같은 발화를 듣고 Whisper로 인식합니다.",
                            )
                        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                        else:
                            # self._wake_stt.stream()의 반환값을 recognizer에 대입합니다.
                            recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
                            # capture.clear()을 호출해 작업을 수행합니다.
                            capture.clear()
                            # last_preview에 문자열을 대입합니다.
                            last_preview = ""
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: wake_detected and
                    # capture.finished.
                    if wake_detected and capture.finished:
                        # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                        break
                    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                    if wake_detected and elapsed_ms >= self._capture_policy.max_duration_ms:
                        # capture.expire()을 호출해 작업을 수행합니다.
                        capture.expire()
                        # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                        break
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # max()의 반환값을 elapsed_ms에 대입합니다.
            elapsed_ms = max(0, self._clock.monotonic_ms() - started_ms)
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            self._events.emit(
                "voice.recording",
                {
                    "state": "stopped",
                    "device": self._device_label,
                    "duration_ms": duration_ms,
                    "speech_ms": capture.speech_duration_ms,
                    "reason": capture.finish_reason,
                    "overflows": 0 if microphone is None else microphone.overflows,
                    "wake_mode": "pending_inline" if wake_detected else "none",
                },
            )
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            self._events.emit(
                "stt.result",
                {
                    "language": "ko",
                    "engine": "vosk",
                    "duration_ms": duration_ms,
                    "latency_ms": elapsed_ms,
                    "text_len": len(self._wake_word_text) if wake_detected else 0,
                    "wake_mode": "detected" if wake_detected else "none",
                },
            )
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[마이크 꺼짐]")

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._command_from_wake_capture(capture, started_ms=started_ms)

    # _command_from_wake_capture(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: capture, started_ms.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: TurnStart.
    def _command_from_wake_capture(
        self, capture: SpeechCapture, *, started_ms: int
    ) -> TurnStart:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: capture.finish_reason ==
        # 'trailing_silence'.
        if capture.finish_reason == "trailing_silence":
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[녹음 종료] 연속 무음을 감지했습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: capture.finish_reason ==
        # 'max_duration'.
        elif capture.finish_reason == "max_duration":
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[녹음 종료] 최대 녹음 시간에 도달했습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not capture.acceptable or not
        # capture.frames.
        if not capture.acceptable or not capture.frames:
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[한 문장 명령] 추가 질문이 없어 안내 후 질문을 듣습니다.")
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return TurnStart("standalone", None)

        # _write()을 호출해 작업을 수행합니다.
        _write(self._output, "[Whisper 처리] 호출과 질문을 한 문장으로 인식합니다.")
        # self._command_stt.transcribe()의 반환값을 transcript에 대입합니다.
        transcript = self._command_stt.transcribe(capture.frames)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._command_stt.fallback_reason is
        # not None.
        if self._command_stt.fallback_reason is not None:
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[Whisper 폴백] CUDA를 사용할 수 없어 CPU int8로 전환했습니다.")
        # 오른쪽 식을 계산한 값을 quality에 대입합니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        quality = (
            f"평균 logprob={_format_optional(transcript.avg_logprob)}, "
            f"무음 확률={_format_optional(transcript.no_speech_probability)}, "
            f"장치={self._command_stt.active_device}"
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: transcript.text.
        if transcript.text:
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, f"[Whisper 확정] {_preview_text(transcript.text)} ({quality})")
        # transcript_passes_quality()의 반환값을 accepted에 대입합니다.
        accepted = transcript_passes_quality(
            transcript,
            min_avg_logprob=self._min_avg_logprob,
            max_no_speech_probability=self._max_no_speech_probability,
        )
        # strip_leading_wake_word()의 반환값을 command_text에 대입합니다.
        command_text = strip_leading_wake_word(transcript.text, self._wake_word_text)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not accepted or not command_text.
        if not accepted or not command_text:
            # self._emit_command_result()을 호출해 작업을 수행합니다.
            self._emit_command_result(
                transcript,
                started_ms=started_ms,
                state="standalone_wake" if accepted else "rejected",
            )
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[한 문장 명령] 질문 부분이 없어 안내 후 질문을 듣습니다.")
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return TurnStart("standalone", None)

        # Transcript()의 반환값을 command에 대입합니다.
        command = Transcript(
            command_text,
            transcript.language,
            transcript.duration_ms,
            transcript.confidence,
            transcript.avg_logprob,
            transcript.no_speech_probability,
        )
        # self._emit_command_result()을 호출해 작업을 수행합니다.
        self._emit_command_result(command, started_ms=started_ms, state="inline_command")
        # _write()을 호출해 작업을 수행합니다.
        _write(self._output, f"[한 문장 명령] {command_text}")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return TurnStart("inline_command", command)

    # _capture_and_transcribe_command(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: stop_event.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Transcript.
    def _capture_and_transcribe_command(self, *, stop_event: Event | None = None) -> Transcript:
        # self._clock.monotonic_ms()의 반환값을 started_ms에 대입합니다.
        started_ms = self._clock.monotonic_ms()
        # SpeechCapture()의 반환값을 capture에 대입합니다.
        capture = SpeechCapture(self._capture_policy)
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        self._events.emit(
            "voice.recording",
            {"state": "started", "device": self._device_label, "duration_ms": 0},
        )
        # _write()을 호출해 작업을 수행합니다.
        _write(
            self._output,
            f"[마이크 켜짐] 요청을 듣고 있습니다. (장치: {self._device_label})",
        )
        # 오른쪽 식을 계산한 값을 next_level_status_ms에 대입합니다.
        next_level_status_ms = LEVEL_STATUS_INTERVAL_MS
        # microphone을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        microphone: MicrophoneStream | None = None
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with self._microphone_factory() as microphone:
                # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
                while not capture.finished:
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stop_event is not None and
                    # stop_event.is_set().
                    if stop_event is not None and stop_event.is_set():
                        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                        return Transcript("", self._command_stt.language, 0, None)
                    # microphone.next_frame()의 반환값을 frame에 대입합니다.
                    frame = microphone.next_frame(timeout_s=0.5)
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: frame is None.
                    if frame is None:
                        # max()의 반환값을 elapsed_ms에 대입합니다.
                        elapsed_ms = max(0, self._clock.monotonic_ms() - started_ms)
                        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: elapsed_ms >=
                        # self._capture_policy.max_duration_ms.
                        if elapsed_ms >= self._capture_policy.max_duration_ms:
                            # capture.expire()을 호출해 작업을 수행합니다.
                            capture.expire()
                        # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로
                        # 이동합니다.
                        continue
                    # capture.feed()을 호출해 작업을 수행합니다.
                    capture.feed(frame)
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: capture.input_duration_ms
                    # >=
                    # next_level_status_ms.
                    if capture.input_duration_ms >= next_level_status_ms:
                        # 오른쪽 식을 계산한 값을 state에 대입합니다.
                        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을
                        # 고릅니다.
                        state = "음성 감지" if capture.speech_started else "대기"
                        # _write()을 호출해 작업을 수행합니다.
                        _write(self._output, f"[마이크 음량] {frame.rms_dbfs:.1f} dBFS · {state}")
                        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                        next_level_status_ms += LEVEL_STATUS_INTERVAL_MS
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            self._events.emit(
                "voice.recording",
                {
                    "state": "stopped",
                    "device": self._device_label,
                    "duration_ms": capture.input_duration_ms,
                    "speech_ms": capture.speech_duration_ms,
                    "reason": capture.finish_reason,
                    "overflows": 0 if microphone is None else microphone.overflows,
                },
            )
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[마이크 꺼짐]")

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: capture.finish_reason ==
        # 'trailing_silence'.
        if capture.finish_reason == "trailing_silence":
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[녹음 종료] 연속 무음을 감지했습니다.")
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[녹음 종료] 최대 녹음 시간에 도달했습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not capture.acceptable or not
        # capture.frames.
        if not capture.acceptable or not capture.frames:
            # self._emit_command_result()을 호출해 작업을 수행합니다.
            self._emit_command_result(
                Transcript("", "ko", capture.input_duration_ms, None),
                started_ms=started_ms,
                state="no_speech",
            )
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return Transcript("", "ko", capture.input_duration_ms, None)

        # _write()을 호출해 작업을 수행합니다.
        _write(self._output, "[Whisper 처리] 한국어 질문을 로컬에서 인식하고 있습니다.")
        # self._command_stt.transcribe()의 반환값을 transcript에 대입합니다.
        transcript = self._command_stt.transcribe(capture.frames)
        # 오른쪽 식을 계산한 값을 fallback_reason에 대입합니다.
        fallback_reason = self._command_stt.fallback_reason
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: fallback_reason is not None.
        if fallback_reason is not None:
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[Whisper 폴백] CUDA를 사용할 수 없어 CPU int8로 전환했습니다.")
        # 오른쪽 식을 계산한 값을 quality에 대입합니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        quality = (
            f"평균 logprob={_format_optional(transcript.avg_logprob)}, "
            f"무음 확률={_format_optional(transcript.no_speech_probability)}, "
            f"장치={self._command_stt.active_device}"
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: transcript.text.
        if transcript.text:
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, f"[Whisper 확정] {_preview_text(transcript.text)} ({quality})")
        # transcript_passes_quality()의 반환값을 accepted에 대입합니다.
        accepted = transcript_passes_quality(
            transcript,
            min_avg_logprob=self._min_avg_logprob,
            max_no_speech_probability=self._max_no_speech_probability,
        )
        # self._emit_command_result()을 호출해 작업을 수행합니다.
        self._emit_command_result(
            transcript,
            started_ms=started_ms,
            state="accepted" if accepted else "rejected",
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: accepted.
        if accepted:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return transcript
        # _write()을 호출해 작업을 수행합니다.
        _write(self._output, f"[인식 거부] 품질 기준을 통과하지 못했습니다. ({quality})")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Transcript(
            "",
            transcript.language,
            transcript.duration_ms,
            transcript.confidence,
            transcript.avg_logprob,
            transcript.no_speech_probability,
        )

    # _emit_command_result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: transcript, started_ms, state.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _emit_command_result(
        self, transcript: Transcript, *, started_ms: int, state: str
    ) -> None:
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        self._events.emit(
            "stt.result",
            {
                "state": state,
                "engine": "faster-whisper",
                "device": self._command_stt.active_device,
                "language": transcript.language,
                "duration_ms": transcript.duration_ms,
                "latency_ms": max(0, self._clock.monotonic_ms() - started_ms),
                "text_len": len(transcript.text),
                "confidence": transcript.confidence,
                "avg_logprob": transcript.avg_logprob,
                "no_speech_probability": transcript.no_speech_probability,
            },
        )


# VoiceController: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class VoiceController:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: listener, tts, chat, masker, acknowledgement, max_tts_chars, events, clock,
    # output_stream.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        *,
        listener: LocalVoiceListener,
        tts: TTSEngine,
        chat: ChatOrchestrator,
        masker: LogMasker,
        acknowledgement: str,
        max_tts_chars: int,
        events: VoiceEventSink,
        clock: Clock,
        output_stream: TextIO,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self._listener에 대입합니다.
        self._listener = listener
        # 오른쪽 식을 계산한 값을 self._tts에 대입합니다.
        self._tts = tts
        # 오른쪽 식을 계산한 값을 self._chat에 대입합니다.
        self._chat = chat
        # 오른쪽 식을 계산한 값을 self._masker에 대입합니다.
        self._masker = masker
        # 오른쪽 식을 계산한 값을 self._acknowledgement에 대입합니다.
        self._acknowledgement = acknowledgement
        # 오른쪽 식을 계산한 값을 self._max_tts_chars에 대입합니다.
        self._max_tts_chars = max_tts_chars
        # 오른쪽 식을 계산한 값을 self._events에 대입합니다.
        self._events = events
        # 오른쪽 식을 계산한 값을 self._clock에 대입합니다.
        self._clock = clock
        # 오른쪽 식을 계산한 값을 self._output에 대입합니다.
        self._output = output_stream

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: max_interactions, stop_event, on_wake, on_transcript, on_response, on_state.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 정수(int).
    def run(
        self,
        *,
        max_interactions: int | None = None,
        stop_event: Event | None = None,
        on_wake: Callable[[], None] | None = None,
        on_transcript: Callable[[str], None] | None = None,
        on_response: Callable[[str], None] | None = None,
        on_state: Callable[[str], None] | None = None,
    ) -> int:
        # interactions에 숫자 등 고정된 값을 대입합니다.
        interactions = 0
        # wake_already_detected을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        wake_already_detected = False
        # _write()을 호출해 작업을 수행합니다.
        _write(
            self._output,
            "로컬 음성 모드입니다. '자비스'와 질문을 이어서 말하거나, "
            "호출 후 안내가 나오면 질문하세요. 종료는 Ctrl+C 또는 '종료'입니다.",
        )
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
            while max_interactions is None or interactions < max_interactions:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stop_event is not None and
                # stop_event.is_set().
                if stop_event is not None and stop_event.is_set():
                    # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                    break
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_state.
                if on_state:
                    # on_state()을 호출해 작업을 수행합니다.
                    on_state("idle")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: wake_already_detected.
                if wake_already_detected:
                    # wake_already_detected을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
                    wake_already_detected = False
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_wake.
                    if on_wake:
                        # on_wake()을 호출해 작업을 수행합니다.
                        on_wake()
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_state.
                    if on_state:
                        # on_state()을 호출해 작업을 수행합니다.
                        on_state("listening")
                    # self._speak()을 호출해 작업을 수행합니다.
                    self._speak(self._acknowledgement)
                    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                    # 처리합니다.
                    try:
                        # self._listener.listen_for_command()의 반환값을 transcript에 대입합니다.
                        transcript = self._listener.listen_for_command(stop_event=stop_event)
                    # TypeError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
                    except TypeError:
                        # self._listener.listen_for_command()의 반환값을 transcript에 대입합니다.
                        transcript = self._listener.listen_for_command()
                # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                else:
                    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                    # 처리합니다.
                    try:
                        # self._listener.await_turn_start()의 반환값을 turn에 대입합니다.
                        turn = self._listener.await_turn_start(stop_event=stop_event)
                    # TypeError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
                    except TypeError:
                        # self._listener.await_turn_start()의 반환값을 turn에 대입합니다.
                        turn = self._listener.await_turn_start()
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stop_event is not None and
                    # stop_event.is_set().
                    if stop_event is not None and stop_event.is_set():
                        # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                        break
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: turn.mode == 'cancelled'.
                    if turn.mode == "cancelled":
                        # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                        break
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_wake.
                    if on_wake:
                        # on_wake()을 호출해 작업을 수행합니다.
                        on_wake()
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_state.
                    if on_state:
                        # on_state()을 호출해 작업을 수행합니다.
                        on_state("listening")
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: turn.mode ==
                    # 'inline_command' and turn.command
                    # is not None.
                    if turn.mode == "inline_command" and turn.command is not None:
                        # 오른쪽 식을 계산한 값을 transcript에 대입합니다.
                        transcript = turn.command
                    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
                    else:
                        # self._speak()을 호출해 작업을 수행합니다.
                        self._speak(self._acknowledgement)
                        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                        # 처리합니다.
                        try:
                            # self._listener.listen_for_command()의 반환값을 transcript에
                            # 대입합니다.
                            transcript = self._listener.listen_for_command(stop_event=stop_event)
                        # TypeError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
                        # 담깁니다.
                        except TypeError:
                            # self._listener.listen_for_command()의 반환값을 transcript에
                            # 대입합니다.
                            transcript = self._listener.listen_for_command()
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stop_event is not None and
                # stop_event.is_set().
                if stop_event is not None and stop_event.is_set():
                    # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                    break
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not transcript.text.
                if not transcript.text:
                    # self._speak()을 호출해 작업을 수행합니다.
                    self._speak(MISHEARD_TEXT)
                    # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                    continue
                # _write()을 호출해 작업을 수행합니다.
                _write(self._output, f"인식: {transcript.text}")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_transcript.
                if on_transcript:
                    # on_transcript()을 호출해 작업을 수행합니다.
                    on_transcript(transcript.text)
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_state.
                if on_state:
                    # on_state()을 호출해 작업을 수행합니다.
                    on_state("thinking")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다:
                # normalize_spoken_command(transcript.text) in
                # EXIT_PHRASES.
                if normalize_spoken_command(transcript.text) in EXIT_PHRASES:
                    # self._speak()을 호출해 작업을 수행합니다.
                    self._speak(EXIT_TEXT)
                    # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                    break
                # self._chat.handle_turn()의 반환값을 outcome에 대입합니다.
                outcome = self._chat.handle_turn(transcript.text, channel="voice")
                # 오른쪽 식을 계산한 값을 presentation에 대입합니다.
                presentation = outcome.presentation
                # 오른쪽 식을 계산한 값을 speech에 대입합니다.
                # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
                speech = presentation.speech_text if presentation else outcome.text
                # _write()을 호출해 작업을 수행합니다.
                _write(self._output, f"Jarvis: {outcome.display_text}")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_response.
                if on_response:
                    # on_response()을 호출해 작업을 수행합니다.
                    on_response(outcome.display_text)
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_state.
                if on_state:
                    # on_state()을 호출해 작업을 수행합니다.
                    on_state("speaking")
                # prepare_speech()의 반환값을 prepared에 대입합니다.
                prepared = prepare_speech(
                    speech,
                    masker=self._masker,
                    max_chars=self._max_tts_chars,
                )
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if ((outcome.pending_approval is not None or outcome.intent_confirmation) and
                        (prepared.truncated or prepared.refused)):
                    # self._chat.discard_pending_approval()을 호출해 작업을 수행합니다.
                    self._chat.discard_pending_approval(cause="speech_unavailable")
                # self._speak_interruptibly()의 반환값을 wake_already_detected에 대입합니다.
                wake_already_detected = self._speak_interruptibly(
                    prepared.text,
                    refused=prepared.refused,
                )
                # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                interactions += 1
            # 0을 반환하고 이 함수의 실행을 끝냅니다.
            return 0
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: on_state.
            if on_state:
                # on_state()을 호출해 작업을 수행합니다.
                on_state("idle")
            # self._chat.end()을 호출해 작업을 수행합니다.
            self._chat.end(reason="bye")
            # 사용하던 연결이나 자원을 닫습니다.
            self._tts.close()

    # _speak(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, refused.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _speak(self, text: str, *, refused: bool = False) -> None:
        # self._clock.monotonic_ms()의 반환값을 started_ms에 대입합니다.
        started_ms = self._clock.monotonic_ms()
        # 오른쪽 식을 계산한 값을 state에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        state = "refused" if refused else "completed"
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._tts.speak()을 호출해 작업을 수행합니다.
            self._tts.speak(text)
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception:
            # 오른쪽 식을 계산한 값을 state에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            state = "refused" if refused else "cancelled"
            # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
            raise
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            self._events.emit(
                "tts.result",
                {
                    "state": state,
                    "engine": "windows-sapi",
                    "chars": len(text),
                    "latency_ms": max(0, self._clock.monotonic_ms() - started_ms),
                },
            )

    # _speak_interruptibly(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, refused.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 참/거짓(bool).
    def _speak_interruptibly(self, text: str, *, refused: bool = False) -> bool:
        # self._clock.monotonic_ms()의 반환값을 started_ms에 대입합니다.
        started_ms = self._clock.monotonic_ms()
        # Event()의 반환값을 speech_done에 대입합니다.
        speech_done = Event()
        # errors에 리스트(순서가 있고 수정 가능)을 대입합니다.
        errors: list[BaseException] = []

        # run_speech(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # 반환 타입 힌트: 별도 결과 없음(None).
        def run_speech() -> None:
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # self._tts.speak()을 호출해 작업을 수행합니다.
                self._tts.speak(text)
            # BaseException를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except BaseException as error:
                # 리스트 끝에 항목 하나를 추가합니다.
                errors.append(error)
            # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
            finally:
                # speech_done.set()을 호출해 작업을 수행합니다.
                speech_done.set()

        # Thread()의 반환값을 worker에 대입합니다.
        worker = Thread(target=run_speech, name="jarvis-tts", daemon=True)
        # worker.start()을 호출해 작업을 수행합니다.
        worker.start()
        # interrupted을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        interrupted = False
        # monitor_unavailable을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        monitor_unavailable = False
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._listener.wait_for_barge_in()의 반환값을 interrupted에 대입합니다.
            interrupted = self._listener.wait_for_barge_in(speech_done, spoken_text=text)
        # JarvisError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except JarvisError as error:
            # monitor_unavailable을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
            monitor_unavailable = True
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, f"[끼어들기 감시 불가] {error.user_message}")
        # BaseException를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except BaseException:
            # self._tts.cancel()을 호출해 작업을 수행합니다.
            self._tts.cancel()
            # join을 호출합니다. 문자열에서는 조각 결합, 스레드에서는 종료 대기를 뜻합니다.
            worker.join(timeout=5)
            # 현재 예외를 다시 발생시켜 호출한 쪽으로 전달합니다.
            raise
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: interrupted.
        if interrupted:
            # self._tts.cancel()을 호출해 작업을 수행합니다.
            self._tts.cancel()
        # join을 호출합니다. 문자열에서는 조각 결합, 스레드에서는 종료 대기를 뜻합니다.
        worker.join(timeout=5 if interrupted else 65)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: worker.is_alive().
        if worker.is_alive():
            # self._tts.cancel()을 호출해 작업을 수행합니다.
            self._tts.cancel()
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisError("중단한 음성 합성 프로세스가 종료되지 않았습니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: errors and (not interrupted).
        if errors and not interrupted:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise errors[0]

        # 오른쪽 식을 계산한 값을 state에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        state = "interrupted" if interrupted else "refused" if refused else "completed"
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        self._events.emit(
            "tts.result",
            {
                "state": state,
                "engine": "windows-sapi",
                "chars": len(text),
                "latency_ms": max(0, self._clock.monotonic_ms() - started_ms),
                "barge_in_monitor": "unavailable" if monitor_unavailable else "active",
            },
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: interrupted.
        if interrupted:
            # _write()을 호출해 작업을 수행합니다.
            _write(self._output, "[답변 중단] 새 질문을 받을 준비를 합니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return interrupted


# _write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: stream, text.
# 반환 타입 힌트: 별도 결과 없음(None).
def _write(stream: TextIO, text: str) -> None:
    # 열린 출력 대상에 데이터를 기록합니다.
    stream.write(text + "\n")
    # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
    stream.flush()


# _preview_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 문자열(str).
def _preview_text(text: str) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    return " ".join(text.split())[:MAX_PREVIEW_CHARS]


# _format_optional(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value.
# 반환 타입 힌트: 문자열(str).
def _format_optional(value: float | None) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    return "없음" if value is None else f"{value:.3f}"


# microphone_factory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: device, sample_rate.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Callable[[], MicrophoneStream].
def microphone_factory(
    device: str,
    *,
    sample_rate: int,
) -> Callable[[], MicrophoneStream]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # lambda: 이름 없이 짧은 함수를 만들어 값처럼 전달하거나 저장합니다.
    return lambda: MicrophoneStream(device, sample_rate=sample_rate)
