"""Composition root for all Phase 0 runtime dependencies."""

from __future__ import annotations

import os
import traceback
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from app import __version__
from app.cli import run_cli
from app.config.loader import DEFAULT_CONFIG_DIR, load_config
from app.config.models import LoadedConfig
from app.config.secrets import SecretLoader
from app.core.clock import Clock, SystemClock
from app.core.errors import ExitCode, JarvisError, exit_code_for
from app.core.ids import PrefixedIdFactory, SystemIdFactory
from app.memory.migrations import initialize_database
from app.orchestrator.recovery import recover_startup
from app.telemetry.events import JsonlEventWriter
from app.telemetry.masking import LogMasker
from app.ui.single_instance import SingleInstanceLock


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


def _data_path(config: LoadedConfig, configured: Path) -> Path:
    if configured.is_absolute():
        return configured.resolve(strict=False)
    return (config.settings.paths.data_root / configured).resolve(strict=False)


def build(
    config_dir: Path = DEFAULT_CONFIG_DIR,
    *,
    clock: Clock | None = None,
    ids: PrefixedIdFactory | None = None,
) -> Runtime:
    """Load configuration and construct every Phase 0 service in one place."""
    loaded = load_config(config_dir)
    runtime_clock = clock or SystemClock()
    runtime_ids = ids or SystemIdFactory()
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
    return Runtime(
        config=loaded,
        clock=runtime_clock,
        ids=runtime_ids,
        masker=masker,
        events=events,
        secrets=secrets,
        lock=SingleInstanceLock(state_dir / "jarvis.lock"),
        memory_db=_data_path(loaded, loaded.settings.paths.memory_db),
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
) -> int:
    """Run startup, CLI, and cleanup with production-safe exception reporting."""
    runtime: Runtime | None = None
    started = False
    started_ms = 0
    exit_code = int(ExitCode.UNHANDLED_ERROR)
    try:
        runtime = build(config_dir)
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
        exit_code = run_cli(
            input_stream=input_stream,
            output_stream=output_stream,
            once=once,
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
