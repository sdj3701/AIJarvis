"""Opt-in local wake-word controller that reuses the text orchestrator."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from threading import Event, Thread
from typing import Any, Protocol, TextIO

from app.core.clock import Clock
from app.core.errors import JarvisError
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
BARGE_IN_RECENT_SPEECH_MS = 1_000
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

    def wait_for_barge_in(self, speech_done: Event, *, spoken_text: str = "") -> bool:
        """Watch partial and final wake-word results while TTS is speaking."""
        if speech_done.is_set():
            return False
        recognizer = self._wake_stt.stream()
        spoken_text_contains_wake = self._wake_word in normalize_spoken_command(spoken_text)
        detected = False
        duration_ms = 0
        last_loud_input_ms: int | None = None
        last_preview = ""
        next_level_status_ms = LEVEL_STATUS_INTERVAL_MS
        partial_updates = 0
        final_updates = 0
        peak_dbfs = -96.0
        microphone: MicrophoneStream | None = None
        self._events.emit(
            "voice.barge_in",
            {"state": "started", "device": self._device_label, "duration_ms": 0},
        )
        _write(self._output, "[끼어들기 감시] 답변 중 '자비스'라고 부르면 중단합니다.")
        try:
            with self._microphone_factory() as microphone:
                while not speech_done.is_set():
                    frame = microphone.next_frame(timeout_s=0.1)
                    if frame is None:
                        continue
                    duration_ms += frame.duration_ms
                    level_dbfs = frame.rms_dbfs
                    peak_dbfs = max(peak_dbfs, level_dbfs)
                    if level_dbfs >= self._capture_policy.speech_threshold_dbfs:
                        last_loud_input_ms = duration_ms
                    if duration_ms >= next_level_status_ms:
                        _write(
                            self._output,
                            f"[끼어들기 마이크] {level_dbfs:.1f} dBFS · 감시 중",
                        )
                        next_level_status_ms += LEVEL_STATUS_INTERVAL_MS

                    update = recognizer.feed(frame.pcm)
                    if update.final:
                        final_updates += 1
                    else:
                        partial_updates += 1
                    preview = _preview_text(update.text)
                    if preview and preview != last_preview:
                        label = "끼어들기 STT 확정" if update.final else "끼어들기 STT 부분"
                        _write(self._output, f"[{label}] {preview}")
                        last_preview = preview

                    normalized = normalize_spoken_command(update.text)
                    wake_seen = self._wake_word in normalized
                    recent_loud_input = (
                        last_loud_input_ms is not None
                        and duration_ms - last_loud_input_ms <= BARGE_IN_RECENT_SPEECH_MS
                    )
                    partial_allowed = not spoken_text_contains_wake
                    wake_recognized = wake_seen and (update.final or partial_allowed)
                    if wake_recognized and recent_loud_input:
                        detected = True
                        self._events.emit(
                            "voice.barge_in",
                            {
                                "state": "detected",
                                "device": self._device_label,
                                "duration_ms": duration_ms,
                                "recognition_state": "final" if update.final else "partial",
                                "level_dbfs": round(level_dbfs, 1),
                            },
                        )
                        _write(self._output, "[말 끼어들기] '자비스'를 감지했습니다.")
                        break
                    if update.final:
                        recognizer = self._wake_stt.stream()
        finally:
            self._events.emit(
                "voice.barge_in",
                {
                    "state": "stopped",
                    "device": self._device_label,
                    "duration_ms": duration_ms,
                    "detected": detected,
                    "overflows": 0 if microphone is None else microphone.overflows,
                    "partial_updates": partial_updates,
                    "final_updates": final_updates,
                    "peak_dbfs": round(peak_dbfs, 1),
                },
            )
        return detected

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
        wake_already_detected = False
        _write(self._output, "로컬 음성 모드입니다. 종료하려면 Ctrl+C 또는 '종료'라고 말하세요.")
        try:
            while max_interactions is None or interactions < max_interactions:
                if wake_already_detected:
                    wake_already_detected = False
                else:
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
                wake_already_detected = self._speak_interruptibly(
                    prepared.text,
                    refused=prepared.refused,
                )
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

    def _speak_interruptibly(self, text: str, *, refused: bool = False) -> bool:
        started_ms = self._clock.monotonic_ms()
        speech_done = Event()
        errors: list[BaseException] = []

        def run_speech() -> None:
            try:
                self._tts.speak(text)
            except BaseException as error:
                errors.append(error)
            finally:
                speech_done.set()

        worker = Thread(target=run_speech, name="jarvis-tts", daemon=True)
        worker.start()
        interrupted = False
        monitor_unavailable = False
        try:
            interrupted = self._listener.wait_for_barge_in(speech_done, spoken_text=text)
        except JarvisError as error:
            monitor_unavailable = True
            _write(self._output, f"[끼어들기 감시 불가] {error.user_message}")
        except BaseException:
            self._tts.cancel()
            worker.join(timeout=5)
            raise
        if interrupted:
            self._tts.cancel()
        worker.join(timeout=5 if interrupted else 65)
        if worker.is_alive():
            self._tts.cancel()
            raise JarvisError("중단한 음성 합성 프로세스가 종료되지 않았습니다.")
        if errors and not interrupted:
            raise errors[0]

        state = "interrupted" if interrupted else "refused" if refused else "completed"
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
        if interrupted:
            _write(self._output, "[답변 중단] 새 질문을 받을 준비를 합니다.")
        return interrupted


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
