"""Unit tests for Jarvis GUI webview bridge and launcher compilation."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from app.orchestrator.loop import ChatOrchestrator, TurnOutcome
from app.ui.gui import JarvisWebviewBridge
from scripts.build_exe import find_csc


class DummyBudget:
    def __init__(self) -> None:
        pass


def test_bridge_send_empty_message() -> None:
    chat = MagicMock(spec=ChatOrchestrator)
    bridge = JarvisWebviewBridge(chat)
    assert bridge.send_message("") == ""
    assert bridge.send_message("   ") == ""
    chat.handle_turn.assert_not_called()


def test_bridge_special_commands() -> None:
    chat = MagicMock(spec=ChatOrchestrator)
    mock_budget = MagicMock()
    mock_budget.day.used = 0.0
    mock_budget.day.limit = 10.0
    mock_budget.day.ratio = 0.0
    mock_budget.month.used = 0.0
    mock_budget.month.limit = 100.0
    mock_budget.month.ratio = 0.0
    chat.budget_status.return_value = mock_budget

    bridge = JarvisWebviewBridge(chat)

    clear_rep = bridge.send_message("/clear")
    assert "초기화" in clear_rep
    chat.clear.assert_called_once()

    budget_rep = bridge.send_message("/budget")
    assert "오늘:" in budget_rep

    help_rep = bridge.send_message("/help")
    assert "/help" in help_rep


def test_bridge_send_normal_turn() -> None:
    from decimal import Decimal

    chat = MagicMock(spec=ChatOrchestrator)
    chat.handle_turn.return_value = TurnOutcome(
        ok=True,
        text="메모장을 열었습니다.",
        request_id="req_1",
        turn_id="turn_1",
        input_tokens=10,
        output_tokens=10,
        cost_usd=Decimal("0"),
    )
    bridge = JarvisWebviewBridge(chat)

    reply = bridge.send_message("메모장 열어줘")
    assert reply == "메모장을 열었습니다."
    chat.handle_turn.assert_called_once_with("메모장 열어줘")


def test_bridge_mic_toggle_and_status() -> None:
    chat = MagicMock(spec=ChatOrchestrator)
    bridge = JarvisWebviewBridge(chat, voice_controller=MagicMock())

    status = bridge.get_status()
    assert status["voice_enabled"] is True
    assert status["mic_muted"] is False

    res = bridge.toggle_mic()
    assert res["mic_muted"] is True
    assert bridge.get_status()["mic_muted"] is True

    res2 = bridge.toggle_mic()
    assert res2["mic_muted"] is False


def test_bridge_js_notifications() -> None:
    chat = MagicMock(spec=ChatOrchestrator)
    bridge = JarvisWebviewBridge(chat)
    mock_window = MagicMock()
    bridge.set_window(mock_window)

    bridge.notify_wake()
    mock_window.evaluate_js.assert_called_with("window.onJarvisWake && window.onJarvisWake();")

    bridge.notify_transcript("테스트 명령")
    assert any("테스트 명령" in call.args[0] for call in mock_window.evaluate_js.call_args_list)

    bridge.notify_response("답변입니다")
    assert any("답변입니다" in call.args[0] for call in mock_window.evaluate_js.call_args_list)

    bridge.notify_state("thinking")
    assert any("thinking" in call.args[0] for call in mock_window.evaluate_js.call_args_list)


@pytest.mark.skipif(os.name != "nt", reason="Windows only csc compiler test")
def test_csc_compiler_discovery() -> None:
    csc = find_csc()
    assert csc is not None
    assert csc.is_file()
