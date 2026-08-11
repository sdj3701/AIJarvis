"""Opt-in local wake-word controller that reuses the text orchestrator."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol, TextIO

from app.core.clock import Clock
from app.orchestrator.loop import ChatOrchestrator
from app.telemetry.masking import LogMasker
from app.voice.base import Transcript, TTSEngine
from app.voice.microphone import MicrophoneStream, SpeechCapture, SpeechCapturePolicy
from app.voice.stt import (
    FasterWhisperSTTEngine,
    VoskSTTEngine,
    transcript_passes_quality,
)
from app.voice.tts import prepare_speech

EXIT_PHRASES = frozenset({"종료", "자비스종료", "그만", "그만해"})
MISHEARD_TEXT = "잘 듣지 못했습니다. 다시 자비스라고 불러 주세요."
EXIT_TEXT = "안전하게 종료합니다."
INPUT_STATUS_INTERVAL_MS = 2_000
LEVEL_STATUS_INTERVAL_MS = 500
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
        wake_stt: VoskSTTEngine,
        command_stt: FasterWhisperSTTEngine,
        microphone_factory: Callable[[], MicrophoneStream],
        wake_word: str,
        capture_policy: SpeechCapturePolicy,
        min_avg_logprob: float,
        max_no_speech_probability: float,
        device_label: str,
        events: VoiceEventSink,
        clock: Clock,
        output_stream: TextIO,
    ) -> None:
        self._wake_stt = wake_stt
        self._command_stt = command_stt
        self._microphone_factory = microphone_factory
        self._wake_word = normalize_spoken_command(wake_word)
        self._capture_policy = capture_policy
        self._min_avg_logprob = min_avg_logprob
        self._max_no_speech_probability = max_no_speech_probability
        self._device_label = device_label
        self._events = events
        self._clock = clock
        self._output = output_stream

    def wait_for_wake(self) -> Transcript:
        return self._listen_for_wake()

    def listen_for_command(self) -> Transcript:
        return self._capture_and_transcribe_command()

    def _listen_for_wake(self) -> Transcript:
        wake_phrases = ("자비스", "자 비스")
        recognizer = self._wake_stt.stream(phrases=wake_phrases)
        started_ms = self._clock.monotonic_ms()
        duration_ms = 0
        self._events.emit(
            "voice.recording",
            {"state": "started", "device": self._device_label, "duration_ms": 0},
        )
        _write(
            self._output,
            f"[마이크 켜짐] 웨이크워드를 듣고 있습니다. (장치: {self._device_label})",
        )
        transcript = ""
        last_preview = ""
        next_input_status_ms = INPUT_STATUS_INTERVAL_MS
        microphone: MicrophoneStream | None = None
        try:
            with self._microphone_factory() as microphone:
                while True:
                    frame = microphone.next_frame(timeout_s=0.5)
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
                    if update.final and self._wake_word in normalized:
                        transcript = update.text
                        break
                    if update.final:
                        recognizer = self._wake_stt.stream(phrases=wake_phrases)
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

    def _capture_and_transcribe_command(self) -> Transcript:
        started_ms = self._clock.monotonic_ms()
        capture = SpeechCapture(self._capture_policy)
        self._events.emit(
            "voice.recording",
            {"state": "started", "device": self._device_label, "duration_ms": 0},
        )
        _write(
            self._output,
            f"[마이크 켜짐] 요청을 듣고 있습니다. (장치: {self._device_label})",
        )
        next_level_status_ms = LEVEL_STATUS_INTERVAL_MS
        microphone: MicrophoneStream | None = None
        try:
            with self._microphone_factory() as microphone:
                while not capture.finished:
                    frame = microphone.next_frame(timeout_s=0.5)
                    if frame is None:
                        elapsed_ms = max(0, self._clock.monotonic_ms() - started_ms)
                        if elapsed_ms >= self._capture_policy.max_duration_ms:
                            capture.expire()
                        continue
                    capture.feed(frame)
                    if capture.input_duration_ms >= next_level_status_ms:
                        state = "음성 감지" if capture.speech_started else "대기"
                        _write(self._output, f"[마이크 음량] {frame.rms_dbfs:.1f} dBFS · {state}")
                        next_level_status_ms += LEVEL_STATUS_INTERVAL_MS
        finally:
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
            _write(self._output, "[마이크 꺼짐]")

        if capture.finish_reason == "trailing_silence":
            _write(self._output, "[녹음 종료] 연속 무음을 감지했습니다.")
        else:
            _write(self._output, "[녹음 종료] 최대 녹음 시간에 도달했습니다.")
        if not capture.acceptable or not capture.frames:
            self._emit_command_result(
                Transcript("", "ko", capture.input_duration_ms, None),
                started_ms=started_ms,
                state="no_speech",
            )
            return Transcript("", "ko", capture.input_duration_ms, None)

        _write(self._output, "[Whisper 처리] 한국어 질문을 로컬에서 인식하고 있습니다.")
        transcript = self._command_stt.transcribe(capture.frames)
        fallback_reason = self._command_stt.fallback_reason
        if fallback_reason is not None:
            _write(self._output, "[Whisper 폴백] CUDA를 사용할 수 없어 CPU int8로 전환했습니다.")
        quality = (
            f"평균 logprob={_format_optional(transcript.avg_logprob)}, "
            f"무음 확률={_format_optional(transcript.no_speech_probability)}, "
            f"장치={self._command_stt.active_device}"
        )
        if transcript.text:
            _write(self._output, f"[Whisper 확정] {_preview_text(transcript.text)} ({quality})")
        accepted = transcript_passes_quality(
            transcript,
            min_avg_logprob=self._min_avg_logprob,
            max_no_speech_probability=self._max_no_speech_probability,
        )
        self._emit_command_result(
            transcript,
            started_ms=started_ms,
            state="accepted" if accepted else "rejected",
        )
        if accepted:
            return transcript
        _write(self._output, f"[인식 거부] 품질 기준을 통과하지 못했습니다. ({quality})")
        return Transcript(
            "",
            transcript.language,
            transcript.duration_ms,
            transcript.confidence,
            transcript.avg_logprob,
            transcript.no_speech_probability,
        )

    def _emit_command_result(
        self, transcript: Transcript, *, started_ms: int, state: str
    ) -> None:
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


def _format_optional(value: float | None) -> str:
    return "없음" if value is None else f"{value:.3f}"


def microphone_factory(
    device: str,
    *,
    sample_rate: int,
) -> Callable[[], MicrophoneStream]:
    return lambda: MicrophoneStream(device, sample_rate=sample_rate)
