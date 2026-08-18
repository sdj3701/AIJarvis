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
from app.memory.summarizer import SessionSummarizer, SummarizerSettings
from app.orchestrator.loop import ChatOrchestrator
from app.orchestrator.recovery import recover_sessions, recover_startup, recover_tasks
from app.orchestrator.research import ResearchRunner
from app.orchestrator.tasks import TaskStore
from app.privacy.gate import PrivacyGate
from app.rag.fetcher import UrlFetcher
from app.rag.indexer import DocumentIndexer
from app.rag.search_provider import SearchProvider, build_search_provider
from app.safety.approval import InMemoryApprovalStore
from app.safety.gate import SafetyGate
from app.safety.paths import build_sandbox
from app.telemetry.audit import JsonlAuditWriter
from app.telemetry.events import JsonlEventWriter
from app.telemetry.masking import LogMasker
from app.telemetry.metrics import SQLiteMetrics
from app.tools.base import Tool
from app.tools.impl.create_file import CreateFileTool
from app.tools.impl.open_app import OpenAppTool
from app.tools.impl.open_folder import OpenFolderTool
from app.tools.impl.open_url import OpenUrlTool
from app.tools.impl.web_search import DocSearchTool, FetchUrlTool, WebSearchTool
from app.tools.registry import ToolRegistry, build_registry, spec_from_definition
from app.tools.runner import ToolRunner
from app.ui.single_instance import SingleInstanceLock
from app.voice.barge_in_gate import (
    BargeInGate,
    BargeInGatePolicy,
    WebRtcVoiceActivityDetector,
)
from app.voice.controller import LocalVoiceListener, VoiceController, microphone_factory
from app.voice.enrollment import TorchEcapaSpeakerEmbedder, load_speaker_profile
from app.voice.interrupt_hotkey import (
    InterruptHotkeyFactory,
    InterruptHotkeyMonitor,
    create_interrupt_hotkey,
)
from app.voice.microphone import SpeechCapturePolicy
from app.voice.source_filter import (
    SourceFilter,
    SourceFilterPolicy,
    SpeakerSoftMatcher,
    build_music_classifier,
)
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
    privacy_gate: PrivacyGate
    summarizer: SessionSummarizer
    indexer: DocumentIndexer
    tool_registry: ToolRegistry
    tool_runner: ToolRunner
    safety_gate: SafetyGate
    approval_store: InMemoryApprovalStore
    audit_writer: JsonlAuditWriter
    research: ResearchRunner
    search_provider: SearchProvider
    task_store: TaskStore


def _data_path(config: LoadedConfig, configured: Path) -> Path:
    if configured.is_absolute():
        return configured.resolve(strict=False)
    return (config.settings.paths.data_root / configured).resolve(strict=False)


