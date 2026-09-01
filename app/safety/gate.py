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
from app.safety.paths import Sandbox, assert_in_sandbox, build_sandbox, resolve_tool_path
from app.tools.base import Capability, Risk, ToolSpec

Decision = Literal["allow", "confirm", "typed_confirm", "deny"]

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


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    risk: Risk
    reason: str
    tool_name: str
    normalized_args: dict[str, Any]
    args_hash: str
    display: str
    capabilities: frozenset[Capability]


@dataclass
class SafetyGate:
    policy: ToolPolicy
    sandbox: Sandbox
    network: NetworkPolicy
    definitions: dict[str, ToolDefinition]

    @classmethod
    def from_config(cls, settings: Settings, policy: ToolPolicy) -> SafetyGate:
        sandbox = build_sandbox(settings, policy.sandbox)
        definitions = {item.name: item for item in policy.tools}
        return cls(
            policy=policy,
            sandbox=sandbox,
            network=policy.network,
            definitions=definitions,
        )

    def evaluate(self, call: ToolCall, *, ctx: RequestContext, spec: ToolSpec) -> Verdict:
        self._check_forbidden_tool(call)
        defn = self.definitions.get(call.name)
        try:
            normalized = self._normalize(call.name, call.arguments, defn)
        except (ToolArgInvalid, PolicyDenied) as error:
            message = getattr(error, "user_message", str(error))
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

        risk = self._effective_risk(call.name, normalized, spec, defn)
        decision = self._decision_for_risk(risk)
        display = self._build_display(call.name, normalized)
        reason = self._reason_for_decision(call.name, risk, decision, normalized)
        bound_hash = compute_args_hash(call.name, normalized) if normalized else ""

        if ctx.channel == "voice" and risk == "high":
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

        if not ctx.interactive and decision in {"confirm", "typed_confirm"}:
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

    def check_forbidden_user_text(self, text: str) -> ForbiddenAction | None:
        lowered = text.strip().lower()
        for item in self.policy.forbidden:
            if item.id == "delete_any" and any(
                pattern.search(text) or pattern.search(lowered) for pattern in _DELETE_PATTERNS[:4]
            ):
                return item
            if item.id == "format_disk" and (
                "포맷" in text or "format disk" in lowered
            ):
                return item
            if item.id == "arbitrary_shell" and any(
                pattern.search(text) for pattern in _DELETE_PATTERNS[6:9]
            ):
                return item
            if item.id == "registry_write" and any(
                pattern.search(text) for pattern in _DELETE_PATTERNS[8:10]
            ):
                return item
        return None

    def _check_forbidden_tool(self, call: ToolCall) -> None:
        forbidden_names = {
            "delete_file",
            "delete_any",
            "format_disk",
            "run_shell",
            "arbitrary_shell",
            "registry_write",
            "run_skill",
        }
        if call.name in forbidden_names:
            reason = next(
                (item.reason for item in self.policy.forbidden if item.id == call.name),
                "금지된 작업입니다.",
            )
            raise PolicyDenied(reason)

    def _normalize(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        if tool_name == "open_app":
            return self._normalize_open_app(arguments, defn)
        if tool_name == "close_app":
            return self._normalize_close_app(arguments, defn)
        if tool_name == "open_folder":
            return self._normalize_open_folder(arguments, defn)
        if tool_name == "open_url":
            return self._normalize_open_url(arguments)
        if tool_name == "create_file":
            return self._normalize_create_file(arguments, defn)
        if tool_name in {"web_search", "doc_search", "fetch_url"}:
            return dict(arguments)
        return dict(arguments)

    def _normalize_open_app(
        self,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        app = str(arguments["app"])
        if defn is None or not defn.app_map or app not in defn.app_map:
            raise PolicyDenied(f"등록되지 않은 앱입니다: {app}")
        if defn.allow_args is False and len(arguments) > 1:
            raise PolicyDenied("이 앱에는 추가 인자를 전달할 수 없습니다.")
        exe = defn.app_map[app]
        return {"app": app, "exe_path": str(exe.resolve(strict=False))}

    def _normalize_close_app(
        self,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        app = str(arguments["app"])
        if defn is None or not defn.app_map or app not in defn.app_map:
            raise PolicyDenied(f"등록되지 않은 앱입니다: {app}")
        exe = defn.app_map[app]
        exe_name = exe.name if hasattr(exe, "name") else str(exe).split("\\")[-1]
        return {
            "app": app,
            "exe_path": str(exe.resolve(strict=False)),
            "exe_name": exe_name,
        }

    def _normalize_open_folder(
        self,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        root = str(arguments["root"])
        relative = str(arguments["relative_path"])
        allowed = defn.allowed_roots if defn and defn.allowed_roots else []
        path = resolve_tool_path(
            self.sandbox,
            root_name=root,
            relative=relative,
            allowed_roots=allowed,
            must_exist=True,
            must_be_dir=True,
        )
        return {"root": root, "relative_path": relative, "path": str(path)}

    def _normalize_open_url(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = str(arguments["url"]).strip()
        self._validate_http_url(url)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return {
            "url": url,
            "host": host,
            "has_query": bool(parsed.query),
            "listed_domain": self._domain_listed(host),
        }

    def _normalize_create_file(
        self,
        arguments: dict[str, Any],
        defn: ToolDefinition | None,
    ) -> dict[str, Any]:
        root = str(arguments["root"])
        relative = str(arguments["relative_path"])
        content = str(arguments["content"])
        overwrite = bool(arguments.get("overwrite", False))
        allowed = defn.allowed_roots if defn and defn.allowed_roots else []
        max_bytes = defn.max_content_bytes if defn and defn.max_content_bytes else 200_000
        if len(content.encode("utf-8")) > max_bytes:
            raise ToolArgInvalid(f"내용 크기가 {max_bytes}바이트를 초과합니다.")
        path = resolve_tool_path(
            self.sandbox,
            root_name=root,
            relative=relative,
            allowed_roots=allowed,
            for_write=True,
        )
        if path.exists() and not overwrite:
            raise PolicyDenied(
                "파일이 이미 존재합니다. overwrite=true와 승인이 필요합니다."
            )
        parent = path.parent
        assert_in_sandbox(parent, self.sandbox.write_roots, sandbox=self.sandbox)
        return {
            "root": root,
            "relative_path": relative,
            "path": str(path),
            "content": content,
            "overwrite": overwrite,
            "exists": path.exists(),
        }

    def _effective_risk(
        self,
        tool_name: str,
        normalized: dict[str, Any],
        spec: ToolSpec,
        defn: ToolDefinition | None,
    ) -> Risk:
        risk: Risk = spec.risk
        escalation = defn.risk_escalation if defn else None
        if escalation:
            if tool_name == "open_url":
                if not normalized.get("listed_domain") and "unlisted_domain" in escalation:
                    risk = _max_risk(risk, escalation["unlisted_domain"])
                if normalized.get("has_query") and "has_query_string" in escalation:
                    risk = _max_risk(risk, escalation["has_query_string"])
            if tool_name == "create_file":
                if normalized.get("overwrite") and "overwrite" in escalation:
                    risk = _max_risk(risk, escalation["overwrite"])
                elif not normalized.get("exists") and risk == "medium":
                    pass
        return risk

    def _decision_for_risk(self, risk: Risk) -> Decision:
        if risk == "low":
            return "allow"
        if risk == "medium":
            return "confirm"
        return "typed_confirm"

    def _reason_for_decision(
        self,
        tool_name: str,
        risk: Risk,
        decision: Decision,
        normalized: dict[str, Any],
    ) -> str:
        if decision == "allow":
            return f"{tool_name} 실행을 허용합니다."
        if tool_name == "close_app":
            return "애플리케이션 종료 작업입니다. y/n 확인이 필요합니다."
        if tool_name == "create_file" and normalized.get("overwrite"):
            return "기존 파일을 덮어씁니다. 확인 문구 입력이 필요합니다."
        if tool_name == "open_url" and not normalized.get("listed_domain"):
            return "등록되지 않은 도메인입니다. 승인이 필요합니다."
        if risk == "medium":
            return "중간 위험 작업입니다. y/n 확인이 필요합니다."
        return "높은 위험 작업입니다. 확인 문구 입력이 필요합니다."

    def _build_display(self, tool_name: str, normalized: dict[str, Any]) -> str:
        if tool_name == "open_app":
            return f"앱 실행: {normalized['app']} ({normalized['exe_path']})"
        if tool_name == "close_app":
            return f"앱 종료: {normalized['app']} ({normalized.get('exe_name', '')})"
        if tool_name == "open_folder":
            return f"폴더 열기: {normalized['path']}"
        if tool_name == "open_url":
            return f"URL 열기: {normalized['url']}"
        if tool_name == "create_file":
            action = "덮어쓰기" if normalized.get("overwrite") else "새 파일 생성"
            size = len(str(normalized.get("content", "")).encode("utf-8"))
            return f"{action}: {normalized['path']} ({size:,} bytes)"
        if tool_name == "web_search":
            return f"웹 검색: {normalized.get('query', '')}"
        if tool_name == "doc_search":
            return f"문서 검색: {normalized.get('query', '')}"
        if tool_name == "fetch_url":
            return f"URL 가져오기: {normalized.get('url', '')}"
        return f"{tool_name}: {normalized}"

    def _validate_http_url(self, url: str) -> None:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in self.network.allowed_schemes:
            raise PolicyDenied(f"허용되지 않은 URL 스킴입니다: {scheme or '(없음)'}")
        if self.network.deny_credentials_in_url and (parsed.username or parsed.password):
            raise PolicyDenied("URL에 자격증명을 포함할 수 없습니다.")
        host = parsed.hostname
        if host is None:
            raise PolicyDenied("URL 호스트가 없습니다.")
        lowered = host.lower()
        if lowered.endswith(".local"):
            raise PolicyDenied("로컬 호스트 이름은 차단됩니다.")
        if self.network.deny_mixed_script_idn and _has_mixed_script(lowered):
            raise PolicyDenied("혼합 스크립트 IDN 호스트는 차단됩니다.")
        self._validate_host_ip(lowered)

    def _validate_host_ip(self, host: str) -> None:
        if host == "localhost":
            if self.network.deny_loopback:
                raise PolicyDenied("loopback 호스트는 차단됩니다.")
            return
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as error:
            raise PolicyDenied("호스트 이름을 확인할 수 없습니다.") from error
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if self.network.deny_loopback and ip.is_loopback:
                raise PolicyDenied("loopback IP는 차단됩니다.")
            if self.network.deny_private_ranges and (
                ip.is_private or ip.is_link_local or ip.is_reserved
            ):
                raise PolicyDenied("사설·링크로컬 IP는 차단됩니다.")

    def _domain_listed(self, host: str) -> bool:
        for allowed in self.network.url_allowlist:
            allowed_lower = allowed.lower()
            if host == allowed_lower or host.endswith("." + allowed_lower):
                return True
        return False


def _max_risk(current: Risk, candidate: Risk) -> Risk:
    order = {"low": 0, "medium": 1, "high": 2}
    return candidate if order[candidate] > order[current] else current


def _has_mixed_script(host: str) -> bool:
    try:
        decoded = host.encode("ascii").decode("idna")
    except UnicodeError:
        decoded = host
    scripts: set[str] = set()
    for char in decoded:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        if "LATIN" in name:
            scripts.add("LATIN")
        elif "CYRILLIC" in name:
            scripts.add("CYRILLIC")
        elif "GREEK" in name:
            scripts.add("GREEK")
        else:
            scripts.add(name.split()[0] if name else "OTHER")
    latin = "LATIN" in scripts
    return len(scripts) > 1 and latin
