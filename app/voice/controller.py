"""Opt-in local wake-word controller that reuses the text orchestrator."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
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
from app.voice.source_filter import SourceDecision, SourceFilter, SourcePath
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

EXIT_PHRASES = frozenset({"종료", "자비스종료", "그만", "그만해"})
MISHEARD_TEXT = "잘 듣지 못했습니다. 다시 자비스라고 불러 주세요."
EXIT_TEXT = "안전하게 종료합니다."
INPUT_STATUS_INTERVAL_MS = 2_000
LEVEL_STATUS_INTERVAL_MS = 500
MAX_PREVIEW_CHARS = 160
WAKE_PHRASES = ("자비스", "자 비스")
_SILENCE_FRAME = AudioFrame(b"\x00\x00" * 4_000, 16_000)


class VoiceEventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class TurnStart:
    mode: Literal["standalone", "inline_command"]
    command: Transcript | None


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
        barge_in_gate_factory: Callable[[], BargeInGate] | None = None,
        interrupt_hotkey_factory: InterruptHotkeyFactory | None = None,
        source_filter: SourceFilter | None = None,
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
        self._wake_word_text = wake_word.strip()
        self._wake_word = normalize_spoken_command(wake_word)
        self._capture_policy = capture_policy
        self._barge_in_gate_factory = barge_in_gate_factory
        self._interrupt_hotkey_factory = interrupt_hotkey_factory
        self._source_filter = source_filter
        self._min_avg_logprob = min_avg_logprob
        self._max_no_speech_probability = max_no_speech_probability
        self._device_label = device_label
        self._events = events
        self._clock = clock
        self._output = output_stream

    def await_turn_start(self) -> TurnStart:
        return self._await_wake_session()

    def wait_for_wake(self) -> Transcript:
        """Compatibility helper: wait until a wake word is accepted."""
        started = self._await_wake_session()
        if started.mode == "inline_command" and started.command is not None:
            return Transcript(
                self._wake_word_text,
                started.command.language,
                started.command.duration_ms,
                started.command.confidence,
            )
        return Transcript(self._wake_word_text, "ko", 0, None)

    def listen_for_command(self) -> Transcript:
        return self._capture_and_transcribe_command()

    def wait_for_barge_in(self, speech_done: Event, *, spoken_text: str = "") -> bool:
        """Watch wake-word results and optional hotkey while TTS is speaking."""
        if speech_done.is_set() or self._barge_in_gate_factory is None:
            return False
        gate = self._barge_in_gate_factory()
        recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
        spoken_text_contains_wake = self._wake_word in normalize_spoken_command(spoken_text)
        hotkey = (
            self._interrupt_hotkey_factory()
            if self._interrupt_hotkey_factory is not None
            else NullInterruptHotkey()
        )
        detected = False
        interrupt_source = ""
        duration_ms = 0
        last_preview = ""
        next_level_status_ms = LEVEL_STATUS_INTERVAL_MS
        partial_updates = 0
        final_updates = 0
        gate_frames = 0
        onset_count = 0
        voice_frames = 0
        peak_dbfs = -96.0
        recent_frames: deque[AudioFrame] = deque()
        recent_ms = 0
        microphone: MicrophoneStream | None = None
        self._events.emit(
            "voice.barge_in",
            {
                "state": "started",
                "device": self._device_label,
                "duration_ms": 0,
                "gate": "adaptive_vad",
            },
        )
        _write(
            self._output,
            "[끼어들기 감시] 답변 중 '자비스'라고 부르거나 중단 단축키를 누르면 멈춥니다.",
        )
        try:
            with self._microphone_factory() as microphone:
                while not speech_done.is_set():
                    if hotkey.poll():
                        detected = True
                        interrupt_source = "hotkey"
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
                        _write(self._output, "[단축키 끼어들기] 답변을 중단합니다.")
                        break
                    frame = microphone.next_frame(timeout_s=0.1)
                    if frame is None:
                        continue
                    duration_ms += frame.duration_ms
                    decision = gate.feed(frame)
                    level_dbfs = decision.level_dbfs
                    peak_dbfs = max(peak_dbfs, level_dbfs)
                    voice_frames += int(decision.voice)
                    onset_count += int(decision.onset)
                    if duration_ms >= next_level_status_ms:
                        state = (
                            "onset"
                            if decision.onset
                            else "통과"
                            if decision.open
                            else "감시 중"
                        )
                        voice_state = "음성" if decision.voice else "비음성"
                        _write(
                            self._output,
                            f"[끼어들기 마이크] {level_dbfs:.1f} dBFS · "
                            f"기준 {decision.baseline_dbfs:.1f} dBFS · "
                            f"VAD {voice_state} · {state}",
                        )
                        next_level_status_ms += LEVEL_STATUS_INTERVAL_MS
                    if decision.reset_recognizer:
                        recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
                        last_preview = ""

                    for gated_frame in decision.frames:
                        gate_frames += 1
                        recent_ms = _push_recent_frame(
                            recent_frames,
                            gated_frame,
                            recent_ms,
                            window_ms=self._source_window_ms(),
                        )
                        update = recognizer.feed(gated_frame.pcm)
                        if update.final:
                            final_updates += 1
                        else:
                            partial_updates += 1
                        preview = _preview_text(update.text)
                        if preview and preview != last_preview:
                            label = (
                                "끼어들기 STT 확정" if update.final else "끼어들기 STT 부분"
                            )
                            _write(self._output, f"[{label}] {preview}")
                            last_preview = preview

                        kind = wake_match_kind(update.text, self._wake_word_text)
                        if spoken_text_contains_wake:
                            wake_recognized = update.final and kind == "standalone"
                        else:
                            wake_recognized = kind in {"standalone", "prefix"} and (
                                update.final or kind == "standalone"
                            )
                        if wake_recognized:
                            if not self._source_accepts(tuple(recent_frames), path="barge_in"):
                                recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
                                last_preview = ""
                                continue
                            detected = True
                            interrupt_source = "wake_word"
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
                            _write(self._output, "[말 끼어들기] '자비스'를 감지했습니다.")
                            break
                        if update.final:
                            recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
                            last_preview = ""
                    if detected:
                        break
        finally:
            hotkey.close()
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
        return detected

    def _await_wake_session(self) -> TurnStart:
        recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
        capture = SpeechCapture(self._capture_policy)
        started_ms = self._clock.monotonic_ms()
        duration_ms = 0
        wake_detected = False
        last_preview = ""
        next_input_status_ms = INPUT_STATUS_INTERVAL_MS
        recent_frames: deque[AudioFrame] = deque()
        recent_ms = 0
        microphone: MicrophoneStream | None = None
        self._events.emit(
            "voice.recording",
            {"state": "started", "device": self._device_label, "duration_ms": 0},
        )
        _write(
            self._output,
            f"[마이크 켜짐] 웨이크워드를 듣고 있습니다. (장치: {self._device_label})",
        )
        try:
            with self._microphone_factory() as microphone:
                while True:
                    frame = microphone.next_frame(timeout_s=0.5)
                    elapsed_ms = max(0, self._clock.monotonic_ms() - started_ms)
                    if frame is None:
                        if wake_detected and not capture.finished:
                            # Mic poll timeout counts as silence so trailing-silence
                            # can finish without depending on wall-clock advancement.
                            capture.feed(_SILENCE_FRAME)
                            duration_ms += _SILENCE_FRAME.duration_ms
                        if wake_detected and capture.finished:
                            break
                        if wake_detected and elapsed_ms >= self._capture_policy.max_duration_ms:
                            capture.expire()
                            break
                        continue
                    duration_ms += frame.duration_ms
                    if not wake_detected:
                        recent_ms = _push_recent_frame(
                            recent_frames,
                            frame,
                            recent_ms,
                            window_ms=self._source_window_ms(),
                        )
                    if not capture.finished:
                        capture.feed(frame)
                    if wake_detected:
                        # Vosk wake grammar must not keep mapping later words to "자비스".
                        if duration_ms >= next_input_status_ms:
                            state = "음성 감지" if capture.speech_started else "대기"
                            _write(
                                self._output,
                                f"[호출 후 녹음] {frame.rms_dbfs:.1f} dBFS · {state} "
                                "(Whisper로 질문 인식)",
                            )
                            next_input_status_ms += LEVEL_STATUS_INTERVAL_MS
                        if capture.finished:
                            break
                        if elapsed_ms >= self._capture_policy.max_duration_ms:
                            capture.expire()
                            break
                        continue

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
                    if update.final:
                        kind = wake_match_kind(update.text, self._wake_word_text)
                        if kind in {"standalone", "prefix"}:
                            if self._source_accepts(tuple(recent_frames), path="wake"):
                                wake_detected = True
                                _write(
                                    self._output,
                                    "[호출 확정] 이어서 같은 발화를 듣고 "
                                    "Whisper로 인식합니다.",
                                )
                            else:
                                recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
                                capture.clear()
                                last_preview = ""
                        else:
                            recognizer = self._wake_stt.stream(phrases=WAKE_PHRASES)
                            capture.clear()
                            last_preview = ""
                    if wake_detected and capture.finished:
                        break
                    if wake_detected and elapsed_ms >= self._capture_policy.max_duration_ms:
                        capture.expire()
                        break
        finally:
            elapsed_ms = max(0, self._clock.monotonic_ms() - started_ms)
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
            _write(self._output, "[마이크 꺼짐]")

        return self._command_from_wake_capture(capture, started_ms=started_ms)

    def _command_from_wake_capture(
        self, capture: SpeechCapture, *, started_ms: int
    ) -> TurnStart:
        if capture.finish_reason == "trailing_silence":
            _write(self._output, "[녹음 종료] 연속 무음을 감지했습니다.")
        elif capture.finish_reason == "max_duration":
            _write(self._output, "[녹음 종료] 최대 녹음 시간에 도달했습니다.")
        if not capture.acceptable or not capture.frames:
            _write(self._output, "[한 문장 명령] 추가 질문이 없어 안내 후 질문을 듣습니다.")
            return TurnStart("standalone", None)

        if not self._source_accepts(capture.frames, path="command"):
            _write(self._output, "[한 문장 명령] 소스 필터가 질문을 무시했습니다.")
            return TurnStart("standalone", None)

        _write(self._output, "[Whisper 처리] 호출과 질문을 한 문장으로 인식합니다.")
        transcript = self._command_stt.transcribe(capture.frames)
        if self._command_stt.fallback_reason is not None:
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
        command_text = strip_leading_wake_word(transcript.text, self._wake_word_text)
        if not accepted or not command_text:
            self._emit_command_result(
                transcript,
                started_ms=started_ms,
                state="standalone_wake" if accepted else "rejected",
            )
            _write(self._output, "[한 문장 명령] 질문 부분이 없어 안내 후 질문을 듣습니다.")
            return TurnStart("standalone", None)

        command = Transcript(
            command_text,
            transcript.language,
            transcript.duration_ms,
            transcript.confidence,
            transcript.avg_logprob,
            transcript.no_speech_probability,
        )
        self._emit_command_result(command, started_ms=started_ms, state="inline_command")
        _write(self._output, f"[한 문장 명령] {command_text}")
        return TurnStart("inline_command", command)

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

        if not self._source_accepts(capture.frames, path="command"):
            self._emit_command_result(
                Transcript("", "ko", capture.input_duration_ms, None),
                started_ms=started_ms,
                state="source_filtered",
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

    def _source_window_ms(self) -> int:
        if self._source_filter is None:
            return 1_200
        return self._source_filter.policy.analysis_window_ms

    def _source_accepts(self, frames: Sequence[AudioFrame], *, path: SourcePath) -> bool:
        if self._source_filter is None:
            return True
        decision = self._source_filter.classify(frames, path=path)
        self._emit_source_decision(decision, path=path)
        if self._source_filter.consume_music_warning():
            _write(
                self._output,
                "[소스 필터] 음악 분류기를 쓸 수 없어 기존 동작으로 통과합니다.",
            )
        if self._source_filter.consume_speaker_warning():
            _write(
                self._output,
                "[소스 필터] 화자 필터를 쓸 수 없어 기존 동작으로 통과합니다.",
            )
        if decision.accept:
            if decision.label in {"owner", "unknown"} and decision.speaker_score is not None:
                _write(
                    self._output,
                    f"[소스 필터] {decision.label} 통과 "
                    f"(화자 점수 {decision.speaker_score:.2f})",
                )
            return True
        if decision.label == "music":
            score = (
                f" · 음악 점수 {decision.music_score:.2f}"
                if decision.music_score is not None
                else ""
            )
            _write(self._output, f"[소스 필터] 음악으로 무시{score}")
        else:
            score = (
                f" · 화자 점수 {decision.speaker_score:.2f}"
                if decision.speaker_score is not None
                else ""
            )
            _write(
                self._output,
                f"[소스 필터] 다른 목소리로 무시{score} "
                "(재등록: scripts\\enroll_voice.py)",
            )
        return False

    def _emit_source_decision(self, decision: SourceDecision, *, path: SourcePath) -> None:
        self._events.emit(
            "voice.source_filter",
            {
                "path": path,
                "label": decision.label,
                "accept": decision.accept,
                "reason": decision.reason,
                "music_score": decision.music_score,
                "speaker_score": decision.speaker_score,
            },
        )


def _push_recent_frame(
    frames: deque[AudioFrame],
    frame: AudioFrame,
    current_ms: int,
    *,
    window_ms: int,
) -> int:
    frames.append(frame)
    total_ms = current_ms + frame.duration_ms
    while frames and total_ms - frames[0].duration_ms >= window_ms and len(frames) > 1:
        removed = frames.popleft()
        total_ms -= removed.duration_ms
    return total_ms


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
        _write(
            self._output,
            "로컬 음성 모드입니다. '자비스'와 질문을 이어서 말하거나, "
            "호출 후 안내가 나오면 질문하세요. 종료는 Ctrl+C 또는 '종료'입니다.",
        )
        try:
            while max_interactions is None or interactions < max_interactions:
                if wake_already_detected:
                    wake_already_detected = False
                    self._speak(self._acknowledgement)
                    transcript = self._listener.listen_for_command()
                else:
                    turn = self._listener.await_turn_start()
                    if turn.mode == "inline_command" and turn.command is not None:
                        transcript = turn.command
                    else:
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
