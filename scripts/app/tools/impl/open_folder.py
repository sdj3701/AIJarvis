# 파이썬 공부 | scripts/app/tools/impl/open_folder.py
# 허용된 경로에 존재하는 폴더를 엽니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Open an existing folder under an allowed sandbox root."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from app.core.errors import ToolExecutionFailed
from app.tools.base import ToolContext, ToolResult, ToolSpec


# OpenFolderTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class OpenFolderTool:
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
        # str()의 반환값을 folder에 대입합니다.
        folder = str(normalized.get("path", ""))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not folder.
        if not folder:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: os.name == 'nt'.
            if os.name == "nt":
                # os.startfile()을 호출해 작업을 수행합니다.
                os.startfile(folder)
                # pid을 아직 값이 없음을 뜻하는 None으로 설정합니다.
                pid = None
            # 앞선 조건이 거짓이면 이 블록을 실행합니다.
            else:
                # subprocess.Popen()의 반환값을 proc에 대입합니다.
                proc = subprocess.Popen(
                    ["xdg-open", folder],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                # 오른쪽 식을 계산한 값을 pid에 대입합니다.
                pid = proc.pid
        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OSError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolExecutionFailed(
                "폴더를 열지 못했습니다.",
                {"path": folder, "error": str(error)},
            ) from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# _ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: start.
# 반환 타입 힌트: 정수(int).
def _ms(start: float) -> int:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return max(0, int((time.monotonic() - start) * 1000))
