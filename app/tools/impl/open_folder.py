"""Open an existing folder under an allowed sandbox root."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from app.core.errors import ToolExecutionFailed
from app.tools.base import ToolContext, ToolResult, ToolSpec


@dataclass
class OpenFolderTool:
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        normalized = tctx.normalized_args or {}
        folder = str(normalized.get("path", ""))
        if not folder:
            return ToolResult(
                ok=False,
                output="폴더 경로가 없습니다.",
                data=None,
                error="missing_path",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
        try:
            if os.name == "nt":
                os.startfile(folder)
                pid = None
            else:
                proc = subprocess.Popen(
                    ["xdg-open", folder],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                pid = proc.pid
        except OSError as error:
            raise ToolExecutionFailed(
                "폴더를 열지 못했습니다.",
                {"path": folder, "error": str(error)},
            ) from error
        return ToolResult(
            ok=True,
            output=f"폴더를 열었습니다: {folder}",
            data={"path": folder, "pid": pid},
            error=None,
            changed_paths=(),
            duration_ms=_ms(start),
            truncated=False,
            untrusted=False,
        )


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
