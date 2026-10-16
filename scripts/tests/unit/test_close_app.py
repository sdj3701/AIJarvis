# 파이썬 공부 | scripts/tests/unit/test_close_app.py
# close_app 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Regression tests for handle-bound close and explicit force approval."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from app.core.errors import PolicyDenied
from app.llm.base import ToolCall
from app.orchestrator.tool_commands import parse_tool_command
from app.tools.base import ToolContext
from app.tools.impl.close_app import CloseAppTool
from tests.helpers.phase4_app import build_phase4_app

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase4
# TARGET에 딕셔너리(키와 값의 쌍)을 대입합니다.
TARGET = {
    "pid": 123,
    "created": 42,
    "exe_path": "test",
    "session": 1,
    "file_identity": [1, 2, 3, 4],
}


# pytest가 test_explicit_commands()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: text, force.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    "text,force",
    [
        ("카카오톡 종료해줘", False),
        ("카톡 꺼줘", False),
        ("카카오톡 강제 종료해줘", True),
        ("/close_app kakaotalk --force", True),
    ],
)
def test_explicit_commands(text, force):
    # parse_tool_command()의 반환값을 call에 대입합니다.
    call = parse_tool_command(text)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert call is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert call.name == "close_app"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert call.arguments == {"app": "kakaotalk", "force": force}


# pytest가 test_non_commands()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: text.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    "text",
    [
        "카카오톡 종료하지 마",
        "카카오톡 종료할 수 있어?",
        '"카카오톡 종료해줘"',
        "카카오톡 종료했어",
        "카카오톡 종료해줘라는 문장",
        "카톡 꺼줘?",
    ],
)
def test_non_commands(text):
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert parse_tool_command(text) is None


# pytest가 test_approval_and_process_identity_binding()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_approval_and_process_identity_binding(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # ToolCall()의 반환값을 call에 대입합니다.
    call = ToolCall("explicit_close_force", "close_app", {"app": "notepad", "force": True})
    # 오른쪽 식을 계산한 값을 spec에 대입합니다.
    spec = app.runtime.tool_runner.registry.specs["close_app"]
    # MagicMock()의 반환값을 ctx에 대입합니다.
    ctx = MagicMock()
    # ctx.channel에 문자열을 대입합니다.
    ctx.channel = "text"
    # ctx.interactive을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    ctx.interactive = True
    # 오른쪽 식을 계산한 값을 gate에 대입합니다.
    gate = app.runtime.safety_gate
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.gate.snapshot_app", return_value=[TARGET]):
        # gate.evaluate()의 반환값을 verdict에 대입합니다.
        verdict = gate.evaluate(call, ctx=ctx, spec=spec)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict.decision == "typed_confirm"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict.risk == "high"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "123" in verdict.display
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.gate.snapshot_app", return_value=[{**TARGET, "created": 43}]):
        # gate.evaluate()의 반환값을 changed에 대입합니다.
        changed = gate.evaluate(call, ctx=ctx, spec=spec)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert changed.args_hash != verdict.args_hash
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert gate.evaluate(replace(call, id="model_call"), ctx=ctx, spec=spec).decision == "deny"


# pytest가 test_close_requires_ticket_and_reports_actual_exit()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir, force, done.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("force,done", [(False, True), (False, False), (True, True)])
def test_close_requires_ticket_and_reports_actual_exit(config_dir, force, done):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # 오른쪽 식을 계산한 값을 spec에 대입합니다.
    spec = app.runtime.tool_runner.registry.specs["close_app"]
    # normalized에 딕셔너리(키와 값의 쌍)을 대입합니다.
    normalized = {"app": "notepad", "targets": [TARGET], "force": force}
    # ToolContext()의 반환값을 ctx에 대입합니다.
    ctx = ToolContext(ctx=MagicMock(), normalized_args=normalized, ticket=MagicMock())
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.close_app.WindowsProcesses") as backend:
        # 오른쪽 식을 계산한 값을 backend.return_value.close.return_value에 대입합니다.
        backend.return_value.close.return_value = done
        # CloseAppTool(spec).run()의 반환값을 result에 대입합니다.
        result = CloseAppTool(spec).run({}, ctx)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.ok == done
        # backend.return_value.close.assert_called_once_with()을 호출해 작업을 수행합니다.
        backend.return_value.close.assert_called_once_with(
            [TARGET], force=force, timeout_s=spec.timeout_s
        )
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PolicyDenied):
        # CloseAppTool(spec).run()을 호출해 작업을 수행합니다.
        CloseAppTool(spec).run({}, replace(ctx, ticket=None))


