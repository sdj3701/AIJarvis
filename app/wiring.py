"""Composition root for all Phase 0 runtime dependencies."""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from app import __version__
from app.budget import BudgetGuard, SQLiteBudgetLedger
from app.cli import run_cli
from app.config.loader import DEFAULT_CONFIG_DIR, load_config
from app.config.models import LoadedConfig
from app.config.secrets import SecretLoader
from app.core.clock import (
    Clock,
    RandomSource,
    Sleeper,
    SystemClock,
    SystemRandom,
    SystemSleeper,
)
from app.core.errors import ConfigError, ExitCode, JarvisError, exit_code_for
from app.core.ids import PrefixedIdFactory, SystemIdFactory
from app.core.test_hooks import CrashTestHook, CrashTestLLMClient
from app.llm.base import LLMClient
from app.llm.ollama_client import OllamaClient
from app.memory.migrations import initialize_database
from app.memory.store import SQLiteSessionStore
from app.orchestrator.loop import ChatOrchestrator
from app.orchestrator.recovery import recover_startup
from app.telemetry.events import JsonlEventWriter
from app.telemetry.masking import LogMasker
from app.telemetry.metrics import SQLiteMetrics
from app.ui.single_instance import SingleInstanceLock
from app.voice.barge_in_gate import (
    BargeInGate,
    BargeInGatePolicy,
    WebRtcVoiceActivityDetector,
)
from app.voice.controller import LocalVoiceListener, VoiceController, microphone_factory
from app.voice.microphone import SpeechCapturePolicy
from app.voice.stt import FasterWhisperSTTEngine, VoskSTTEngine
from app.voice.tts import WindowsSapiTTS


@dataclass(frozen=True, slots=True)
class Runtime:
    config: LoadedConfig
    clock: Clock
    ids: PrefixedIdFactory
    masker: LogMasker
    events: JsonlEventWriter
    secrets: SecretLoader
    lock: SingleInstanceLock
    memory_db: Path
    llm: LLMClient
    sessions: SQLiteSessionStore
    budget: BudgetGuard
    sleeper: Sleeper
    random: RandomSource
    test_hook: CrashTestHook
    metrics: SQLiteMetrics


def _data_path(config: LoadedConfig, configured: Path) -> Path:
    if configured.is_absolute():
        return configured.resolve(strict=False)
    return (config.settings.paths.data_root / configured).resolve(strict=False)


def build(
    config_dir: Path = DEFAULT_CONFIG_DIR,
    *,
    clock: Clock | None = None,
    ids: PrefixedIdFactory | None = None,
    llm: LLMClient | None = None,
) -> Runtime:
    """Load configuration and construct every Phase 0 service in one place."""
    loaded = load_config(config_dir)
    runtime_clock = clock or SystemClock()
    runtime_ids = ids or SystemIdFactory()
    test_hook = CrashTestHook.from_environment(dev_mode=loaded.settings.dev_mode)
    runtime_llm = llm
    if runtime_llm is None and test_hook.enabled and os.environ.get("JARVIS_LLM") == "fake":
        runtime_llm = CrashTestLLMClient()
    masker = LogMasker.from_policy(loaded.policies.privacy)
    logs_dir = _data_path(loaded, loaded.settings.paths.logs_dir)
    state_dir = _data_path(loaded, loaded.settings.paths.state_dir)
    events = JsonlEventWriter(
        logs_dir,
        clock=runtime_clock,
        masker=masker,
        fsync_events=loaded.settings.logging.fsync_events,
    )
    secrets = SecretLoader(
        dev_mode=loaded.settings.dev_mode,
        masker=masker,
        events=events,
    )
    memory_db = _data_path(loaded, loaded.settings.paths.memory_db)
    metrics = SQLiteMetrics(memory_db, enabled=loaded.settings.metrics.enabled)
    return Runtime(
        config=loaded,
        clock=runtime_clock,
        ids=runtime_ids,
        masker=masker,
        events=events,
        secrets=secrets,
        lock=SingleInstanceLock(state_dir / "jarvis.lock"),
        memory_db=memory_db,
        llm=runtime_llm or OllamaClient(loaded.settings.llm),
        sessions=SQLiteSessionStore(
            memory_db,
            data_root=loaded.settings.paths.data_root,
            raw_dir=_data_path(loaded, loaded.settings.paths.raw_dir),
            quarantine_dir=state_dir / "quarantine",
            fsync_raw=loaded.settings.logging.fsync_events,
        ),
        budget=BudgetGuard(SQLiteBudgetLedger(memory_db), loaded.settings.budget),
        sleeper=SystemSleeper(),
        random=SystemRandom(),
        test_hook=test_hook,
        metrics=metrics,
    )


