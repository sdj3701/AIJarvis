"""Path traversal corpus must never create files outside sandbox."""

from __future__ import annotations

import pytest

from app.llm.base import ToolCall
from tests.helpers.phase4_app import Phase4App, read_lines, snapshot_tree
from tests.security.test_approval_binding import _ctx

pytestmark = [pytest.mark.phase4, pytest.mark.security]


@pytest.mark.parametrize("payload", read_lines("traversal.txt"))
def test_path_traversal_blocked(phase4_app: Phase4App, payload: str) -> None:
    before = snapshot_tree(phase4_app.data_root)
    call = ToolCall(
        id="traversal",
        name="create_file",
        arguments={"root": "notes", "relative_path": payload, "content": "x"},
    )
    outcome = phase4_app.chat.execute_tool_call(call, ctx=_ctx(phase4_app))
    assert not outcome.ok
    assert snapshot_tree(phase4_app.data_root) == before
    last = phase4_app.audit()[-1]
    assert last["phase"] == "denied"
    assert last["decision"] == "deny"
    assert last["cause"] in {"arg_invalid", "policy_denied"}
    assert last["args_display"]
    assert last["result"] is None
