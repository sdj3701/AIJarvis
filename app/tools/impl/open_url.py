"""Open http/https URLs in the default browser."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.browser import open_url_with_browser


@dataclass
class OpenUrlTool:
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        normalized = tctx.normalized_args or {}
        url = str(normalized.get("url", args.get("url", "")))
        open_url_with_browser(url)
        return ToolResult(
            ok=True,
            output=f"브라우저에서 URL을 열었습니다: {url}",
            data={"url": url},
            error=None,
            changed_paths=(),
            duration_ms=_ms(start),
            truncated=False,
            untrusted=False,
        )


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
