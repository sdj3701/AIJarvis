"""Junction-based sandbox escape attempts."""

from __future__ import annotations

import os
import subprocess

import pytest

from app.llm.base import ToolCall
from tests.helpers.phase4_app import Phase4App
from tests.security.test_approval_binding import _ctx

pytestmark = [pytest.mark.phase4, pytest.mark.security]


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_junction_escape_blocked(phase4_app: Phase4App) -> None:
    data_root = phase4_app.data_root
    outside = data_root.parent / "outside"
    outside.mkdir(exist_ok=True)
    link = data_root / "docs" / "notes" / "link"
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("junction creation requires appropriate permissions")
    call = ToolCall(
        id="junction",
        name="create_file",
        arguments={"root": "notes", "relative_path": "link\\x.md", "content": "x"},
    )
    outcome = phase4_app.chat.execute_tool_call(call, ctx=_ctx(phase4_app))
    assert not outcome.ok
    assert not (outside / "x.md").exists()
    assert phase4_app.audit()[-1]["phase"] == "denied"
