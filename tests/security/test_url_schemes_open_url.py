"""URL scheme blocking for open_url via SafetyGate."""

from __future__ import annotations

import pytest

from app.llm.base import ToolCall
from tests.helpers.phase4_app import Phase4App, read_lines
from tests.security.test_approval_binding import _ctx

pytestmark = [pytest.mark.phase4, pytest.mark.security]


@pytest.mark.parametrize("url", read_lines("url_schemes.txt"))
def test_open_url_scheme_corpus_blocked(phase4_app: Phase4App, url: str) -> None:
    gate = phase4_app.runtime.safety_gate
    spec = phase4_app.runtime.tool_registry.specs["open_url"]
    call = ToolCall(id="u1", name="open_url", arguments={"url": url})
    verdict = gate.evaluate(call, ctx=_ctx(phase4_app), spec=spec)
    assert verdict.decision == "deny", url