# pytest가 test_no_running_target_is_denied()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
def test_no_running_target_is_denied(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.gate.snapshot_app", return_value=[]):
        # app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
        outcome = app.chat.handle_turn("/close_app notepad")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not outcome.ok
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.pending_approval is None


# pytest가 test_runner_approval_then_exact_target_execution()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_runner_approval_then_exact_target_execution(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.gate.snapshot_app", return_value=[TARGET]), patch(
        "app.tools.impl.close_app.WindowsProcesses"
    ) as backend:
        # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
        pending = app.chat.handle_turn("/close_app notepad --force")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert pending.pending_approval is not None
        # backend.assert_not_called()을 호출해 작업을 수행합니다.
        backend.assert_not_called()
        # app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
        ticket = app.runtime.approval_store.grant(
            pending.pending_approval, ctx=app.chat.pending_context,
            method="user_typed_phrase",
        )
        # backend.return_value.close.return_value을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        backend.return_value.close.return_value = True
        # app.chat.resume_after_approval()의 반환값을 result에 대입합니다.
        result = app.chat.resume_after_approval(ticket)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.ok
        # backend.return_value.close.assert_called_once()을 호출해 작업을 수행합니다.
        backend.return_value.close.assert_called_once()


# pytest가 test_changed_target_after_approval_never_executes()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_changed_target_after_approval_never_executes(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.gate.snapshot_app", return_value=[TARGET]):
        # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
        pending = app.chat.handle_turn("/close_app notepad")
    # app.runtime.approval_store.grant()의 반환값을 ticket에 대입합니다.
    ticket = app.runtime.approval_store.grant(
        pending.pending_approval, ctx=app.chat.pending_context, method="user_text",
    )
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.gate.snapshot_app", return_value=[{**TARGET, "created": 43}]), patch(
        "app.tools.impl.close_app.WindowsProcesses"
    ) as backend:
        # app.chat.resume_after_approval()의 반환값을 result에 대입합니다.
        result = app.chat.resume_after_approval(ticket)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert not result.ok
        # backend.assert_not_called()을 호출해 작업을 수행합니다.
        backend.assert_not_called()


# pytest가 test_native_handle_revalidation_prevents_any_termination()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
def test_native_handle_revalidation_prevents_any_termination():
    from app.safety.processes import WindowsProcesses

    # WindowsProcesses()의 반환값을 backend에 대입합니다.
    backend = WindowsProcesses()
    # MagicMock()의 반환값을 backend.k에 대입합니다.
    backend.k = MagicMock()
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with (
        patch.object(backend, "open", side_effect=[11, 22]),
        patch.object(backend, "identity", side_effect=[TARGET, {**TARGET, "created": 99}]),
        pytest.raises(PolicyDenied),
    ):
        # 사용하던 연결이나 자원을 닫습니다.
        backend.close([TARGET, TARGET], force=True, timeout_s=1)
    # backend.k.TerminateProcess.assert_not_called()을 호출해 작업을 수행합니다.
    backend.k.TerminateProcess.assert_not_called()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert backend.k.CloseHandle.call_count == 2


# pytest가 test_gui_force_confirmation_roundtrip()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_gui_force_confirmation_roundtrip(config_dir):
    from app.ui.gui import JarvisWebviewBridge
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # JarvisWebviewBridge()의 반환값을 bridge에 대입합니다.
    bridge = JarvisWebviewBridge(app.chat, typed_confirm_phrase="종료확인")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.gate.snapshot_app", return_value=[TARGET]), patch(
        "app.tools.impl.close_app.WindowsProcesses"
    ) as backend:
        # bridge.send_message()의 반환값을 prompt에 대입합니다.
        prompt = bridge.send_message("/close_app notepad --force")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "종료확인" in prompt
        # backend.assert_not_called()을 호출해 작업을 수행합니다.
        backend.assert_not_called()
        # backend.return_value.close.return_value을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        backend.return_value.close.return_value = True
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "종료했습니다" in bridge.send_message("종료확인")
        # backend.return_value.close.assert_called_once()을 호출해 작업을 수행합니다.
        backend.return_value.close.assert_called_once()
