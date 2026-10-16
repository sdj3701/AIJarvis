# 파이썬 공부 | scripts/tests/integration/test_app_saved_approval.py
# app_saved_approval 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Approval persistence and discovery tests without launching user apps."""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from app.core.errors import PolicyDenied
from app.orchestrator.tool_commands import parse_tool_command
from app.safety.app_access import AppAccess, locked_identity
from app.safety.app_catalog import CatalogEntry
from tests.helpers.phase4_app import build_phase4_app

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase4


# approve(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: app, pending.
def approve(app, pending):
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pending.pending_approval is not None
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return app.runtime.approval_store.grant(
        pending.pending_approval, ctx=app.chat.pending_context, method="user_text"
    )


# pytest가 test_permission_survives_restart_and_can_be_revoked()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_permission_survives_restart_and_can_be_revoked(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
    pending = app.chat.handle_turn("메모장 실행해줘")
    # approve()의 반환값을 ticket에 대입합니다.
    ticket = approve(app, pending)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 123
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert app.chat.resume_after_approval(ticket).ok
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert app.chat.handle_turn("메모장 실행해줘").ok
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert launch.call_count == 2
    # build_phase4_app()의 반환값을 restarted에 대입합니다.
    restarted = build_phase4_app(config_dir)
    # restarted.runtime.safety_gate.app_access.manage()을 호출해 작업을 수행합니다.
    restarted.runtime.safety_gate.app_access.manage("/apps")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 124
        # restarted.chat.handle_turn()의 반환값을 outcome에 대입합니다.
        outcome = restarted.chat.handle_turn("/open_app notepad")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert outcome.ok and outcome.pending_approval is None
    # 오른쪽 식을 계산한 값을 listing에 대입합니다.
    listing = restarted.chat.handle_turn("/apps").text
    # 아래 함수()의 반환값을 record_id에 대입합니다.
    record_id = re.search(r"/apps revoke (\w+)", listing).group(1)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert restarted.chat.handle_turn(f"/apps revoke {record_id}").ok
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert restarted.chat.handle_turn("/open_app notepad").pending_approval is not None


# pytest가 test_denial_saves_nothing()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
def test_denial_saves_nothing(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert app.chat.handle_turn("/open_app notepad").pending_approval is not None
    # app.chat.discard_pending_approval()을 호출해 작업을 수행합니다.
    app.chat.discard_pending_approval(cause="user_deny")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert app.runtime.safety_gate.app_access.manage("/apps") == "저장된 실행 허용 앱이 없습니다."


# pytest가 test_discovery_exact_match_and_file_update()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
def test_discovery_exact_match_and_file_update(tmp_path):
    # 오른쪽 식을 계산한 값을 exe에 대입합니다.
    exe = tmp_path / "KakaoTalk.exe"
    # 바이트 데이터를 파일에 기록합니다.
    exe.write_bytes(b"version one")
    # AppAccess()의 반환값을 access에 대입합니다.
    access = AppAccess(tmp_path, dynamic=True)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.app_access.discover_apps",
               return_value=[CatalogEntry("카카오톡", exe, "test")]):
        # access.resolve()의 반환값을 original에 대입합니다.
        original = access.resolve("카톡", {}, "session", explicit=True)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not access.allowed(original)
    # access.grant()을 호출해 작업을 수행합니다.
    access.grant(original, "카카오톡", "text")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert AppAccess(tmp_path).allowed(original)
    # 바이트 데이터를 파일에 기록합니다.
    exe.write_bytes(b"version two")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with locked_identity(exe) as changed:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert not access.allowed(changed)


