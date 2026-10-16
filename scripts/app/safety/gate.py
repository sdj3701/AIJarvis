# 파이썬 공부 | scripts/app/safety/gate.py
# 도구 인자를 정규화하고 실행 허용·거부·승인 필요 여부를 결정합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Safety gate: normalize tool arguments and produce execution verdicts."""

from __future__ import annotations

import ipaddress
import re
import socket
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from app.config.models import ForbiddenAction, NetworkPolicy, Settings, ToolDefinition, ToolPolicy
from app.core.canonical import args_hash as compute_args_hash
from app.core.context import RequestContext
from app.core.errors import ApprovalRequired, PolicyDenied, ToolArgInvalid
from app.llm.base import ToolCall
from app.safety.app_access import AppAccess
from app.safety.paths import Sandbox, assert_in_sandbox, build_sandbox, resolve_tool_path
from app.safety.processes import snapshot_app
from app.tools.base import Capability, Risk, ToolSpec

# 오른쪽 식을 계산한 값을 Decision에 대입합니다.
Decision = Literal["allow", "confirm", "typed_confirm", "deny"]

# _DELETE_PATTERNS에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
_DELETE_PATTERNS = (
    re.compile(r"\bdelete\b", re.I),
    re.compile(r"\bremove\b", re.I),
    re.compile(r"삭제"),
    re.compile(r"지워"),
    re.compile(r"포맷"),
    re.compile(r"format\s+disk", re.I),
    re.compile(r"\brm\b", re.I),
    re.compile(r"레지스트리"),
    re.compile(r"registry", re.I),
    re.compile(r"powershell", re.I),
    re.compile(r"cmd\.exe", re.I),
)


# Verdict: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class Verdict:
    # decision: Decision 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    decision: Decision
    # risk: Risk 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    risk: Risk
    # reason: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    reason: str
    # tool_name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    tool_name: str
    # normalized_args: dict[str, Any] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    normalized_args: dict[str, Any]
    # args_hash: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    args_hash: str
    # display: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    display: str
    # capabilities: frozenset[Capability] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    capabilities: frozenset[Capability]


