# 파이썬 공부 | scripts/app/tools/impl/open_url.py
# HTTP 또는 HTTPS 주소를 기본 브라우저로 엽니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Open http/https URLs in the default browser."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.browser import open_url_with_browser


# OpenUrlTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class OpenUrlTool:
    # spec: ToolSpec 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    spec: ToolSpec

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        # time.monotonic()의 반환값을 start에 대입합니다.
        start = time.monotonic()
        # 오른쪽 식을 계산한 값을 normalized에 대입합니다.
        normalized = tctx.normalized_args or {}
        # str()의 반환값을 url에 대입합니다.
        url = str(normalized.get("url", args.get("url", "")))
        # open_url_with_browser()을 호출해 작업을 수행합니다.
        open_url_with_browser(url)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# _ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: start.
# 반환 타입 힌트: 정수(int).
def _ms(start: float) -> int:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return max(0, int((time.monotonic() - start) * 1000))