# pytest가 test_ambiguous_choice_is_session_bound_and_revalidated()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
def test_ambiguous_choice_is_session_bound_and_revalidated(tmp_path):
    # 언패킹: 오른쪽 결과를 순서대로 (first, second)에 나누어 담습니다.
    first, second = tmp_path / "one.exe", tmp_path / "two.exe"
    # 바이트 데이터를 파일에 기록합니다.
    first.write_bytes(b"one")
    # 바이트 데이터를 파일에 기록합니다.
    second.write_bytes(b"two")
    # AppAccess()의 반환값을 access에 대입합니다.
    access = AppAccess(tmp_path, dynamic=True)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with patch("app.safety.app_access.discover_apps", return_value=[
        CatalogEntry("Editor", first, "test"), CatalogEntry("Editor", second, "test")
    ]), pytest.raises(PolicyDenied) as error:
        # access.resolve()을 호출해 작업을 수행합니다.
        access.resolve("Editor", {}, "session", explicit=True)
    # 아래 함수()의 반환값을 choice에 대입합니다.
    choice = re.search(r"choice:\w+:1", error.value.user_message).group(0)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PolicyDenied):
        # access.resolve()을 호출해 작업을 수행합니다.
        access.resolve(choice, {}, "other-session", explicit=True)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PolicyDenied):
        # access.resolve()을 호출해 작업을 수행합니다.
        access.resolve(choice, {}, "session", explicit=False)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert access.resolve(choice, {}, "session", explicit=True)["exe_path"] == str(first)
    # 바이트 데이터를 파일에 기록합니다.
    first.write_bytes(b"changed")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PolicyDenied):
        # access.resolve()을 호출해 작업을 수행합니다.
        access.resolve(choice, {}, "session", explicit=True)


# pytest가 test_file_lock_prevents_modification()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
def test_file_lock_prevents_modification(tmp_path):
    # 오른쪽 식을 계산한 값을 exe에 대입합니다.
    exe = tmp_path / "editor.exe"
    # 바이트 데이터를 파일에 기록합니다.
    exe.write_bytes(b"original")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with locked_identity(exe), pytest.raises(PermissionError):
        # 바이트 데이터를 파일에 기록합니다.
        exe.write_bytes(b"replaced")


# pytest가 test_storage_failure_prevents_execution()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_storage_failure_prevents_execution(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
    pending = app.chat.handle_turn("/open_app notepad")
    # approve()의 반환값을 ticket에 대입합니다.
    ticket = approve(app, pending)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(app.runtime.safety_gate.app_access, "grant",
                      side_effect=PolicyDenied("저장 실패")), patch(
        "app.tools.impl.open_app.subprocess.Popen"
    ) as launch:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert not app.chat.resume_after_approval(ticket).ok
        # launch.assert_not_called()을 호출해 작업을 수행합니다.
        launch.assert_not_called()


# pytest가 test_corrupt_database_is_not_replaced()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
def test_corrupt_database_is_not_replaced(tmp_path):
    # AppAccess()의 반환값을 access에 대입합니다.
    access = AppAccess(tmp_path)
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    access.path.parent.mkdir(parents=True)
    # 바이트 데이터를 파일에 기록합니다.
    access.path.write_bytes(b"invalid database")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PolicyDenied):
        # access.manage()을 호출해 작업을 수행합니다.
        access.manage("/apps")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert access.path.read_bytes() == b"invalid database"


# pytest가 test_expired_pending_approval_does_not_save_or_launch()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_expired_pending_approval_does_not_save_or_launch(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
    pending = app.chat.handle_turn("/open_app notepad")
    # app.runtime.clock.advance()을 호출해 작업을 수행합니다.
    app.runtime.clock.advance(seconds=3600)
    # approve()의 반환값을 ticket에 대입합니다.
    ticket = approve(app, pending)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert not app.chat.resume_after_approval(ticket).ok
        # launch.assert_not_called()을 호출해 작업을 수행합니다.
        launch.assert_not_called()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()


# pytest가 test_gui_permission_list_and_revoke()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_gui_permission_list_and_revoke(config_dir):
    from app.ui.gui import JarvisWebviewBridge

    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # JarvisWebviewBridge()의 반환값을 bridge에 대입합니다.
    bridge = JarvisWebviewBridge(app.chat)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "y" in bridge.send_message("/open_app notepad")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 123
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "실행을 요청" in bridge.send_message("y")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "PID" in bridge.get_response_detail()
    # bridge.get_app_permissions()의 반환값을 entries에 대입합니다.
    entries = bridge.get_app_permissions()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(entries) == 1 and entries[0]["status"] == "실행 가능"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "취소" in bridge.revoke_app_permission(entries[0]["id"])
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert bridge.get_app_permissions() == []


# pytest가 test_saved_permissions_disabled_always_confirms()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_saved_permissions_disabled_always_confirms(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # 오른쪽 식을 계산한 값을 access에 대입합니다.
    access = app.runtime.safety_gate.app_access
    # access.saved_permissions을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    access.saved_permissions = False
    # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
    pending = app.chat.handle_turn("/open_app notepad")
    # approve()의 반환값을 ticket에 대입합니다.
    ticket = approve(app, pending)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 123
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert app.chat.resume_after_approval(ticket).ok
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert app.chat.handle_turn("/open_app notepad").pending_approval is not None