def _build_source_filter(config: LoadedConfig) -> SourceFilter | None:
    settings = config.settings.voice.source_filter
    if not settings.enabled:
        return None
    policy = SourceFilterPolicy(
        enabled=settings.enabled,
        music_enabled=settings.music_enabled,
        speaker_enabled=settings.speaker_enabled,
        music_reject_threshold=settings.music_reject_threshold,
        speech_margin=settings.speech_margin,
        owner_accept_threshold=settings.owner_accept_threshold,
        other_reject_threshold=settings.other_reject_threshold,
        analysis_window_ms=settings.analysis_window_ms,
    )
    music_classifier = None
    if settings.music_enabled:
        music_classifier = build_music_classifier(
            yamnet_model_path=_data_path(config, Path(settings.yamnet_model_path)),
        )
    speaker_embedder = None
    speaker_matcher = None
    if settings.speaker_enabled:
        profile = load_speaker_profile(_data_path(config, Path(settings.profile_path)))
        if profile is not None:
            speaker_embedder = TorchEcapaSpeakerEmbedder(
                _data_path(config, Path(settings.ecapa_model_dir)),
            )
            speaker_matcher = SpeakerSoftMatcher(
                profile.embedding,
                owner_accept_threshold=settings.owner_accept_threshold,
                other_reject_threshold=settings.other_reject_threshold,
            )
    source_filter = SourceFilter(
        policy,
        music_classifier=music_classifier,
        speaker_embedder=speaker_embedder,
        speaker_matcher=speaker_matcher,
    )
    # Warm ECAPA on voice start so the first wake is not blocked by model fetch.
    if isinstance(speaker_embedder, TorchEcapaSpeakerEmbedder):
        with suppress(Exception):
            speaker_embedder.warm()
    return source_filter


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
    privacy_gate = PrivacyGate(
        masker=masker,
        privacy=loaded.policies.privacy,
        refuse_kinds=frozenset(loaded.policies.privacy.outputs.memory_write.refuse_kinds),
        mark_sensitive_kinds=frozenset(
            loaded.policies.privacy.outputs.memory_write.mark_sensitive_kinds
        ),
        events=events,
    )
    budget = BudgetGuard(SQLiteBudgetLedger(memory_db), loaded.settings.budget)
    docs_dir = _data_path(loaded, loaded.settings.paths.docs_dir)
    indexer = DocumentIndexer(
        database_path=memory_db,
        docs_root=docs_dir,
        settings=loaded.settings.rag,
        document_policy=loaded.policies.privacy.api_transmission.documents,
        ids=runtime_ids,
        events=events,
    )
    search_provider = build_search_provider(loaded.settings.rag.search.provider)
    fetcher = UrlFetcher(
        fetch_settings=loaded.settings.rag.fetch,
        network=loaded.policies.tools.network,
    )
    phase = 5
    enabled = {
        defn.name: spec_from_definition(defn)
        for defn in loaded.policies.tools.tools
        if defn.enabled and defn.phase <= phase
    }
    implementations: dict[str, Tool] = {}
    if "web_search" in enabled:
        implementations["web_search"] = WebSearchTool(
            spec=enabled["web_search"],
            provider=search_provider,
            gate=privacy_gate,
            budget=budget,
            default_max_results=loaded.settings.rag.search.max_results,
            cost_per_request=loaded.settings.rag.search.cost_per_request,
        )
    if "doc_search" in enabled:
        implementations["doc_search"] = DocSearchTool(
            spec=enabled["doc_search"],
            indexer=indexer,
            default_max_results=loaded.settings.rag.search.max_results,
        )
    if "fetch_url" in enabled:
        implementations["fetch_url"] = FetchUrlTool(
            spec=enabled["fetch_url"],
            fetcher=fetcher,
        )
    if "open_app" in enabled:
        implementations["open_app"] = OpenAppTool(spec=enabled["open_app"])
    if "open_folder" in enabled:
        implementations["open_folder"] = OpenFolderTool(spec=enabled["open_folder"])
    if "open_url" in enabled:
        implementations["open_url"] = OpenUrlTool(spec=enabled["open_url"])
    if "create_file" in enabled:
        implementations["create_file"] = CreateFileTool(spec=enabled["create_file"])
    tool_registry = build_registry(
        loaded.policies.tools, phase=phase, implementations=implementations
    )
    sandbox = build_sandbox(loaded.settings, loaded.policies.tools.sandbox)
    safety_gate = SafetyGate.from_config(loaded.settings, loaded.policies.tools)
    approval_store = InMemoryApprovalStore(
        ids=runtime_ids,
        ticket_ttl_s=loaded.policies.tools.approval.ticket_ttl_s,
        voice_max_risk=loaded.policies.tools.approval.voice_max_risk,
    )
    audit_writer = JsonlAuditWriter(
        logs_dir=logs_dir,
        database_path=memory_db,
        clock=runtime_clock,
        fsync=loaded.settings.logging.fsync_events,
    )
    tool_runner = ToolRunner(
        registry=tool_registry,
        gate=safety_gate,
        approvals=approval_store,
        audit_writer=audit_writer,
        sandbox=sandbox,
        max_concurrent=loaded.policies.tools.limits.max_concurrent_tools,
        max_output_bytes=loaded.policies.tools.limits.max_output_bytes,
        env_allowlist=tuple(loaded.policies.tools.limits.env_allowlist),
        default_timeout_s=loaded.policies.tools.limits.default_timeout_s,
        privacy=privacy_gate,
    )
    research = ResearchRunner(runner=tool_runner, settings=loaded.settings)
    task_store = TaskStore(memory_db)
    sessions = SQLiteSessionStore(
        memory_db,
        data_root=loaded.settings.paths.data_root,
        raw_dir=_data_path(loaded, loaded.settings.paths.raw_dir),
        quarantine_dir=state_dir / "quarantine",
        fsync_raw=loaded.settings.logging.fsync_events,
        export_dir=_data_path(loaded, loaded.settings.paths.export_dir),
        retrieval_settings=loaded.settings.memory.retrieval,
        key_aliases=loaded.settings.memory.key_aliases,
    )
    summarizer = SessionSummarizer(
        llm=runtime_llm or OllamaClient(loaded.settings.llm),
        store=sessions,
        gate=privacy_gate,
        ids=runtime_ids,
        settings=SummarizerSettings(model_label=loaded.settings.llm.model),
        events=events,
    )
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
        sessions=sessions,
        budget=budget,
        sleeper=SystemSleeper(),
        random=SystemRandom(),
        test_hook=test_hook,
        metrics=metrics,
        privacy_gate=privacy_gate,
        summarizer=summarizer,
        indexer=indexer,
        tool_registry=tool_registry,
        tool_runner=tool_runner,
        safety_gate=safety_gate,
        approval_store=approval_store,
        audit_writer=audit_writer,
        research=research,
        search_provider=search_provider,
        task_store=task_store,
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
        recover_sessions(
            runtime.sessions,
            policy=runtime.config.settings.session.recovery,
            events=runtime.events,
            clock=runtime.clock,
            summarizer=runtime.summarizer,
            settings=runtime.config.settings,
            ids=runtime.ids,
            sleeper=runtime.sleeper,
            random=runtime.random,
        )
        recover_tasks(runtime.task_store, runtime.events)
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
            summarizer=runtime.summarizer,
            indexer=runtime.indexer,
            research=runtime.research,
            tool_runner=runtime.tool_runner,
            safety_gate=runtime.safety_gate,
            approval_store=runtime.approval_store,
            audit_writer=runtime.audit_writer,
            task_store=runtime.task_store,
            privacy_gate=runtime.privacy_gate,
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
            interrupt_hotkey_factory: InterruptHotkeyFactory | None = None
            if (
                barge_in_settings.enabled
                and barge_in_settings.interrupt_hotkey_enabled
            ):
                hotkey_spec = barge_in_settings.interrupt_hotkey

                def create_hotkey_monitor() -> InterruptHotkeyMonitor:
                    return create_interrupt_hotkey(hotkey_spec)

                interrupt_hotkey_factory = create_hotkey_monitor
            source_filter = _build_source_filter(runtime.config)
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
                interrupt_hotkey_factory=interrupt_hotkey_factory,
                source_filter=source_filter,
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
                typed_confirm_phrase=runtime.config.policies.tools.approval.typed_confirm_phrase,
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
