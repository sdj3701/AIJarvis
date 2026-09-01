"""Allowlisted application closer tool."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any

from app.tools.base import ToolContext, ToolResult, ToolSpec


@dataclass
class CloseAppTool:
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        normalized = tctx.normalized_args or {}
        exe_name = str(normalized.get("exe_name", "")).strip()
        app_name = str(normalized.get("app", exe_name))

        if not exe_name:
            return ToolResult(
                ok=False,
                output="종료할 애플리케이션 대상이 지정되지 않았습니다.",
                data=None,
                error="missing_exe_name",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )

        try:
            proc = subprocess.run(
                ["taskkill", "/IM", exe_name, "/T", "/F"],
                capture_output=True,
                text=True,
                shell=False,
                timeout=self.spec.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False,
                output="프로그램 종료 작업 시간이 초과되었습니다.",
                data=None,
                error="timeout",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
        except Exception as error:
            return ToolResult(
                ok=False,
                output=f"프로세스 종료 중 오류가 발생했습니다: {error}",
                data=None,
                error=str(error),
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )

        if proc.returncode == 0:
            return ToolResult(
                ok=True,
                output=f"[{app_name}] 애플리케이션을 성공적으로 종료했습니다.",
                data={"app": app_name, "exe_name": exe_name},
                error=None,
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )

        return ToolResult(
            ok=False,
            output=f"[{app_name}] 프로그램이 실행 중이지 않거나 종료할 수 없습니다.",
            data=None,
            error=proc.stderr.strip() or "process_not_found",
            changed_paths=(),
            duration_ms=_ms(start),
            truncated=False,
            untrusted=False,
        )


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