# pytest가 test_launch_failure_keeps_permission()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_launch_failure_keeps_permission(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # approve()의 반환값을 ticket에 대입합니다.
    ticket = approve(app, app.chat.handle_turn("/open_app notepad"))
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen", side_effect=OSError("failed")):
        # app.chat.resume_after_approval()의 반환값을 failed에 대입합니다.
        failed = app.chat.resume_after_approval(ticket)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not failed.ok and "저장" in failed.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(app.chat.app_permissions()) == 1


# pytest가 test_changed_file_after_consent_never_launches()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_changed_file_after_consent_never_launches(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # approve()의 반환값을 ticket에 대입합니다.
    ticket = approve(app, app.chat.handle_turn("/open_app notepad"))
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.locked_identity") as identity, patch(
        "app.tools.impl.open_app.subprocess.Popen"
    ) as launch:
        # identity.return_value.__enter__.return_value에 딕셔너리(키와 값의 쌍)을 대입합니다.
        identity.return_value.__enter__.return_value = {"sha256": "changed"}
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert not app.chat.resume_after_approval(ticket).ok
        # launch.assert_not_called()을 호출해 작업을 수행합니다.
        launch.assert_not_called()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()


# pytest가 test_voice_consent_saves_permission()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_voice_consent_saves_permission(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
    pending = app.chat.handle_turn("메모장 실행해줘", channel="voice")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pending.pending_approval is not None
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 123
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert app.chat.handle_turn("허용", channel="voice").ok
        # launch.assert_called_once()을 호출해 작업을 수행합니다.
        launch.assert_called_once()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(app.chat.app_permissions()) == 1


# pytest가 test_new_input_invalidates_candidate_selection()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir, tmp_path.
def test_new_input_invalidates_candidate_selection(config_dir, tmp_path):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # 오른쪽 식을 계산한 값을 access에 대입합니다.
    access = app.runtime.safety_gate.app_access
    # access.dynamic을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    access.dynamic = True
    # access._expires에 숫자 등 고정된 값을 대입합니다.
    access._expires = 0
    # 언패킹: 오른쪽 결과를 순서대로 (first, second)에 나누어 담습니다.
    first, second = tmp_path / "one.exe", tmp_path / "two.exe"
    # 바이트 데이터를 파일에 기록합니다.
    first.write_bytes(b"one")
    # 바이트 데이터를 파일에 기록합니다.
    second.write_bytes(b"two")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.app_access.discover_apps", return_value=[
        CatalogEntry("Editor", first, "test"), CatalogEntry("Editor", second, "test")
    ]):
        # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
        pending = app.chat.handle_turn("/open_app Editor")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "choice:" in pending.text, pending.text
    # 아래 함수()의 반환값을 choice에 대입합니다.
    choice = re.search(r"choice:\w+:1", pending.text).group(0)
    # app.chat.handle_turn()을 호출해 작업을 수행합니다.
    app.chat.handle_turn("/apps")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PolicyDenied):
        # access.resolve()을 호출해 작업을 수행합니다.
        access.resolve(choice, {}, app.chat.session_id, explicit=True)


# pytest가 test_non_commands_do_not_launch()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: text.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("text", ["카카오톡 실행하지 마", "카카오톡 실행했어", '"카톡 켜줘"',
                                  "카톡 실행해줘?", "카카오톡을 실행할 수 있어?"])
def test_non_commands_do_not_launch(text):
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert parse_tool_command(text) is None


# pytest가 test_complete_launch_verb_is_not_part_of_app_name()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: text, expected.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(("text", "expected"), [
    ("디스코드 실행", "디스코드"),
    ("Discord 실행.", "Discord"),
    ("디스코드 실행해", "디스코드"),
    ("디스코드 실행시켜", "디스코드"),
    ("카카오톡을 실행", "카카오톡"),
    ("Discord 실행시켜줘", "Discord"),
    ("디스코드 실행시켜 줘.", "디스코드"),
    ("디스코드 실행 시켜 줘.", "디스코드"),
    ("카카오톡 시행시켜줘.", "카카오톡"),
    ("카카오톡을 실행시켜줘", "카카오톡"),
    ("카톡 실행해줘", "카톡"),
])
def test_complete_launch_verb_is_not_part_of_app_name(text, expected):
    # parse_tool_command()의 반환값을 call에 대입합니다.
    call = parse_tool_command(text)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert call is not None and call.name == "open_app"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert call.arguments == {"app": expected}


