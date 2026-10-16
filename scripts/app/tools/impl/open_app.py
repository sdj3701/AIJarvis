# 파이썬 공부 | scripts/app/tools/impl/open_app.py
# 허용된 앱을 독립 프로세스로 실행합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Detached allowlisted application launcher."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import PolicyDenied, ToolExecutionFailed
from app.safety.app_access import AppAccess, locked_identity
from app.tools.base import ToolContext, ToolResult, ToolSpec


# OpenAppTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class OpenAppTool:
    # spec: ToolSpec 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    spec: ToolSpec
    # access을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    access: AppAccess | None = None

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.access is None.
        if self.access is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("앱 실행 승인 저장소가 구성되지 않았습니다.")
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.access.lock:
            # 오른쪽 식을 계산한 값을 normalized에 대입합니다.
            normalized = tctx.normalized_args or {}
            # 오른쪽 식을 계산한 값을 request에 대입합니다.
            request = tctx.ctx.request_id
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: request in self.access._finished.
            if request in self.access._finished:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("이미 처리한 실행 요청입니다. 새로 요청하세요.")
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with locked_identity(Path(normalized.get("exe_path", ""))) as identity:
                # tctx.ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
                tctx.ctx.cancel.raise_if_cancelled()
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if any(normalized.get(key) != value for key, value in identity.items()):
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied("승인 후 앱이 변경되었습니다. 다시 요청하세요.")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not
                # self.access.allowed(identity).
                if not self.access.allowed(identity):
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tctx.ticket is None.
                    if tctx.ticket is None:
                        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                        # 이동합니다.
                        raise PolicyDenied("최초 앱 실행 승인이 필요합니다.")
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다:
                    # self.access.saved_permissions.
                    if self.access.saved_permissions:
                        # self.access.grant()을 호출해 작업을 수행합니다.
                        self.access.grant(identity, normalized["app"], tctx.ctx.channel)
                        # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
                        tctx.ctx.events.emit("app.permission.grant", {
                            "app": normalized["app"], "sha256": identity["sha256"],
                        })
                # add 메서드를 호출해 항목이나 기록을 추가합니다.
                self.access._finished.add(request)
                # normalized.get()의 반환값을 token에 대입합니다.
                token = normalized.get("choice_token")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: token.
                if token:
                    # self.access._choices.pop()을 호출해 작업을 수행합니다.
                    self.access._choices.pop(token, None)
                # tctx.ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
                tctx.ctx.cancel.raise_if_cancelled()
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return self._launch(args, tctx)

    # _launch(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def _launch(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        # time.monotonic()의 반환값을 start에 대입합니다.
        start = time.monotonic()
        # 오른쪽 식을 계산한 값을 normalized에 대입합니다.
        normalized = tctx.normalized_args or {}
        # str()의 반환값을 exe_path에 대입합니다.
        exe_path = str(normalized.get("exe_path", ""))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not exe_path.
        if not exe_path:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # subprocess.Popen()의 반환값을 proc에 대입합니다.
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
        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OSError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolExecutionFailed(
                ("실행 권한은 저장되어 있지만 앱을 시작하지 못했습니다."
                 if self.access is not None and self.access.saved_permissions
                 else "앱을 시작하지 못했습니다. 다시 요청하고 승인하세요."),
                {"exe_path": exe_path, "error": str(error)},
            ) from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
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


# _ms(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: start.
# 반환 타입 힌트: 정수(int).
def _ms(start: float) -> int:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return max(0, int((time.monotonic() - start) * 1000))
