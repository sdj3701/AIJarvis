# 파이썬 공부 | scripts/tests/unit/test_gui_bridge.py
# gui_bridge 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Unit tests for Jarvis GUI webview bridge and launcher compilation."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from app.orchestrator.loop import ChatOrchestrator, TurnOutcome
from app.ui.gui import JarvisWebviewBridge
from scripts.build_exe import find_csc


# DummyBudget: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class DummyBudget:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
        pass


# pytest가 test_bridge_send_empty_message()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bridge_send_empty_message() -> None:
    # MagicMock()의 반환값을 chat에 대입합니다.
    chat = MagicMock(spec=ChatOrchestrator)
    # JarvisWebviewBridge()의 반환값을 bridge에 대입합니다.
    bridge = JarvisWebviewBridge(chat)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert bridge.send_message("") == ""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert bridge.send_message("   ") == ""
    # chat.handle_turn.assert_not_called()을 호출해 작업을 수행합니다.
    chat.handle_turn.assert_not_called()


# pytest가 test_bridge_special_commands()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bridge_special_commands() -> None:
    # MagicMock()의 반환값을 chat에 대입합니다.
    chat = MagicMock(spec=ChatOrchestrator)
    # MagicMock()의 반환값을 mock_budget에 대입합니다.
    mock_budget = MagicMock()
    # mock_budget.day.used에 숫자 등 고정된 값을 대입합니다.
    mock_budget.day.used = 0.0
    # mock_budget.day.limit에 숫자 등 고정된 값을 대입합니다.
    mock_budget.day.limit = 10.0
    # mock_budget.day.ratio에 숫자 등 고정된 값을 대입합니다.
    mock_budget.day.ratio = 0.0
    # mock_budget.month.used에 숫자 등 고정된 값을 대입합니다.
    mock_budget.month.used = 0.0
    # mock_budget.month.limit에 숫자 등 고정된 값을 대입합니다.
    mock_budget.month.limit = 100.0
    # mock_budget.month.ratio에 숫자 등 고정된 값을 대입합니다.
    mock_budget.month.ratio = 0.0
    # 오른쪽 식을 계산한 값을 chat.budget_status.return_value에 대입합니다.
    chat.budget_status.return_value = mock_budget

    # JarvisWebviewBridge()의 반환값을 bridge에 대입합니다.
    bridge = JarvisWebviewBridge(chat)

    # bridge.send_message()의 반환값을 clear_rep에 대입합니다.
    clear_rep = bridge.send_message("/clear")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "초기화" in clear_rep
    # chat.clear.assert_called_once()을 호출해 작업을 수행합니다.
    chat.clear.assert_called_once()

    # bridge.send_message()의 반환값을 budget_rep에 대입합니다.
    budget_rep = bridge.send_message("/budget")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "오늘:" in budget_rep

    # bridge.send_message()의 반환값을 help_rep에 대입합니다.
    help_rep = bridge.send_message("/help")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "/help" in help_rep


# pytest가 test_bridge_send_normal_turn()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bridge_send_normal_turn() -> None:
    from decimal import Decimal

    # MagicMock()의 반환값을 chat에 대입합니다.
    chat = MagicMock(spec=ChatOrchestrator)
    # TurnOutcome()의 반환값을 chat.handle_turn.return_value에 대입합니다.
    chat.handle_turn.return_value = TurnOutcome(
        ok=True,
        text="메모장을 열었습니다.",
        request_id="req_1",
        turn_id="turn_1",
        input_tokens=10,
        output_tokens=10,
        cost_usd=Decimal("0"),
    )
    # JarvisWebviewBridge()의 반환값을 bridge에 대입합니다.
    bridge = JarvisWebviewBridge(chat)

    # bridge.send_message()의 반환값을 reply에 대입합니다.
    reply = bridge.send_message("메모장 열어줘")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert reply == "메모장을 열었습니다."
    # chat.handle_turn.assert_called_once_with()을 호출해 작업을 수행합니다.
    chat.handle_turn.assert_called_once_with("메모장 열어줘")


# pytest가 test_bridge_mic_toggle_and_status()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bridge_mic_toggle_and_status() -> None:
    # MagicMock()의 반환값을 chat에 대입합니다.
    chat = MagicMock(spec=ChatOrchestrator)
    # JarvisWebviewBridge()의 반환값을 bridge에 대입합니다.
    bridge = JarvisWebviewBridge(chat, voice_controller=MagicMock())

    # bridge.get_status()의 반환값을 status에 대입합니다.
    status = bridge.get_status()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert status["voice_enabled"] is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert status["mic_muted"] is False

    # bridge.toggle_mic()의 반환값을 res에 대입합니다.
    res = bridge.toggle_mic()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert res["mic_muted"] is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert bridge.get_status()["mic_muted"] is True

    # bridge.toggle_mic()의 반환값을 res2에 대입합니다.
    res2 = bridge.toggle_mic()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert res2["mic_muted"] is False


# pytest가 test_bridge_js_notifications()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bridge_js_notifications() -> None:
    # MagicMock()의 반환값을 chat에 대입합니다.
    chat = MagicMock(spec=ChatOrchestrator)
    # JarvisWebviewBridge()의 반환값을 bridge에 대입합니다.
    bridge = JarvisWebviewBridge(chat)
    # MagicMock()의 반환값을 mock_window에 대입합니다.
    mock_window = MagicMock()
    # bridge.set_window()을 호출해 작업을 수행합니다.
    bridge.set_window(mock_window)

    # bridge.notify_wake()을 호출해 작업을 수행합니다.
    bridge.notify_wake()
    # mock_window.evaluate_js.assert_called_with()을 호출해 작업을 수행합니다.
    mock_window.evaluate_js.assert_called_with("window.onJarvisWake && window.onJarvisWake();")

    # bridge.notify_transcript()을 호출해 작업을 수행합니다.
    bridge.notify_transcript("테스트 명령")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any("테스트 명령" in call.args[0] for call in mock_window.evaluate_js.call_args_list)

    # bridge.notify_response()을 호출해 작업을 수행합니다.
    bridge.notify_response("답변입니다")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any("답변입니다" in call.args[0] for call in mock_window.evaluate_js.call_args_list)

    # bridge.notify_state()을 호출해 작업을 수행합니다.
    bridge.notify_state("thinking")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert any("thinking" in call.args[0] for call in mock_window.evaluate_js.call_args_list)


# pytest가 test_csc_compiler_discovery()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.skipif(os.name != "nt", reason="Windows only csc compiler test")
def test_csc_compiler_discovery() -> None:
    # find_csc()의 반환값을 csc에 대입합니다.
    csc = find_csc()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert csc is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert csc.is_file()
