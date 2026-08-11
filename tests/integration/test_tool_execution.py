"""Integration tests for secure tool execution."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from unittest.mock import patch

import pytest

from tests.helpers.phase4_app import Phase4App
from tests.security.test_approval_binding import _ctx

pytestmark = pytest.mark.phase4


def test_open_allowed_app(phase4_app: Phase4App) -> None:
    with patch("app.tools.impl.open_app.subprocess.Popen") as popen:
        proc = popen.return_value
        proc.pid = 4242
        outcome = phase4_app.chat.handle_turn("/open_app notepad")
    assert outcome.ok
    audit = phase4_app.audit()
    assert any(record["phase"] == "intent" for record in audit)
    assert any(record["phase"] == "result" for record in audit)


def test_unlisted_app_denied_with_reason(phase4_app: Phase4App) -> None:
    outcome = phase4_app.chat.handle_turn("/open_app chrome")
    assert not outcome.ok
    assert phase4_app.audit()[-1]["phase"] == "denied"


def test_create_file_with_approval(phase4_app: Phase4App) -> None:
    import uuid

    name = f"hello-{uuid.uuid4().hex[:8]}.md"
    outcome = phase4_app.chat.handle_turn(f"/create_file notes {name} hello")
    assert outcome.pending_approval is not None
    ticket = phase4_app.runtime.approval_store.grant(
        outcome.pending_approval,
        ctx=phase4_app.chat.pending_context,  # type: ignore[arg-type]
        method="user_text",
    )
    resumed = phase4_app.chat.resume_after_approval(ticket)
    assert resumed.ok
    target = phase4_app.data_root / "docs" / "notes" / name
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "hello"


def test_create_file_content_is_masked_in_audit(phase4_app: Phase4App) -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz"
    outcome = phase4_app.chat.handle_turn(
        f"/create_file notes audit-secret.md {secret}"
    )

    assert outcome.pending_approval is not None
    serialized = json.dumps(phase4_app.audit(), ensure_ascii=False)
    assert secret not in serialized
    assert "OpenAI 형식 API 키" in serialized


@patch("app.tools.impl.open_app.subprocess.Popen")
def test_allowlisted_app_is_detached(popen, phase4_app: Phase4App) -> None:
    proc = popen.return_value
    proc.pid = 9999
    outcome = phase4_app.chat.handle_turn("/open_app calc")
    assert outcome.ok
    popen.assert_called_once()
    assert popen.call_args.kwargs.get("shell") is False


@pytest.mark.skipif(os.name != "nt", reason="Windows timeout process test")
def test_timeout_kills_process_tree(phase4_app: Phase4App) -> None:
    import sys
    import time

    from app.llm.base import ToolCall

    runner = phase4_app.runtime.tool_runner
    spec = runner.registry.specs["web_search"]
    managed_spec = replace(spec, execution_mode="managed_process", timeout_s=1)

    class SlowManaged:
        spec = managed_spec

        def managed_command(self, args, tctx):
            return [
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ]

        def run(self, args, tctx):
            raise AssertionError("managed_process only")

    runner.registry.specs["web_search"] = managed_spec
    runner.registry.tools["web_search"] = SlowManaged()  # type: ignore[assignment]
    call = ToolCall(id="slow", name="web_search", arguments={"query": "test"})
    result = runner.execute(call, ctx=_ctx(phase4_app), ticket=None)
    assert not result.ok
    time.sleep(0.3)