# SafetyGate: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class SafetyGate:
    # policy: ToolPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    policy: ToolPolicy
    # sandbox: Sandbox 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sandbox: Sandbox
    # network: NetworkPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    network: NetworkPolicy
    # definitions: dict[str, ToolDefinition] 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    definitions: dict[str, ToolDefinition]
    # app_access을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    app_access: AppAccess | None = None

    # dataclass가 생성한 초기화 처리 뒤에 실행됩니다. 필드 값의 추가 검사·보정을 맡습니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __post_init__(self) -> None:
        # self.definitions.get()의 반환값을 definition에 대입합니다.
        definition = self.definitions.get("open_app")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.app_access is None.
        if self.app_access is None:
            # AppAccess()의 반환값을 self.app_access에 대입합니다.
            self.app_access = AppAccess(
                self.sandbox.data_root,
                dynamic=bool(definition and definition.dynamic_discovery_enabled),
                ttl=definition.catalog_ttl_s if definition else 300,
                limit=definition.catalog_max_entries if definition else 2000,
                saved_permissions=definition.saved_permissions_enabled if definition else True,
            )

    # from_config(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # cls는 이 메서드를 호출한 클래스입니다.
    # 입력: settings, policy.
    # 반환 타입 힌트: SafetyGate.
    # @classmethod: 객체 대신 클래스를 첫 인자로 받습니다.
    @classmethod
    def from_config(cls, settings: Settings, policy: ToolPolicy) -> SafetyGate:
        # build_sandbox()의 반환값을 sandbox에 대입합니다.
        sandbox = build_sandbox(settings, policy.sandbox)
        # 오른쪽 식을 계산한 값을 definitions에 대입합니다.
        # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
        definitions = {item.name: item for item in policy.tools}
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return cls(
            policy=policy,
            sandbox=sandbox,
            network=policy.network,
            definitions=definitions,
        )

    # evaluate(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: call, ctx, spec.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Verdict.
    def evaluate(self, call: ToolCall, *, ctx: RequestContext, spec: ToolSpec) -> Verdict:
        # self._check_forbidden_tool()을 호출해 작업을 수행합니다.
        self._check_forbidden_tool(call)
        # self.definitions.get()의 반환값을 defn에 대입합니다.
        defn = self.definitions.get(call.name)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.name == 'close_app'.
            if call.name == "close_app":
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'proc_terminate' not in
                # spec.capabilities.
                if "proc_terminate" not in spec.capabilities:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied("종료 도구에 proc_terminate 권한이 필요합니다.")
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.arguments.get('force')
                # and call.id !=
                # 'explicit_close_force'.
                if call.arguments.get("force") and call.id != "explicit_close_force":
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied("강제 종료는 명시적 사용자 명령으로만 요청할 수 있습니다.")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.name == 'open_app' and
            # self.app_access is not
            # None.
            if call.name == "open_app" and self.app_access is not None:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: set(call.arguments) !=
                # {'app'}.
                if set(call.arguments) != {"app"}:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied("앱 실행에는 이름만 지정할 수 있습니다.")
                # self.app_access.resolve()의 반환값을 normalized에 대입합니다.
                normalized = self.app_access.resolve(
                    str(call.arguments["app"]), (defn.app_map or {}) if defn else {},
                    ctx.session_id, explicit=call.id == "cli_open_app",
                )
            # 앞선 조건이 거짓이면 이 블록을 실행합니다.
            else:
                # self._normalize()의 반환값을 normalized에 대입합니다.
                normalized = self._normalize(call.name, call.arguments, defn)
        # (ToolArgInvalid, PolicyDenied)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
        # 담깁니다.
        except (ToolArgInvalid, PolicyDenied) as error:
            # getattr()의 반환값을 message에 대입합니다.
            message = getattr(error, "user_message", str(error))
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return Verdict(
                decision="deny",
                risk=spec.risk,
                reason=message,
                tool_name=call.name,
                normalized_args={},
                args_hash="",
                display=f"거부: {message}",
                capabilities=spec.capabilities,
            )

        # self._effective_risk()의 반환값을 risk에 대입합니다.
        risk = self._effective_risk(call.name, normalized, spec, defn)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if (call.name == "open_app" and self.app_access is not None
                and not self.app_access.allowed(normalized)):
            # _max_risk()의 반환값을 risk에 대입합니다.
            risk = _max_risk(risk, "medium")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.name == 'close_app'.
        if call.name == "close_app":
            # 오른쪽 식을 계산한 값을 risk에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            risk = "high" if normalized["force"] else _max_risk(risk, "medium")
        # self._decision_for_risk()의 반환값을 decision에 대입합니다.
        decision = self._decision_for_risk(risk)
        # self._build_display()의 반환값을 display에 대입합니다.
        display = self._build_display(call.name, normalized)
        # self._reason_for_decision()의 반환값을 reason에 대입합니다.
        reason = self._reason_for_decision(call.name, risk, decision, normalized)
        # 오른쪽 식을 계산한 값을 bound_hash에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        bound_hash = compute_args_hash(call.name, normalized) if normalized else ""

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ctx.channel == 'voice' and risk ==
        # 'high'.
        if ctx.channel == "voice" and risk == "high":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return Verdict(
                decision="deny",
                risk=risk,
                reason="음성 채널에서는 high 위험 작업을 실행할 수 없습니다.",
                tool_name=call.name,
                normalized_args=normalized,
                args_hash=bound_hash,
                display=f"거부: {display}",
                capabilities=spec.capabilities,
            )

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not ctx.interactive and decision in
        # {'confirm',
        # 'typed_confirm'}.
        if not ctx.interactive and decision in {"confirm", "typed_confirm"}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ApprovalRequired(
                reason,
                {"tool_name": call.name, "args_hash": bound_hash},
                verdict=Verdict(
                    decision=decision,
                    risk=risk,
                    reason=reason,
                    tool_name=call.name,
                    normalized_args=normalized,
                    args_hash=bound_hash,
                    display=display,
                    capabilities=spec.capabilities,
                ),
            )

        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Verdict(
            decision=decision,
            risk=risk,
            reason=reason,
            tool_name=call.name,
            normalized_args=normalized,
            args_hash=bound_hash,
            display=display,
            capabilities=spec.capabilities,
        )

    # check_forbidden_user_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: ForbiddenAction | None.
    def check_forbidden_user_text(self, text: str) -> ForbiddenAction | None:
        # text.strip().lower()의 반환값을 lowered에 대입합니다.
        lowered = text.strip().lower()
        # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
        for item in self.policy.forbidden:
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if item.id == "delete_any" and any(
                pattern.search(text) or pattern.search(lowered) for pattern in _DELETE_PATTERNS[:4]
            ):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return item
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if item.id == "format_disk" and (
                "포맷" in text or "format disk" in lowered
            ):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return item
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if item.id == "arbitrary_shell" and any(
                pattern.search(text) for pattern in _DELETE_PATTERNS[6:9]
            ):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return item
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if item.id == "registry_write" and any(
                pattern.search(text) for pattern in _DELETE_PATTERNS[8:10]
            ):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return item
        # None을 반환하고 이 함수의 실행을 끝냅니다.
        return None

    # _check_forbidden_tool(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: call.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _check_forbidden_tool(self, call: ToolCall) -> None:
        # forbidden_names에 집합(중복 없는 항목)을 대입합니다.
        forbidden_names = {
            "delete_file",
            "delete_any",
            "format_disk",
            "run_shell",
            "arbitrary_shell",
            "registry_write",
            "run_skill",
        }
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: call.name in forbidden_names.
        if call.name in forbidden_names:
            # next()의 반환값을 reason에 대입합니다.
            reason = next(
                (item.reason for item in self.policy.forbidden if item.id == call.name),
                "금지된 작업입니다.",
            )
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(reason)

    # _normalize(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: tool_name, arguments, defn.
    # 반환 타입 힌트: dict[str, Any].
    def _normalize(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_app'.
        if tool_name == "open_app":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._normalize_open_app(arguments, defn)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'close_app'.
        if tool_name == "close_app":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._normalize_close_app(arguments, defn)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_folder'.
        if tool_name == "open_folder":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._normalize_open_folder(arguments, defn)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_url'.
        if tool_name == "open_url":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._normalize_open_url(arguments)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'create_file'.
        if tool_name == "create_file":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return self._normalize_create_file(arguments, defn)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name in {'web_search',
        # 'doc_search', 'fetch_url'}.
        if tool_name in {"web_search", "doc_search", "fetch_url"}:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return dict(arguments)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return dict(arguments)

    # _normalize_open_app(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: arguments, defn.
    # 반환 타입 힌트: dict[str, Any].
    def _normalize_open_app(
        self,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        # str()의 반환값을 app에 대입합니다.
        app = str(arguments["app"])
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: defn is None or not defn.app_map or
        # app not in
        # defn.app_map.
        if defn is None or not defn.app_map or app not in defn.app_map:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(f"등록되지 않은 앱입니다: {app}")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: defn.allow_args is False and
        # len(arguments) > 1.
        if defn.allow_args is False and len(arguments) > 1:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("이 앱에는 추가 인자를 전달할 수 없습니다.")
        # 오른쪽 식을 계산한 값을 exe에 대입합니다.
        exe = defn.app_map[app]
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {"app": app, "exe_path": str(exe.resolve(strict=False))}

    # _normalize_close_app(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: arguments, defn.
    # 반환 타입 힌트: dict[str, Any].
    def _normalize_close_app(
        self,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        # str()의 반환값을 app에 대입합니다.
        app = str(arguments["app"])
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: defn is None or not defn.app_map or
        # app not in
        # defn.app_map.
        if defn is None or not defn.app_map or app not in defn.app_map:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(f"등록되지 않은 앱입니다: {app}")
        # 오른쪽 식을 계산한 값을 exe에 대입합니다.
        exe = defn.app_map[app]
        # 오른쪽 식을 계산한 값을 exe_name에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        exe_name = exe.name if hasattr(exe, "name") else str(exe).split("\\")[-1]
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: exe_name.lower() == 'explorer.exe'.
        if exe_name.lower() == "explorer.exe":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("Windows 탐색기 프로세스는 종료할 수 없습니다.")
        # snapshot_app()의 반환값을 targets에 대입합니다.
        targets = snapshot_app(exe)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not targets.
        if not targets:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("등록된 경로의 앱이 실행 중이지 않습니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "app": app,
            "exe_path": str(exe.resolve(strict=False)),
            "exe_name": exe_name,
            "targets": targets,
            "force": bool(arguments.get("force", False)),
        }

    # _normalize_open_folder(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: arguments, defn.
    # 반환 타입 힌트: dict[str, Any].
    def _normalize_open_folder(
        self,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        # str()의 반환값을 root에 대입합니다.
        root = str(arguments["root"])
        # str()의 반환값을 relative에 대입합니다.
        relative = str(arguments["relative_path"])
        # 오른쪽 식을 계산한 값을 allowed에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        allowed = defn.allowed_roots if defn and defn.allowed_roots else []
        # resolve_tool_path()의 반환값을 path에 대입합니다.
        path = resolve_tool_path(
            self.sandbox,
            root_name=root,
            relative=relative,
            allowed_roots=allowed,
            must_exist=True,
            must_be_dir=True,
        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {"root": root, "relative_path": relative, "path": str(path)}

    # _normalize_open_url(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: arguments.
    # 반환 타입 힌트: dict[str, Any].
    def _normalize_open_url(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # str(arguments['url']).strip()의 반환값을 url에 대입합니다.
        url = str(arguments["url"]).strip()
        # self._validate_http_url()으로 입력 형식과 허용 조건을 검사합니다.
        self._validate_http_url(url)
        # urlparse()의 반환값을 parsed에 대입합니다.
        parsed = urlparse(url)
        # (parsed.hostname or '').lower()의 반환값을 host에 대입합니다.
        host = (parsed.hostname or "").lower()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "url": url,
            "host": host,
            "has_query": bool(parsed.query),
            "listed_domain": self._domain_listed(host),
        }

    # _normalize_create_file(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: arguments, defn.
    # 반환 타입 힌트: dict[str, Any].
    def _normalize_create_file(
        self,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        # str()의 반환값을 root에 대입합니다.
        root = str(arguments["root"])
        # str()의 반환값을 relative에 대입합니다.
        relative = str(arguments["relative_path"])
        # str()의 반환값을 content에 대입합니다.
        content = str(arguments["content"])
        # bool()의 반환값을 overwrite에 대입합니다.
        overwrite = bool(arguments.get("overwrite", False))
        # 오른쪽 식을 계산한 값을 allowed에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        allowed = defn.allowed_roots if defn and defn.allowed_roots else []
        # 오른쪽 식을 계산한 값을 max_bytes에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        max_bytes = defn.max_content_bytes if defn and defn.max_content_bytes else 200_000
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(content.encode('utf-8')) >
        # max_bytes.
        if len(content.encode("utf-8")) > max_bytes:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid(f"내용 크기가 {max_bytes}바이트를 초과합니다.")
        # resolve_tool_path()의 반환값을 path에 대입합니다.
        path = resolve_tool_path(
            self.sandbox,
            root_name=root,
            relative=relative,
            allowed_roots=allowed,
            for_write=True,
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: path.exists() and (not overwrite).
        if path.exists() and not overwrite:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(
                "파일이 이미 존재합니다. overwrite=true와 승인이 필요합니다."
            )
        # 오른쪽 식을 계산한 값을 parent에 대입합니다.
        parent = path.parent
        # assert_in_sandbox()을 호출해 작업을 수행합니다.
        assert_in_sandbox(parent, self.sandbox.write_roots, sandbox=self.sandbox)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return {
            "root": root,
            "relative_path": relative,
            "path": str(path),
            "content": content,
            "overwrite": overwrite,
            "exists": path.exists(),
        }

    # _effective_risk(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: tool_name, normalized, spec, defn.
    # 반환 타입 힌트: Risk.
    def _effective_risk(
        self,
        tool_name: str,
        normalized: dict[str, Any],
        spec: ToolSpec,
        defn: ToolDefinition | None,
    ) -> Risk:
        # 오른쪽 식을 계산한 값을 risk에 대입합니다.
        risk: Risk = spec.risk
        # 오른쪽 식을 계산한 값을 escalation에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        escalation = defn.risk_escalation if defn else None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: escalation.
        if escalation:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_url'.
            if tool_name == "open_url":
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if not normalized.get("listed_domain") and "unlisted_domain" in escalation:
                    # _max_risk()의 반환값을 risk에 대입합니다.
                    risk = _max_risk(risk, escalation["unlisted_domain"])
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: normalized.get('has_query')
                # and 'has_query_string'
                # in escalation.
                if normalized.get("has_query") and "has_query_string" in escalation:
                    # _max_risk()의 반환값을 risk에 대입합니다.
                    risk = _max_risk(risk, escalation["has_query_string"])
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'create_file'.
            if tool_name == "create_file":
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: normalized.get('overwrite')
                # and 'overwrite' in
                # escalation.
                if normalized.get("overwrite") and "overwrite" in escalation:
                    # _max_risk()의 반환값을 risk에 대입합니다.
                    risk = _max_risk(risk, escalation["overwrite"])
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not normalized.get('exists')
                # and risk == 'medium'.
                elif not normalized.get("exists") and risk == "medium":
                    # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
                    pass
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return risk

    # _decision_for_risk(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: risk.
    # 반환 타입 힌트: Decision.
    def _decision_for_risk(self, risk: Risk) -> Decision:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: risk == 'low'.
        if risk == "low":
            # 'allow'을 반환하고 이 함수의 실행을 끝냅니다.
            return "allow"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: risk == 'medium'.
        if risk == "medium":
            # 'confirm'을 반환하고 이 함수의 실행을 끝냅니다.
            return "confirm"
        # 'typed_confirm'을 반환하고 이 함수의 실행을 끝냅니다.
        return "typed_confirm"

    # _reason_for_decision(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: tool_name, risk, decision, normalized.
    # 반환 타입 힌트: 문자열(str).
    def _reason_for_decision(
        self,
        tool_name: str,
        risk: Risk,
        decision: Decision,
        normalized: dict[str, Any],
    ) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: decision == 'allow'.
        if decision == "allow":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"{tool_name} 실행을 허용합니다."
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_app'.
        if tool_name == "open_app":
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if self.app_access is not None and not self.app_access.saved_permissions:
                # '영구 실행 허용이 꺼져 있어 이번 실행에 대한 승인이 필요합니다.'을 반환하고 이
                # 함수의 실행을 끝냅니다.
                return "영구 실행 허용이 꺼져 있어 이번 실행에 대한 승인이 필요합니다."
            # 문자열 결과를 반환하고 함수를 끝냅니다.
            return "처음 실행하거나 변경된 앱입니다. 허용하면 저장하고 다음부터 다시 묻지 않습니다."
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'close_app'.
        if tool_name == "close_app":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            return ("강제 종료는 저장하지 않은 내용을 잃을 수 있습니다. 확인 문구를 입력하세요."
                    if normalized["force"] else "앱 정상 종료 요청입니다. y/n 확인이 필요합니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'create_file' and
        # normalized.get('overwrite').
        if tool_name == "create_file" and normalized.get("overwrite"):
            # '기존 파일을 덮어씁니다. 확인 문구 입력이 필요합니다.'을 반환하고 이 함수의 실행을
            # 끝냅니다.
            return "기존 파일을 덮어씁니다. 확인 문구 입력이 필요합니다."
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_url' and (not
        # normalized.get('listed_domain')).
        if tool_name == "open_url" and not normalized.get("listed_domain"):
            # '등록되지 않은 도메인입니다. 승인이 필요합니다.'을 반환하고 이 함수의 실행을
            # 끝냅니다.
            return "등록되지 않은 도메인입니다. 승인이 필요합니다."
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: risk == 'medium'.
        if risk == "medium":
            # '중간 위험 작업입니다. y/n 확인이 필요합니다.'을 반환하고 이 함수의 실행을 끝냅니다.
            return "중간 위험 작업입니다. y/n 확인이 필요합니다."
        # '높은 위험 작업입니다. 확인 문구 입력이 필요합니다.'을 반환하고 이 함수의 실행을
        # 끝냅니다.
        return "높은 위험 작업입니다. 확인 문구 입력이 필요합니다."

    # _build_display(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: tool_name, normalized.
    # 반환 타입 힌트: 문자열(str).
    def _build_display(self, tool_name: str, normalized: dict[str, Any]) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_app'.
        if tool_name == "open_app":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"앱 실행: {normalized['app']} ({normalized['exe_path']})"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'close_app'.
        if tool_name == "close_app":
            # 오른쪽 식을 계산한 값을 mode에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            mode = "강제 종료" if normalized["force"] else "정상 종료"
            # ', '.join()의 반환값을 pids에 대입합니다.
            pids = ", ".join(str(t["pid"]) for t in normalized["targets"])
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"앱 {mode}: {normalized['app']} ({normalized['exe_path']}) PID: {pids}"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_folder'.
        if tool_name == "open_folder":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"폴더 열기: {normalized['path']}"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'open_url'.
        if tool_name == "open_url":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"URL 열기: {normalized['url']}"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'create_file'.
        if tool_name == "create_file":
            # 오른쪽 식을 계산한 값을 action에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            action = "덮어쓰기" if normalized.get("overwrite") else "새 파일 생성"
            # len()의 반환값을 size에 대입합니다.
            size = len(str(normalized.get("content", "")).encode("utf-8"))
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"{action}: {normalized['path']} ({size:,} bytes)"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'web_search'.
        if tool_name == "web_search":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"웹 검색: {normalized.get('query', '')}"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'doc_search'.
        if tool_name == "doc_search":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"문서 검색: {normalized.get('query', '')}"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool_name == 'fetch_url'.
        if tool_name == "fetch_url":
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"URL 가져오기: {normalized.get('url', '')}"
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        return f"{tool_name}: {normalized}"

    # _validate_http_url(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: url.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _validate_http_url(self, url: str) -> None:
        # urlparse()의 반환값을 parsed에 대입합니다.
        parsed = urlparse(url)
        # parsed.scheme.lower()의 반환값을 scheme에 대입합니다.
        scheme = parsed.scheme.lower()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: scheme not in
        # self.network.allowed_schemes.
        if scheme not in self.network.allowed_schemes:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(f"허용되지 않은 URL 스킴입니다: {scheme or '(없음)'}")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.network.deny_credentials_in_url and (parsed.username or parsed.password):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("URL에 자격증명을 포함할 수 없습니다.")
        # 오른쪽 식을 계산한 값을 host에 대입합니다.
        host = parsed.hostname
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: host is None.
        if host is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("URL 호스트가 없습니다.")
        # host.lower()의 반환값을 lowered에 대입합니다.
        lowered = host.lower()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lowered.endswith('.local').
        if lowered.endswith(".local"):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("로컬 호스트 이름은 차단됩니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.network.deny_mixed_script_idn and
        # _has_mixed_script(lowered).
        if self.network.deny_mixed_script_idn and _has_mixed_script(lowered):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("혼합 스크립트 IDN 호스트는 차단됩니다.")
        # self._validate_host_ip()으로 입력 형식과 허용 조건을 검사합니다.
        self._validate_host_ip(lowered)

    # _validate_host_ip(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: host.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _validate_host_ip(self, host: str) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: host == 'localhost'.
        if host == "localhost":
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.network.deny_loopback.
            if self.network.deny_loopback:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("loopback 호스트는 차단됩니다.")
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # socket.getaddrinfo()의 반환값을 infos에 대입합니다.
            infos = socket.getaddrinfo(host, None)
        # socket.gaierror를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except socket.gaierror as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("호스트 이름을 확인할 수 없습니다.") from error
        # for 반복문: 대상의 항목을 하나씩 info에 대입하며 아래 블록을 실행합니다.
        for info in infos:
            # ipaddress.ip_address()의 반환값을 ip에 대입합니다.
            ip = ipaddress.ip_address(info[4][0])
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.network.deny_loopback and
            # ip.is_loopback.
            if self.network.deny_loopback and ip.is_loopback:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("loopback IP는 차단됩니다.")
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if self.network.deny_private_ranges and (
                ip.is_private or ip.is_link_local or ip.is_reserved
            ):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("사설·링크로컬 IP는 차단됩니다.")

    # _domain_listed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: host.
    # 반환 타입 힌트: 참/거짓(bool).
    def _domain_listed(self, host: str) -> bool:
        # for 반복문: 대상의 항목을 하나씩 allowed에 대입하며 아래 블록을 실행합니다.
        for allowed in self.network.url_allowlist:
            # allowed.lower()의 반환값을 allowed_lower에 대입합니다.
            allowed_lower = allowed.lower()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: host == allowed_lower or
            # host.endswith('.' +
            # allowed_lower).
            if host == allowed_lower or host.endswith("." + allowed_lower):
                # True을 반환하고 이 함수의 실행을 끝냅니다.
                return True
        # False을 반환하고 이 함수의 실행을 끝냅니다.
        return False


# _max_risk(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: current, candidate.
# 반환 타입 힌트: Risk.
def _max_risk(current: Risk, candidate: Risk) -> Risk:
    # order에 딕셔너리(키와 값의 쌍)을 대입합니다.
    order = {"low": 0, "medium": 1, "high": 2}
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    return candidate if order[candidate] > order[current] else current


# _has_mixed_script(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: host.
# 반환 타입 힌트: 참/거짓(bool).
def _has_mixed_script(host: str) -> bool:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # host.encode('ascii').decode()의 반환값을 decoded에 대입합니다.
        decoded = host.encode("ascii").decode("idna")
    # UnicodeError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except UnicodeError:
        # 오른쪽 식을 계산한 값을 decoded에 대입합니다.
        decoded = host
    # set()의 반환값을 scripts에 대입합니다.
    scripts: set[str] = set()
    # for 반복문: 대상의 항목을 하나씩 char에 대입하며 아래 블록을 실행합니다.
    for char in decoded:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not char.isalpha().
        if not char.isalpha():
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # unicodedata.name()의 반환값을 name에 대입합니다.
        name = unicodedata.name(char, "")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'LATIN' in name.
        if "LATIN" in name:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            scripts.add("LATIN")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'CYRILLIC' in name.
        elif "CYRILLIC" in name:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            scripts.add("CYRILLIC")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'GREEK' in name.
        elif "GREEK" in name:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            scripts.add("GREEK")
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            scripts.add(name.split()[0] if name else "OTHER")
    # 오른쪽 식을 계산한 값을 latin에 대입합니다.
    latin = "LATIN" in scripts
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return len(scripts) > 1 and latin
