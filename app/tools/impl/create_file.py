"""Create text files under allowed sandbox roots."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.atomic import write_atomic
from app.core.errors import ToolExecutionFailed
from app.tools.base import ToolContext, ToolResult, ToolSpec


@dataclass
class CreateFileTool:
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        normalized = tctx.normalized_args or {}
        target = Path(str(normalized.get("path", "")))
        content = str(normalized.get("content", ""))
        overwrite = bool(normalized.get("overwrite", False))
        if not target:
            return ToolResult(
                ok=False,
                output="대상 경로가 없습니다.",
                data=None,
                error="missing_path",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
        if target.exists() and not overwrite:
            return ToolResult(
                ok=False,
                output="파일이 이미 존재합니다.",
                data=None,
                error="exists",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(target, content.encode("utf-8"))
        except OSError as error:
            raise ToolExecutionFailed(
                "파일을 생성하지 못했습니다.",
                {"path": str(target), "error": str(error)},
            ) from error
        return ToolResult(
            ok=True,
            output=f"파일을 생성했습니다: {target}",
            data={"path": str(target), "overwrite": overwrite},
            error=None,
            changed_paths=(str(target),),
            duration_ms=_ms(start),
            truncated=False,
            untrusted=False,
        )


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
