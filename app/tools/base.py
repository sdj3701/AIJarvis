"""Tool contracts shared by registry and Phase 3 search implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.core.context import RequestContext

if TYPE_CHECKING:
    from app.safety.approval import ApprovalTicket
    from app.safety.paths import Sandbox

Risk = Literal["low", "medium", "high"]
Capability = Literal["fs_read", "fs_write", "net_http", "proc_spawn", "audio_in", "audio_out"]
ExecutionMode = Literal["in_process", "managed_process", "detached_allowlisted"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    json_schema: dict[str, Any]
    risk: Risk
    capabilities: frozenset[Capability]
    execution_mode: ExecutionMode
    idempotent: bool
    enabled: bool
    untrusted_output: bool
    timeout_s: float
    phase: int


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    output: str
    data: dict[str, Any] | None
    error: str | None
    changed_paths: tuple[str, ...]
    duration_ms: int
    truncated: bool
    untrusted: bool


@dataclass(frozen=True, slots=True)
class ToolContext:
    ctx: RequestContext
    sandbox: Sandbox | None = None
    ticket: ApprovalTicket | None = None
    normalized_args: dict[str, Any] | None = None


class Tool(Protocol):
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult: ...
