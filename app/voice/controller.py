"""Opt-in local wake-word controller that reuses the text orchestrator."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol, TextIO

from app.core.clock import Clock
from app.orchestrator.loop import ChatOrchestrator
from app.telemetry.masking import LogMasker
from app.voice.base import Transcript, TTSEngine
from app.voice.microphone import MicrophoneStream
from app.voice.stt import VoskSTTEngine
from app.voice.tts import prepare_speech

EXIT_PHRASES = frozenset({"종료", "자비스종료", "그만", "그만해"})
MISHEARD_TEXT = "잘 듣지 못했습니다. 다시 자비스라고 불러 주세요."
EXIT_TEXT = "안전하게 종료합니다."
INPUT_STATUS_INTERVAL_MS = 2_000
MAX_PREVIEW_CHARS = 160


class VoiceEventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


def normalize_spoken_command(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).casefold()


class LocalVoiceListener:
    """Open the microphone only while listening and discard all consumed PCM."""

    def __init__(
        self,
        *,
        stt: VoskSTTEngine,
        microphone_factory: Callable[[], MicrophoneStream],
        wake_word: str,
        command_timeout_s: float,
        device_label: str,
        events: VoiceEventSink,
        clock: Clock,
        output_stream: TextIO,
    ) -> None:
        self._stt = stt
        self._microphone_factory = microphone_factory
        self._wake_word = normalize_spoken_command(wake_word)
        self._command_timeout_ms = int(command_timeout_s * 1000)
        self._device_label = device_label
        self._events = events
        self._clock = clock
        self._output = output_stream

    def wait_for_wake(self) -> Transcript:
        return self._listen(wake=True)

    def listen_for_command(self) -> Transcript:
        return self._listen(wake=False)

    def _listen(self, *, wake: bool) -> Transcript:
        recognizer = self._stt.stream()
        started_ms = self._clock.monotonic_ms()
        duration_ms = 0
        mode = "웨이크워드" if wake else "요청"
        self._events.emit(
            "voice.recording",
            {"state": "started", "device": self._device_label, "duration_ms": 0},
        )
        _write(
            self._output,
            f"[마이크 켜짐] {mode}을(를) 듣고 있습니다. (장치: {self._device_label})",
        )
        transcript = ""
        last_preview = ""
        next_input_status_ms = INPUT_STATUS_INTERVAL_MS
        microphone: MicrophoneStream | None = None
        try:
            with self._microphone_factory() as microphone:
                while True:
                    frame = microphone.next_frame(timeout_s=0.5)
                    elapsed_ms = max(0, self._clock.monotonic_ms() - started_ms)
                    if not wake and elapsed_ms >= self._command_timeout_ms:
                        transcript = recognizer.finish().text
                        break
                    if frame is None:
                        continue
                    duration_ms += frame.duration_ms
                    update = recognizer.feed(frame.pcm)
                    preview = _preview_text(update.text)
                    if preview and preview != last_preview:
                        label = "STT 확정" if update.final else "STT 부분"
                        _write(self._output, f"[{label}] {preview}")
                        last_preview = preview
                    elif duration_ms >= next_input_status_ms:
                        _write(
                            self._output,
                            f"[마이크 입력] {duration_ms / 1000:.1f}초 수신 중, "
                            "새로 인식된 텍스트 없음",
                        )
                        next_input_status_ms += INPUT_STATUS_INTERVAL_MS
                    normalized = normalize_spoken_command(update.text)
                    if wake and self._wake_word in normalized:
                        transcript = update.text
                        break
                    if not wake and update.final and update.text:
                        transcript = update.text
                        break
                    if update.final:
                        recognizer = self._stt.stream()
        finally:
            elapsed_ms = max(0, self._clock.monotonic_ms() - started_ms)
            self._events.emit(
                "voice.recording",
                {
                    "state": "stopped",
                    "device": self._device_label,
                    "duration_ms": duration_ms,
                    "overflows": 0 if microphone is None else microphone.overflows,
                },
            )
            self._events.emit(
                "stt.result",
                {
                    "language": "ko",
                    "duration_ms": duration_ms,
                    "latency_ms": elapsed_ms,
                    "text_len": len(transcript),
                },
            )
            _write(self._output, "[마이크 꺼짐]")
        return Transcript(transcript.strip(), "ko", duration_ms, None)


class VoiceController:
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
        self._listener = listener
        self._tts = tts
        self._chat = chat
        self._masker = masker
        self._acknowledgement = acknowledgement
        self._max_tts_chars = max_tts_chars
        self._events = events
        self._clock = clock
        self._output = output_stream

    def run(self, *, max_interactions: int | None = None) -> int:
        interactions = 0
        _write(self._output, "로컬 음성 모드입니다. 종료하려면 Ctrl+C 또는 '종료'라고 말하세요.")
        try:
            while max_interactions is None or interactions < max_interactions:
                self._listener.wait_for_wake()
                self._speak(self._acknowledgement)
                transcript = self._listener.listen_for_command()
                if not transcript.text:
                    self._speak(MISHEARD_TEXT)
                    continue
                _write(self._output, f"인식: {transcript.text}")
                if normalize_spoken_command(transcript.text) in EXIT_PHRASES:
                    self._speak(EXIT_TEXT)
                    break
                outcome = self._chat.handle_turn(transcript.text, channel="voice")
                _write(self._output, f"Jarvis: {outcome.text}")
                prepared = prepare_speech(
                    outcome.text,
                    masker=self._masker,
                    max_chars=self._max_tts_chars,
                )
                self._speak(prepared.text, refused=prepared.refused)
                interactions += 1
            return 0
        finally:
            self._chat.end(reason="bye")
            self._tts.close()

    def _speak(self, text: str, *, refused: bool = False) -> None:
        started_ms = self._clock.monotonic_ms()
        state = "refused" if refused else "completed"
        try:
            self._tts.speak(text)
        except Exception:
            state = "refused" if refused else "cancelled"
            raise
        finally:
            self._events.emit(
                "tts.result",
                {
                    "state": state,
                    "engine": "windows-sapi",
                    "chars": len(text),
                    "latency_ms": max(0, self._clock.monotonic_ms() - started_ms),
                },
            )


def _write(stream: TextIO, text: str) -> None:
    stream.write(text + "\n")
    stream.flush()


def _preview_text(text: str) -> str:
    return " ".join(text.split())[:MAX_PREVIEW_CHARS]


def microphone_factory(
    device: str,
    *,
    sample_rate: int,
) -> Callable[[], MicrophoneStream]:
    return lambda: MicrophoneStream(device, sample_rate=sample_rate)
