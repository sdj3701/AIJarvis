# 파이썬 공부 | scripts/app/tools/impl/close_app.py
# 승인된 프로세스 신원과 일치하는 앱을 종료합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Close only approved process identities, never image names or process trees."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.core.errors import PolicyDenied
from app.safety.processes import WindowsProcesses
from app.tools.base import ToolContext, ToolResult, ToolSpec


# CloseAppTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class CloseAppTool:
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
        # normalized.get()의 반환값을 targets에 대입합니다.
        targets = normalized.get("targets", [])
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not targets or tctx.ticket is None or "proc_terminate" not in self.spec.capabilities:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("종료 대상과 승인 티켓이 필요합니다.")
        # normalized.get()의 반환값을 force에 대입합니다.
        force = normalized.get("force", False)
        # WindowsProcesses().close()의 반환값을 done에 대입합니다.
        done = WindowsProcesses().close(targets, force=force, timeout_s=self.spec.timeout_s)
        # 오른쪽 식을 계산한 값을 app에 대입합니다.
        app = normalized["app"]
        # 오른쪽 식을 계산한 값을 output에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        output = (
            f"[{app}] 애플리케이션을 종료했습니다."
            if done
            else (
                f"[{app}] 종료를 요청했지만 프로세스가 아직 실행 중입니다. "
                "저장 확인창이나 트레이를 확인하세요. 카카오톡을 강제로 끝내려면 "
                "'카카오톡 강제 종료해줘'를 별도로 요청하세요."
            )
        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ToolResult(
            done,
            output,
            {"app": app, "force": force},
            None if done else "still_running",
            (),
            int((time.monotonic() - start) * 1000),
            False,
            False,
        )
