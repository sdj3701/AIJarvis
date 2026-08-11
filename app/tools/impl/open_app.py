"""Detached allowlisted application launcher."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any

from app.core.errors import ToolExecutionFailed
from app.tools.base import ToolContext, ToolResult, ToolSpec


@dataclass
class OpenAppTool:
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        normalized = tctx.normalized_args or {}
        exe_path = str(normalized.get("exe_path", ""))
        if not exe_path:
            return ToolResult(
                ok=False,
                output="실행 파일 경로가 없습니다.",
                data=None,
                error="missing_exe_path",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
        try:
            proc = subprocess.Popen(
                [exe_path],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            raise ToolExecutionFailed(
                "앱을 시작하지 못했습니다.",
                {"exe_path": exe_path, "error": str(error)},
            ) from error
        return ToolResult(
            ok=True,
            output=f"앱을 시작했습니다 (PID {proc.pid}).",
            data={"pid": proc.pid, "app": normalized.get("app"), "exe_path": exe_path},
            error=None,
            changed_paths=(),
            duration_ms=_ms(start),
            truncated=False,
            untrusted=False,
        )


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