# pytest가 test_reported_launch_commands_reach_approval_and_execute()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir, tmp_path, text.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("text", ["Discord 실행시켜줘", "디스코드 실행해줘.",
                                  "디스코드 실행", "Discord 실행.",
                                  "디스코드 실행해줘. 허락할게.",
                                  "카카오톡 시행시켜줘."])
def test_reported_launch_commands_reach_approval_and_execute(config_dir, tmp_path, text):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # 오른쪽 식을 계산한 값을 access에 대입합니다.
    access = app.runtime.safety_gate.app_access
    # 언패킹: 오른쪽 결과를 순서대로 (discord, kakao)에 나누어 담습니다.
    discord, kakao = tmp_path / "Discord.exe", tmp_path / "KakaoTalk.exe"
    # 바이트 데이터를 파일에 기록합니다.
    discord.write_bytes(b"discord test executable")
    # 바이트 데이터를 파일에 기록합니다.
    kakao.write_bytes(b"kakao test executable")
    # access._expires에 숫자 등 고정된 값을 대입합니다.
    access._expires = 0
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.safety.app_access.discover_apps", return_value=[
        CatalogEntry("Discord", discord, "test"), CatalogEntry("카카오톡", kakao, "test")
    ]):
        # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
        pending = app.chat.handle_turn(text, channel="voice")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pending.pending_approval is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()
    # 오른쪽 식을 계산한 값을 expected에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    expected = kakao if "카카오톡" in text else discord
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pending.pending_approval.normalized_args["exe_path"] == str(expected)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 123
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert app.chat.handle_turn("허용", channel="voice").ok
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert launch.call_args.args[0] == [str(expected)]
        # launch.assert_called_once()을 호출해 작업을 수행합니다.
        launch.assert_called_once()
        # A subsequent short request reuses the saved permission, not the LLM.
        # app.chat.handle_turn()의 반환값을 repeated에 대입합니다.
        repeated = app.chat.handle_turn(f"{expected.stem} 실행", channel="voice")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert repeated.ok and repeated.pending_approval is None
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert launch.call_count == 2


# pytest가 test_short_launch_rejects_questions_reports_and_negations()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: text.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("text", [
    "디스코드 실행?", "디스코드 실행 방법", "디스코드 실행하지마",
    "디스코드 실행했어", "디스코드 실행 중", '"디스코드 실행"',
    "디스코드 실행해도 돼?", "디스코드 실행 취소",
])
def test_short_launch_rejects_questions_reports_and_negations(text):
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert parse_tool_command(text) is None


# pytest가 test_inline_consent_is_only_a_launch_request()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: suffix.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("suffix", ["허락할게", "허용할게", "승인할게"])
def test_inline_consent_is_only_a_launch_request(suffix):
    # parse_tool_command()의 반환값을 call에 대입합니다.
    call = parse_tool_command(f"디스코드 실행해줘. {suffix}.")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert call is not None and call.arguments == {"app": "디스코드"}


# pytest가 test_inline_consent_does_not_broaden_command_matching()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: text.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("text", [
    '"디스코드 실행해줘. 허락할게."', "디스코드 실행하지 마. 허락할게.",
    "디스코드 실행해줘? 허락할게.", "디스코드 실행해줘. 허락하지 않을게.",
    "디스코드 실행해줘. 허락할게. 파일 삭제해줘.",
])
def test_inline_consent_does_not_broaden_command_matching(text):
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert parse_tool_command(text) is None


# pytest가 test_voice_permission_synonym_is_bound_to_pending_request()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_voice_permission_synonym_is_bound_to_pending_request(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
    pending = app.chat.handle_turn("메모장 실행해줘. 허락할게.", channel="voice")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert pending.pending_approval is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 123
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert app.chat.handle_turn("허락할게.", channel="voice").ok
        # launch.assert_called_once()을 호출해 작업을 수행합니다.
        launch.assert_called_once()