def _record_error(runtime: Runtime, error: BaseException, *, handled: bool) -> None:
    if isinstance(error, JarvisError):
        user_message = error.user_message
        detail = error.detail
    else:
        user_message = "예상하지 못한 오류가 발생했습니다."
        detail = {}
    with suppress(Exception):
        runtime.events.emit(
            "error",
            {
                "error_type": type(error).__name__,
                "user_message": user_message,
                "detail": detail,
                "handled": handled,
            },
            level="error",
        )


def run_application(
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    input_stream: TextIO,
    output_stream: TextIO,
    error_stream: TextIO,
    once: str | None = None,
    voice: bool = False,
    llm: LLMClient | None = None,
) -> int:
    """Run startup, CLI, and cleanup with production-safe exception reporting."""
    runtime: Runtime | None = None
    started = False
    started_ms = 0
    exit_code = int(ExitCode.UNHANDLED_ERROR)
    try:
        runtime = build(config_dir, llm=llm)
        runtime.lock.acquire()
        initialize_database(runtime.memory_db)
        started_ms = runtime.clock.monotonic_ms()
        runtime.events.emit(
            "app.start",
            {
                "version": __version__,
                "pid": os.getpid(),
                "config_hash": runtime.config.config_hash,
                "dev_mode": runtime.config.settings.dev_mode,
            },
        )
        started = True
        recover_startup(runtime.config.settings.paths.data_root, runtime.events)
        verifier = getattr(runtime.llm, "verify_model", None)
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
            verify_model=verifier if callable(verifier) else None,
            test_hook=runtime.test_hook,
            metrics=runtime.metrics,
        )
        if voice:
            voice_settings = runtime.config.settings.voice
            if not voice_settings.enabled:
                raise ConfigError("설정에서 음성 모드가 비활성화되어 있습니다.")
            model_path = (
                _data_path(runtime.config, runtime.config.settings.paths.models_dir)
                / voice_settings.stt.wake.model
            )
            wake_stt = VoskSTTEngine(
                model_path,
                sample_rate=voice_settings.stt.sample_rate_hz,
                language=voice_settings.stt.language,
                expected_archive_sha256=voice_settings.stt.wake.model_archive_sha256,
            )
            command_settings = voice_settings.stt.command
            command_model_path = (
                _data_path(runtime.config, runtime.config.settings.paths.models_dir)
                / command_settings.model
            )
            command_stt = FasterWhisperSTTEngine(
                command_model_path,
                expected_model_sha256=command_settings.model_sha256,
                language=voice_settings.stt.language,
                device=command_settings.device,
                compute_type=command_settings.compute_type,
                cpu_fallback=command_settings.cpu_fallback,
                cpu_compute_type=command_settings.cpu_compute_type,
                beam_size=command_settings.beam_size,
                vad_filter=command_settings.vad_filter,
                initial_prompt=command_settings.initial_prompt,
            )
            barge_in_settings = voice_settings.barge_in
            barge_in_policy = BargeInGatePolicy(
                speech_threshold_dbfs=barge_in_settings.speech_threshold_dbfs,
                min_onset_rise_db=barge_in_settings.min_onset_rise_db,
                baseline_window_ms=barge_in_settings.baseline_window_ms,
                startup_guard_ms=barge_in_settings.startup_guard_ms,
                recent_speech_ms=barge_in_settings.recent_speech_ms,
                pre_roll_ms=barge_in_settings.pre_roll_ms,
            )
            barge_in_gate_factory: Callable[[], BargeInGate] | None = None
            if barge_in_settings.enabled:

                def create_barge_in_gate() -> BargeInGate:
                    return BargeInGate(
                        barge_in_policy,
                        WebRtcVoiceActivityDetector(
                            mode=barge_in_settings.vad_mode,
                            frame_ms=barge_in_settings.vad_frame_ms,
                            min_voiced_ratio=barge_in_settings.vad_min_voiced_ratio,
                        ),
                    )

                barge_in_gate_factory = create_barge_in_gate
            listener = LocalVoiceListener(
                wake_stt=wake_stt,
                command_stt=command_stt,
                microphone_factory=microphone_factory(
                    voice_settings.stt.device,
                    sample_rate=voice_settings.stt.sample_rate_hz,
                ),
                wake_word=voice_settings.wake_word,
                capture_policy=SpeechCapturePolicy(
                    pre_roll_ms=command_settings.pre_roll_ms,
                    speech_threshold_dbfs=command_settings.speech_threshold_dbfs,
                    trailing_silence_ms=command_settings.trailing_silence_ms,
                    min_speech_ms=command_settings.min_speech_ms,
                    max_duration_ms=int(voice_settings.stt.max_command_seconds * 1000),
                ),
                barge_in_gate_factory=barge_in_gate_factory,
                min_avg_logprob=command_settings.min_avg_logprob,
                max_no_speech_probability=command_settings.max_no_speech_probability,
                device_label=voice_settings.stt.device,
                events=runtime.events,
                clock=runtime.clock,
                output_stream=output_stream,
            )
            controller = VoiceController(
                listener=listener,
                tts=WindowsSapiTTS(
                    voice_settings.tts.voice,
                    rate=voice_settings.tts.rate,
                ),
                chat=chat,
                masker=runtime.masker,
                acknowledgement=voice_settings.acknowledgement,
                max_tts_chars=voice_settings.tts.max_chars,
                events=runtime.events,
                clock=runtime.clock,
                output_stream=output_stream,
            )
            exit_code = controller.run()
        else:
            exit_code = run_cli(
                input_stream=input_stream,
                output_stream=output_stream,
                once=once,
                chat=chat,
            )
    except KeyboardInterrupt as error:
        exit_code = int(ExitCode.INTERRUPTED)
        output_stream.write("\n입력을 중단하고 안전하게 종료합니다.\n")
        output_stream.flush()
        if runtime is not None and runtime.lock.acquired:
            _record_error(runtime, error, handled=True)
    except JarvisError as error:
        exit_code = int(exit_code_for(error))
        error_stream.write(error.user_message + "\n")
        error_stream.flush()
        if runtime is not None and runtime.lock.acquired:
            _record_error(runtime, error, handled=True)
            if runtime.config.settings.dev_mode:
                traceback.print_exc(file=error_stream)
    except Exception as error:
        exit_code = int(ExitCode.UNHANDLED_ERROR)
        error_stream.write("예상하지 못한 오류가 발생했습니다.\n")
        error_stream.flush()
        if runtime is not None and runtime.lock.acquired:
            _record_error(runtime, error, handled=False)
            if runtime.config.settings.dev_mode:
                traceback.print_exc(file=error_stream)
    finally:
        if runtime is not None:
            if started:
                try:
                    runtime.events.emit(
                        "app.stop",
                        {
                            "exit_code": exit_code,
                            "uptime_ms": max(0, runtime.clock.monotonic_ms() - started_ms),
                        },
                    )
                except Exception:
                    if exit_code == int(ExitCode.SUCCESS):
                        exit_code = int(ExitCode.UNHANDLED_ERROR)
                        error_stream.write("종료 이벤트를 기록하지 못했습니다.\n")
                        error_stream.flush()
            runtime.lock.release()
    return exit_code
