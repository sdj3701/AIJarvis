# 파이썬 공부 | scripts/app/wiring.py
# 설정, 저장소, AI, 도구, 음성 객체를 만들고 서로 연결해 앱을 실행합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Composition root: choose implementations and run process lifetime.

``build()`` constructs services for the current product (chat, memory, tools,
and optional voice). ``run_application()`` is the startup/shutdown sequence:
load → lock → recover → CLI or voice → ``app.stop`` → release lock.
"""

from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from app import __version__
from app.budget import BudgetGuard, SQLiteBudgetLedger
from app.cli import run_cli
from app.config.defaults import DEFAULT_CONFIG_DIR
from app.config.loader import load_config
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
from app.core.recovery import recover_startup
from app.core.test_hooks import CrashTestHook, CrashTestLLMClient
from app.llm.base import LLMClient
from app.llm.launcher import OllamaLauncher
from app.llm.ollama_client import OllamaClient
from app.memory.migrations import initialize_database
from app.memory.store import SQLiteSessionStore
from app.memory.summarizer import SessionSummarizer, SummarizerSettings
from app.orchestrator.loop import ChatOrchestrator
from app.orchestrator.recovery import recover_sessions, recover_tasks
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
from app.tools.impl.close_app import CloseAppTool
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
from app.voice.interrupt_hotkey import (
    InterruptHotkeyFactory,
    InterruptHotkeyMonitor,
    create_interrupt_hotkey,
)
from app.voice.microphone import SpeechCapturePolicy
from app.voice.stt import FasterWhisperSTTEngine, VoskSTTEngine
from app.voice.tts import WindowsSapiTTS


# FoundationRuntime: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class FoundationRuntime:
    """Phase 0 process services: no LLM, tools, or voice."""

    # config: LoadedConfig 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    config: LoadedConfig
    # clock: Clock 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    clock: Clock
    # ids: PrefixedIdFactory 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ids: PrefixedIdFactory
    # masker: LogMasker 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    masker: LogMasker
    # events: JsonlEventWriter 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    events: JsonlEventWriter
    # secrets: SecretLoader 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    secrets: SecretLoader
    # lock: SingleInstanceLock 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    lock: SingleInstanceLock
    # memory_db: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    memory_db: Path


# Runtime: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class Runtime:
    # config: LoadedConfig 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    config: LoadedConfig
    # clock: Clock 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    clock: Clock
    # ids: PrefixedIdFactory 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ids: PrefixedIdFactory
    # masker: LogMasker 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    masker: LogMasker
    # events: JsonlEventWriter 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    events: JsonlEventWriter
    # secrets: SecretLoader 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    secrets: SecretLoader
    # lock: SingleInstanceLock 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    lock: SingleInstanceLock
    # memory_db: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    memory_db: Path
    # llm: LLMClient 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    llm: LLMClient
    # sessions: SQLiteSessionStore 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    sessions: SQLiteSessionStore
    # budget: BudgetGuard 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    budget: BudgetGuard
    # sleeper: Sleeper 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sleeper: Sleeper
    # random: RandomSource 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    random: RandomSource
    # test_hook: CrashTestHook 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    test_hook: CrashTestHook
    # metrics: SQLiteMetrics 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    metrics: SQLiteMetrics
    # privacy_gate: PrivacyGate 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    privacy_gate: PrivacyGate
    # summarizer: SessionSummarizer 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    summarizer: SessionSummarizer
    # indexer: DocumentIndexer 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    indexer: DocumentIndexer
    # tool_registry: ToolRegistry 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    tool_registry: ToolRegistry
    # tool_runner: ToolRunner 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tool_runner: ToolRunner
    # safety_gate: SafetyGate 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    safety_gate: SafetyGate
    # approval_store: InMemoryApprovalStore 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    approval_store: InMemoryApprovalStore
    # audit_writer: JsonlAuditWriter 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    audit_writer: JsonlAuditWriter
    # research: ResearchRunner 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    research: ResearchRunner
    # search_provider: SearchProvider 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    search_provider: SearchProvider
    # task_store: TaskStore 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    task_store: TaskStore


# _data_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config, configured.
# 반환 타입 힌트: Path.
def _data_path(config: LoadedConfig, configured: Path) -> Path:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: configured.is_absolute().
    if configured.is_absolute():
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return configured.resolve(strict=False)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (config.settings.paths.data_root / configured).resolve(strict=False)


# build_foundation(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, clock, ids.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: FoundationRuntime.
def build_foundation(
    config_dir: Path = DEFAULT_CONFIG_DIR,
    *,
    clock: Clock | None = None,
    ids: PrefixedIdFactory | None = None,
) -> FoundationRuntime:
    """Assemble the Phase 0 runtime: config, clock, IDs, events, and secrets."""
    # load_config()의 반환값을 loaded에 대입합니다.
    loaded = load_config(config_dir)
    # 오른쪽 식을 계산한 값을 runtime_clock에 대입합니다.
    runtime_clock = clock or SystemClock()
    # 오른쪽 식을 계산한 값을 runtime_ids에 대입합니다.
    runtime_ids = ids or SystemIdFactory()
    # LogMasker.from_policy()의 반환값을 masker에 대입합니다.
    masker = LogMasker.from_policy(loaded.policies.privacy)
    # _data_path()의 반환값을 logs_dir에 대입합니다.
    logs_dir = _data_path(loaded, loaded.settings.paths.logs_dir)
    # _data_path()의 반환값을 state_dir에 대입합니다.
    state_dir = _data_path(loaded, loaded.settings.paths.state_dir)
    # JsonlEventWriter()의 반환값을 events에 대입합니다.
    events = JsonlEventWriter(
        logs_dir,
        clock=runtime_clock,
        masker=masker,
        fsync_events=loaded.settings.logging.fsync_events,
    )
    # SecretLoader()의 반환값을 secrets에 대입합니다.
    secrets = SecretLoader(
        dev_mode=loaded.settings.dev_mode,
        masker=masker,
        events=events,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return FoundationRuntime(
        config=loaded,
        clock=runtime_clock,
        ids=runtime_ids,
        masker=masker,
        events=events,
        secrets=secrets,
        lock=SingleInstanceLock(state_dir / "jarvis.lock"),
        memory_db=_data_path(loaded, loaded.settings.paths.memory_db),
    )


# build(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, clock, ids, llm.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Runtime.
def build(
    config_dir: Path = DEFAULT_CONFIG_DIR,
    *,
    clock: Clock | None = None,
    ids: PrefixedIdFactory | None = None,
    llm: LLMClient | None = None,
) -> Runtime:
    """Construct every runtime service from the loaded configuration."""
    # load_config()의 반환값을 loaded에 대입합니다.
    loaded = load_config(config_dir)
    # 오른쪽 식을 계산한 값을 runtime_clock에 대입합니다.
    runtime_clock = clock or SystemClock()
    # 오른쪽 식을 계산한 값을 runtime_ids에 대입합니다.
    runtime_ids = ids or SystemIdFactory()
    # CrashTestHook.from_environment()의 반환값을 test_hook에 대입합니다.
    test_hook = CrashTestHook.from_environment(dev_mode=loaded.settings.dev_mode)
    # 오른쪽 식을 계산한 값을 runtime_llm에 대입합니다.
    runtime_llm = llm
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if runtime_llm is None and test_hook.enabled and os.environ.get("JARVIS_LLM") == "fake":
        # CrashTestLLMClient()의 반환값을 runtime_llm에 대입합니다.
        runtime_llm = CrashTestLLMClient()
    # LogMasker.from_policy()의 반환값을 masker에 대입합니다.
    masker = LogMasker.from_policy(loaded.policies.privacy)
    # _data_path()의 반환값을 logs_dir에 대입합니다.
    logs_dir = _data_path(loaded, loaded.settings.paths.logs_dir)
    # _data_path()의 반환값을 state_dir에 대입합니다.
    state_dir = _data_path(loaded, loaded.settings.paths.state_dir)
    # JsonlEventWriter()의 반환값을 events에 대입합니다.
    events = JsonlEventWriter(
        logs_dir,
        clock=runtime_clock,
        masker=masker,
        fsync_events=loaded.settings.logging.fsync_events,
    )
    # SecretLoader()의 반환값을 secrets에 대입합니다.
    secrets = SecretLoader(
        dev_mode=loaded.settings.dev_mode,
        masker=masker,
        events=events,
    )
    # _data_path()의 반환값을 memory_db에 대입합니다.
    memory_db = _data_path(loaded, loaded.settings.paths.memory_db)
    # SQLiteMetrics()의 반환값을 metrics에 대입합니다.
    metrics = SQLiteMetrics(memory_db, enabled=loaded.settings.metrics.enabled)
    # PrivacyGate()의 반환값을 privacy_gate에 대입합니다.
    privacy_gate = PrivacyGate(
        masker=masker,
        privacy=loaded.policies.privacy,
        refuse_kinds=frozenset(loaded.policies.privacy.outputs.memory_write.refuse_kinds),
        mark_sensitive_kinds=frozenset(
            loaded.policies.privacy.outputs.memory_write.mark_sensitive_kinds
        ),
        events=events,
    )
    # BudgetGuard()의 반환값을 budget에 대입합니다.
    budget = BudgetGuard(SQLiteBudgetLedger(memory_db), loaded.settings.budget)
    # _data_path()의 반환값을 docs_dir에 대입합니다.
    docs_dir = _data_path(loaded, loaded.settings.paths.docs_dir)
    # DocumentIndexer()의 반환값을 indexer에 대입합니다.
    indexer = DocumentIndexer(
        database_path=memory_db,
        docs_root=docs_dir,
        models_root=_data_path(loaded, loaded.settings.paths.models_dir),
        settings=loaded.settings.rag,
        document_policy=loaded.policies.privacy.api_transmission.documents,
        ids=runtime_ids,
        events=events,
    )
    # build_search_provider()의 반환값을 search_provider에 대입합니다.
    search_provider = build_search_provider(loaded.settings.rag.search.provider)
    # UrlFetcher()의 반환값을 fetcher에 대입합니다.
    fetcher = UrlFetcher(
        fetch_settings=loaded.settings.rag.fetch,
        network=loaded.policies.tools.network,
    )
    # phase에 숫자 등 고정된 값을 대입합니다.
    phase = 5  # Highest tool phase currently wired; higher-phase specs stay disabled.
    # 오른쪽 식을 계산한 값을 enabled에 대입합니다.
    # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
    enabled = {
        defn.name: spec_from_definition(defn)
        for defn in loaded.policies.tools.tools
        if defn.enabled and defn.phase <= phase
    }
    # implementations에 딕셔너리(키와 값의 쌍)을 대입합니다.
    implementations: dict[str, Tool] = {}
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'web_search' in enabled.
    if "web_search" in enabled:
        # WebSearchTool()의 반환값을 implementations['web_search']에 대입합니다.
        implementations["web_search"] = WebSearchTool(
            spec=enabled["web_search"],
            provider=search_provider,
            gate=privacy_gate,
            budget=budget,
            default_max_results=loaded.settings.rag.search.max_results,
            cost_per_request=loaded.settings.rag.search.cost_per_request,
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'doc_search' in enabled.
    if "doc_search" in enabled:
        # DocSearchTool()의 반환값을 implementations['doc_search']에 대입합니다.
        implementations["doc_search"] = DocSearchTool(
            spec=enabled["doc_search"],
            indexer=indexer,
            default_max_results=loaded.settings.rag.search.max_results,
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'fetch_url' in enabled.
    if "fetch_url" in enabled:
        # FetchUrlTool()의 반환값을 implementations['fetch_url']에 대입합니다.
        implementations["fetch_url"] = FetchUrlTool(
            spec=enabled["fetch_url"],
            fetcher=fetcher,
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'open_app' in enabled.
    if "open_app" in enabled:
        # OpenAppTool()의 반환값을 implementations['open_app']에 대입합니다.
        implementations["open_app"] = OpenAppTool(spec=enabled["open_app"])
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'close_app' in enabled.
    if "close_app" in enabled:
        # CloseAppTool()의 반환값을 implementations['close_app']에 대입합니다.
        implementations["close_app"] = CloseAppTool(spec=enabled["close_app"])
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'open_folder' in enabled.
    if "open_folder" in enabled:
        # OpenFolderTool()의 반환값을 implementations['open_folder']에 대입합니다.
        implementations["open_folder"] = OpenFolderTool(spec=enabled["open_folder"])
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'open_url' in enabled.
    if "open_url" in enabled:
        # OpenUrlTool()의 반환값을 implementations['open_url']에 대입합니다.
        implementations["open_url"] = OpenUrlTool(spec=enabled["open_url"])
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'create_file' in enabled.
    if "create_file" in enabled:
        # CreateFileTool()의 반환값을 implementations['create_file']에 대입합니다.
        implementations["create_file"] = CreateFileTool(spec=enabled["create_file"])
    # build_registry()의 반환값을 tool_registry에 대입합니다.
    tool_registry = build_registry(
        loaded.policies.tools, phase=phase, implementations=implementations
    )
    # build_sandbox()의 반환값을 sandbox에 대입합니다.
    sandbox = build_sandbox(loaded.settings, loaded.policies.tools.sandbox)
    # SafetyGate.from_config()의 반환값을 safety_gate에 대입합니다.
    safety_gate = SafetyGate.from_config(loaded.settings, loaded.policies.tools)
    # implementations.get()의 반환값을 open_tool에 대입합니다.
    open_tool = implementations.get("open_app")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(open_tool, OpenAppTool).
    if isinstance(open_tool, OpenAppTool):
        # 오른쪽 식을 계산한 값을 open_tool.access에 대입합니다.
        open_tool.access = safety_gate.app_access
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: open_tool.access is not None.
        if open_tool.access is not None:
            # open_tool.access.refresh_catalog()을 호출해 작업을 수행합니다.
            open_tool.access.refresh_catalog()
    # InMemoryApprovalStore()의 반환값을 approval_store에 대입합니다.
    approval_store = InMemoryApprovalStore(
        ids=runtime_ids,
        ticket_ttl_s=loaded.policies.tools.approval.ticket_ttl_s,
        voice_max_risk=loaded.policies.tools.approval.voice_max_risk,
    )
    # JsonlAuditWriter()의 반환값을 audit_writer에 대입합니다.
    audit_writer = JsonlAuditWriter(
        logs_dir=logs_dir,
        database_path=memory_db,
        clock=runtime_clock,
        fsync=loaded.settings.logging.fsync_events,
    )
    # ToolRunner()의 반환값을 tool_runner에 대입합니다.
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
    # ResearchRunner()의 반환값을 research에 대입합니다.
    research = ResearchRunner(runner=tool_runner, settings=loaded.settings)
    # TaskStore()의 반환값을 task_store에 대입합니다.
    task_store = TaskStore(memory_db)
    # SQLiteSessionStore()의 반환값을 sessions에 대입합니다.
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
    # OllamaLauncher()의 반환값을 ollama_launcher에 대입합니다.
    ollama_launcher = OllamaLauncher(base_url=loaded.settings.llm.base_url)
    # 오른쪽 식을 계산한 값을 effective_llm에 대입합니다.
    effective_llm = runtime_llm or OllamaClient(loaded.settings.llm, launcher=ollama_launcher)
    # SessionSummarizer()의 반환값을 summarizer에 대입합니다.
    summarizer = SessionSummarizer(
        llm=effective_llm,
        store=sessions,
        gate=privacy_gate,
        ids=runtime_ids,
        settings=SummarizerSettings(model_label=loaded.settings.llm.model),
        events=events,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Runtime(
        config=loaded,
        clock=runtime_clock,
        ids=runtime_ids,
        masker=masker,
        events=events,
        secrets=secrets,
        lock=SingleInstanceLock(state_dir / "jarvis.lock"),
        memory_db=memory_db,
        llm=effective_llm,
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


# _record_error(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: runtime, error, handled.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def _record_error(
    runtime: FoundationRuntime | Runtime,
    error: BaseException,
    *,
    handled: bool,
) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: isinstance(error, JarvisError).
    if isinstance(error, JarvisError):
        # 오른쪽 식을 계산한 값을 user_message에 대입합니다.
        user_message = error.user_message
        # 오른쪽 식을 계산한 값을 detail에 대입합니다.
        detail = error.detail
    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
    else:
        # user_message에 문자열을 대입합니다.
        user_message = "예상하지 못한 오류가 발생했습니다."
        # detail에 딕셔너리(키와 값의 쌍)을 대입합니다.
        detail = {}
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with suppress(Exception):
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
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


# build_voice_controller(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: runtime, chat, output_stream.
# 반환 타입 힌트: VoiceController.
def build_voice_controller(
    runtime: Runtime,
    chat: ChatOrchestrator,
    output_stream: TextIO | None = None,
) -> VoiceController:
    """Assemble local STT/TTS and create a VoiceController instance."""
    # 오른쪽 식을 계산한 값을 voice_settings에 대입합니다.
    voice_settings = runtime.config.settings.voice
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not voice_settings.enabled.
    if not voice_settings.enabled:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError("설정에서 음성 모드가 비활성화되어 있습니다.")
    # 오른쪽 식을 계산한 값을 model_path에 대입합니다.
    model_path = (
        _data_path(runtime.config, runtime.config.settings.paths.models_dir)
        / voice_settings.stt.wake.model
    )
    # VoskSTTEngine()의 반환값을 wake_stt에 대입합니다.
    wake_stt = VoskSTTEngine(
        model_path,
        sample_rate=voice_settings.stt.sample_rate_hz,
        language=voice_settings.stt.language,
        expected_archive_sha256=voice_settings.stt.wake.model_archive_sha256,
    )
    # 오른쪽 식을 계산한 값을 command_settings에 대입합니다.
    command_settings = voice_settings.stt.command
    # 오른쪽 식을 계산한 값을 command_model_path에 대입합니다.
    command_model_path = (
        _data_path(runtime.config, runtime.config.settings.paths.models_dir)
        / command_settings.model
    )
    # FasterWhisperSTTEngine()의 반환값을 command_stt에 대입합니다.
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
    # 오른쪽 식을 계산한 값을 barge_in_settings에 대입합니다.
    barge_in_settings = voice_settings.barge_in
    # BargeInGatePolicy()의 반환값을 barge_in_policy에 대입합니다.
    barge_in_policy = BargeInGatePolicy(
        speech_threshold_dbfs=barge_in_settings.speech_threshold_dbfs,
        min_onset_rise_db=barge_in_settings.min_onset_rise_db,
        baseline_window_ms=barge_in_settings.baseline_window_ms,
        startup_guard_ms=barge_in_settings.startup_guard_ms,
        recent_speech_ms=barge_in_settings.recent_speech_ms,
        pre_roll_ms=barge_in_settings.pre_roll_ms,
    )
    # barge_in_gate_factory을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    barge_in_gate_factory: Callable[[], BargeInGate] | None = None
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: barge_in_settings.enabled.
    if barge_in_settings.enabled:

        # create_barge_in_gate(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # 반환 타입 힌트: BargeInGate.
        def create_barge_in_gate() -> BargeInGate:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return BargeInGate(
                barge_in_policy,
                WebRtcVoiceActivityDetector(
                    mode=barge_in_settings.vad_mode,
                    frame_ms=barge_in_settings.vad_frame_ms,
                    min_voiced_ratio=barge_in_settings.vad_min_voiced_ratio,
                ),
            )

        # 오른쪽 식을 계산한 값을 barge_in_gate_factory에 대입합니다.
        barge_in_gate_factory = create_barge_in_gate
    # interrupt_hotkey_factory을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    interrupt_hotkey_factory: InterruptHotkeyFactory | None = None
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if barge_in_settings.enabled and barge_in_settings.interrupt_hotkey_enabled:
        # 오른쪽 식을 계산한 값을 hotkey_spec에 대입합니다.
        hotkey_spec = barge_in_settings.interrupt_hotkey

        # create_hotkey_monitor(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # 반환 타입 힌트: InterruptHotkeyMonitor.
        def create_hotkey_monitor() -> InterruptHotkeyMonitor:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return create_interrupt_hotkey(hotkey_spec)

        # 오른쪽 식을 계산한 값을 interrupt_hotkey_factory에 대입합니다.
        interrupt_hotkey_factory = create_hotkey_monitor
    # 오른쪽 식을 계산한 값을 stream에 대입합니다.
    stream = output_stream or sys.stdout
    # LocalVoiceListener()의 반환값을 listener에 대입합니다.
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
        min_avg_logprob=command_settings.min_avg_logprob,
        max_no_speech_probability=command_settings.max_no_speech_probability,
        device_label=voice_settings.stt.device,
        events=runtime.events,
        clock=runtime.clock,
        output_stream=stream,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return VoiceController(
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
        output_stream=stream,
    )


# _run_voice_mode(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: runtime, chat, output_stream.
# 반환 타입 힌트: 정수(int).
def _run_voice_mode(
    runtime: Runtime,
    chat: ChatOrchestrator,
    output_stream: TextIO,
) -> int:
    """Assemble local STT/TTS and run the voice controller."""
    # build_voice_controller()의 반환값을 controller에 대입합니다.
    controller = build_voice_controller(runtime, chat, output_stream)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return controller.run()


# run_application(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, input_stream, output_stream, error_stream, once, voice, llm.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 정수(int).
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
    """Acquire the instance lock, recover leftover files, then serve CLI or voice."""
    # runtime을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    runtime: Runtime | None = None
    # started을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    started = False
    # started_ms에 숫자 등 고정된 값을 대입합니다.
    started_ms = 0
    # int()의 반환값을 exit_code에 대입합니다.
    exit_code = int(ExitCode.UNHANDLED_ERROR)
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # build()의 반환값을 runtime에 대입합니다.
        runtime = build(config_dir, llm=llm)
        # runtime.lock.acquire()을 호출해 작업을 수행합니다.
        runtime.lock.acquire()
        # initialize_database()을 호출해 작업을 수행합니다.
        initialize_database(runtime.memory_db)
        # runtime.clock.monotonic_ms()의 반환값을 started_ms에 대입합니다.
        started_ms = runtime.clock.monotonic_ms()
        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
        runtime.events.emit(
            "app.start",
            {
                "version": __version__,
                "pid": os.getpid(),
                "config_hash": runtime.config.config_hash,
                "dev_mode": runtime.config.settings.dev_mode,
            },
        )
        # started을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        started = True
        # recover_startup()을 호출해 작업을 수행합니다.
        recover_startup(runtime.config.settings.paths.data_root, runtime.events)
        # recover_sessions()을 호출해 작업을 수행합니다.
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
        # recover_tasks()을 호출해 작업을 수행합니다.
        recover_tasks(runtime.task_store, runtime.events)
        # Bring up and verify local models before the first embedding sync.
        verifier = getattr(runtime.llm, "verify_model", None)
        if callable(verifier):
            verifier()

        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with suppress(Exception):
            # runtime.indexer.sync()을 호출해 작업을 수행합니다.
            runtime.indexer.sync()
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
            verify_model=None,  # Verified before indexing above.
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
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: voice.
        if voice:
            # _run_voice_mode()의 반환값을 exit_code에 대입합니다.
            exit_code = _run_voice_mode(runtime, chat, output_stream)
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # run_cli()의 반환값을 exit_code에 대입합니다.
            exit_code = run_cli(
                input_stream=input_stream,
                output_stream=output_stream,
                once=once,
                chat=chat,
                typed_confirm_phrase=runtime.config.policies.tools.approval.typed_confirm_phrase,
            )
    # KeyboardInterrupt를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except KeyboardInterrupt as error:
        # int()의 반환값을 exit_code에 대입합니다.
        exit_code = int(ExitCode.INTERRUPTED)
        # 열린 출력 대상에 데이터를 기록합니다.
        output_stream.write("\n입력을 중단하고 안전하게 종료합니다.\n")
        # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
        output_stream.flush()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: runtime is not None and
        # runtime.lock.acquired.
        if runtime is not None and runtime.lock.acquired:
            # _record_error()을 호출해 작업을 수행합니다.
            _record_error(runtime, error, handled=True)
    # JarvisError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except JarvisError as error:
        # int()의 반환값을 exit_code에 대입합니다.
        exit_code = int(exit_code_for(error))
        # 열린 출력 대상에 데이터를 기록합니다.
        error_stream.write(error.user_message + "\n")
        # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
        error_stream.flush()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: runtime is not None and
        # runtime.lock.acquired.
        if runtime is not None and runtime.lock.acquired:
            # _record_error()을 호출해 작업을 수행합니다.
            _record_error(runtime, error, handled=True)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: runtime.config.settings.dev_mode.
            if runtime.config.settings.dev_mode:
                # traceback.print_exc()을 호출해 작업을 수행합니다.
                traceback.print_exc(file=error_stream)
    # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except Exception as error:
        # int()의 반환값을 exit_code에 대입합니다.
        exit_code = int(ExitCode.UNHANDLED_ERROR)
        # 열린 출력 대상에 데이터를 기록합니다.
        error_stream.write("예상하지 못한 오류가 발생했습니다.\n")
        # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
        error_stream.flush()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: runtime is not None and
        # runtime.lock.acquired.
        if runtime is not None and runtime.lock.acquired:
            # _record_error()을 호출해 작업을 수행합니다.
            _record_error(runtime, error, handled=False)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: runtime.config.settings.dev_mode.
            if runtime.config.settings.dev_mode:
                # traceback.print_exc()을 호출해 작업을 수행합니다.
                traceback.print_exc(file=error_stream)
    # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
    finally:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: runtime is not None.
        if runtime is not None:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: started.
            if started:
                # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                # 처리합니다.
                try:
                    # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                    runtime.events.emit(
                        "app.stop",
                        {
                            "exit_code": exit_code,
                            "uptime_ms": max(0, runtime.clock.monotonic_ms() - started_ms),
                        },
                    )
                # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
                except Exception:
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: exit_code ==
                    # int(ExitCode.SUCCESS).
                    if exit_code == int(ExitCode.SUCCESS):
                        # int()의 반환값을 exit_code에 대입합니다.
                        exit_code = int(ExitCode.UNHANDLED_ERROR)
                        # 열린 출력 대상에 데이터를 기록합니다.
                        error_stream.write("종료 이벤트를 기록하지 못했습니다.\n")
                        # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
                        error_stream.flush()
            # runtime.lock.release()을 호출해 작업을 수행합니다.
            runtime.lock.release()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return exit_code
