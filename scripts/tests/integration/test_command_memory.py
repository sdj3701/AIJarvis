# 파이썬 공부 | scripts/tests/integration/test_command_memory.py
# command_memory 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.

"""Persistent command meanings and embeddings, independent of executable permissions."""
import sqlite3
from decimal import Decimal
from unittest.mock import patch

import pytest
import yaml

from app.llm.base import LLMUsage, ToolCall
from app.orchestrator.command_memory import CommandMemory, eligible
from tests.helpers.phase4_app import build_phase4_app


# FakeEmbedder: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeEmbedder:
    # identity에 문자열을 대입합니다.
    identity = "test-model:digest-v1"

    # embed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    def embed(self, text):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return [1.0, 0.0, 0.0]


# attach(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: app.
def attach(app):
    # CommandMemory()의 반환값을 app.chat._commands에 대입합니다.
    app.chat._commands = CommandMemory(app.runtime.memory_db, FakeEmbedder())
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return app.chat._commands


# pytest가 test_enabled_config_wires_storage_and_reuses_after_restart()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_enabled_config_wires_storage_and_reuses_after_restart(config_dir):
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = config_dir / "settings.yaml"
    # yaml.safe_load()의 반환값을 settings에 대입합니다.
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # settings['command_memory']['enabled']을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    settings["command_memory"]["enabled"] = True
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.orchestrator.loop.OllamaSentenceEmbedder", return_value=FakeEmbedder()):
        # build_phase4_app()의 반환값을 app에 대입합니다.
        app = build_phase4_app(config_dir)
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert app.chat._commands.path == app.runtime.memory_db
        # app.chat.handle_turn()의 반환값을 learned에 대입합니다.
        learned = app.chat.handle_turn("/learn 작업 시작 => /open_app notepad")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "저장했습니다" in learned.text
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert "1건" in app.chat.handle_turn("/commands").text
        # app.chat.clear()을 호출해 작업을 수행합니다.
        app.chat.clear()
        # build_phase4_app()의 반환값을 restarted에 대입합니다.
        restarted = build_phase4_app(config_dir)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with (
        patch.object(restarted.chat._commands.embedder, "embed",
                     side_effect=AssertionError("exact reuse must work offline")),
        patch("app.tools.impl.open_app.OpenAppTool._launch") as launch,
    ):
        # restarted.chat.handle_turn()의 반환값을 result에 대입합니다.
        result = restarted.chat.handle_turn("작업 시작")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.pending_approval is not None
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert not result.intent_confirmation
        # launch.assert_not_called()을 호출해 작업을 수행합니다.
        launch.assert_not_called()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not restarted.chat.app_permissions()


# pytest가 test_explicit_correction_takes_priority_over_parser()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_explicit_correction_takes_priority_over_parser(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # The user explicitly assigns this phrase to a different installed target.
    # app.chat.handle_turn()의 반환값을 result에 대입합니다.
    result = app.chat.handle_turn("/learn 디스코드 실행 => /open_app notepad")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "저장했습니다" in result.text
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.OpenAppTool._launch") as launch:
        # app.chat.handle_turn()의 반환값을 result에 대입합니다.
        result = app.chat.handle_turn("디스코드 실행")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.pending_tool_call.arguments == {"app": "notepad"}
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.pending_approval is not None
        # launch.assert_not_called()을 호출해 작업을 수행합니다.
        launch.assert_not_called()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.exact("디스코드 실행").call.arguments == {"app": "notepad"}


# pytest가 test_persistence_vectors_delete_and_offline_exact()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_persistence_vectors_delete_and_offline_exact(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # store.remember()을 호출해 작업을 수행합니다.
    store.remember("메모장 좀 띄워줘", ToolCall("test", "open_app", {"app": "notepad"}),
                   provenance="user_confirmed")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.index_pending() == 1
    # CommandMemory()의 반환값을 restarted에 대입합니다.
    restarted = CommandMemory(app.runtime.memory_db, FakeEmbedder())
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(restarted.embedder, "embed", side_effect=OSError("offline")):
        # restarted.search()의 반환값을 found에 대입합니다.
        found = restarted.search("메모장 좀 띄워줘.")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert found.exact and found.call.arguments == {"app": "notepad"}
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with restarted.connection() as db:
        # 오른쪽 식을 계산한 값을 key에 대입합니다.
        key = db.execute("SELECT id FROM command_examples").fetchone()[0]
    # restarted.manage()을 호출해 작업을 수행합니다.
    restarted.manage(f"/commands forget {key}")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert restarted.search("메모장 좀 띄워줘") is None


# pytest가 test_semantic_confirmation_is_not_execution_approval()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_semantic_confirmation_is_not_execution_approval(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # store.remember()을 호출해 작업을 수행합니다.
    store.remember("메모장 실행", ToolCall("test", "open_app", {"app": "notepad"}),
                   provenance="explicit_command")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.OpenAppTool._launch") as launch:
        # app.chat.handle_turn()의 반환값을 interpretation에 대입합니다.
        interpretation = app.chat.handle_turn("메모장 좀 띄워줘", channel="voice")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert interpretation.intent_confirmation
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert interpretation.pending_approval is None
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with store.connection() as db:
            # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
            assert db.execute("SELECT COUNT(*) FROM command_examples").fetchone()[0] == 1
        # app.chat.handle_turn()의 반환값을 pending에 대입합니다.
        pending = app.chat.handle_turn("맞아", channel="voice")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert pending.pending_approval is not None
        # launch.assert_not_called()을 호출해 작업을 수행합니다.
        launch.assert_not_called()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.search("메모장 좀 띄워줘").exact
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 123
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert app.chat.handle_turn("허용", channel="voice").ok
        # launch.assert_called_once()을 호출해 작업을 수행합니다.
        launch.assert_called_once()
    # build_phase4_app()의 반환값을 restarted에 대입합니다.
    restarted = build_phase4_app(config_dir)
    # attach()을 호출해 작업을 수행합니다.
    attach(restarted)
    # restarted.chat.app_permissions()을 호출해 작업을 수행합니다.
    restarted.chat.app_permissions()  # Initialize ACL outside the subprocess mock.
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.tools.impl.open_app.subprocess.Popen") as launch:
        # launch.return_value.pid에 숫자 등 고정된 값을 대입합니다.
        launch.return_value.pid = 456
        # restarted.chat.handle_turn()의 반환값을 result에 대입합니다.
        result = restarted.chat.handle_turn("메모장 좀 띄워줘", channel="voice")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.ok and not result.intent_confirmation and result.pending_approval is None
        # launch.assert_called_once()을 호출해 작업을 수행합니다.
        launch.assert_called_once()


# pytest가 test_negative_and_question_never_retrieve()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: text, tmp_path.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("text", ["메모장 실행하지 마", "메모장 실행했어?", '"메모장 띄워줘"',
                                  "메모장 말고 디스코드 실행해", "메모장 실행 방법"])
def test_negative_and_question_never_retrieve(text, tmp_path):
    # CommandMemory()의 반환값을 store에 대입합니다.
    store = CommandMemory(tmp_path / "test.sqlite3", FakeEmbedder())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not eligible(text)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(store, "connection", side_effect=AssertionError("must not search")):
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert store.search(text) is None


# pytest가 test_expiry_and_cancel_do_not_learn()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_expiry_and_cancel_do_not_learn(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # store.remember()을 호출해 작업을 수행합니다.
    store.remember("메모장 실행", ToolCall("test", "open_app", {"app": "notepad"}),
                   provenance="explicit_command")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert app.chat.handle_turn("메모장 띄워줘").intent_confirmation
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "취소" in app.chat.handle_turn("취소").text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not store.search("메모장 띄워줘").exact
    # app.chat.handle_turn()을 호출해 작업을 수행합니다.
    app.chat.handle_turn("메모장 띄워줘")
    # app.runtime.clock.advance()을 호출해 작업을 수행합니다.
    app.runtime.clock.advance(seconds=121)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "만료" in app.chat.handle_turn("맞아").text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()


# pytest가 test_teach_updates_without_executing_and_retains_meaning_on_index_failure()을 실행해
# 아래 상황이
# 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
def test_teach_updates_without_executing_and_retains_meaning_on_index_failure(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch.object(store.embedder, "embed", side_effect=OSError("offline")):
        # app.chat.handle_turn()의 반환값을 result에 대입합니다.
        result = app.chat.handle_turn("/learn 작업 시작 => /open_app notepad")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "대기" in result.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.search("작업 시작").exact
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.index_pending() == 1


# pytest가 test_model_fallback_proposes_only()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_model_fallback_proposes_only(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # app.llm.script.clear()을 호출해 작업을 수행합니다.
    app.llm.script.clear()
    # app.llm.reply()을 호출해 작업을 수행합니다.
    app.llm.reply('{"intent":"open_app","app":"notepad"}',
                  usage=LLMUsage(1, 1, Decimal(0), 1))
    # app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = app.chat.handle_turn("메모장 좀 띄워줘")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.intent_confirmation
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "0건" in store.manage("/commands")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()


# pytest가 test_named_other_app_does_not_inherit_nearest_target()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_named_other_app_does_not_inherit_nearest_target(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # store.remember()을 호출해 작업을 수행합니다.
    store.remember("디스코드 실행", ToolCall("test", "open_app", {"app": "discord"}),
                   provenance="explicit_command")
    # app.llm.script.clear()을 호출해 작업을 수행합니다.
    app.llm.script.clear()
    # app.llm.reply()을 호출해 작업을 수행합니다.
    app.llm.reply('{"intent":"open_app","app":"notepad"}')
    # app.chat.handle_turn()의 반환값을 proposed에 대입합니다.
    proposed = app.chat.handle_turn("메모장 좀 띄워줘")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert proposed.intent_confirmation
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "notepad" in proposed.text and "discord" not in proposed.text


# pytest가 test_badly_parsed_polite_app_name_falls_back_to_meaning()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_badly_parsed_polite_app_name_falls_back_to_meaning(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # store.remember()을 호출해 작업을 수행합니다.
    store.remember("메모장 실행", ToolCall("test", "open_app", {"app": "notepad"}),
                   provenance="explicit_command")
    # app.chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = app.chat.handle_turn("메모장 좀 켜줘")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert outcome.intent_confirmation
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "notepad" in outcome.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()


# pytest가 test_new_input_and_channel_change_invalidate_intent()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
def test_new_input_and_channel_change_invalidate_intent(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # attach()의 반환값을 store에 대입합니다.
    store = attach(app)
    # store.remember()을 호출해 작업을 수행합니다.
    store.remember("메모장 실행", ToolCall("test", "open_app", {"app": "notepad"}),
                   provenance="explicit_command")
    # app.chat.handle_turn()을 호출해 작업을 수행합니다.
    app.chat.handle_turn("메모장 띄워줘", channel="voice")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "만료" in app.chat.handle_turn("맞아", channel="text").text
    # app.chat.handle_turn()을 호출해 작업을 수행합니다.
    app.chat.handle_turn("메모장 띄워줘", channel="voice")
    # app.chat.clear()을 호출해 작업을 수행합니다.
    app.chat.clear()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert app.chat._pending_intent is None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not app.chat.app_permissions()


# pytest가 test_model_change_reindexes_without_losing_examples()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
def test_model_change_reindexes_without_losing_examples(tmp_path):
    # CommandMemory()의 반환값을 store에 대입합니다.
    store = CommandMemory(tmp_path / "memory.sqlite3", FakeEmbedder())
    # store.remember()을 호출해 작업을 수행합니다.
    store.remember("메모장 실행", ToolCall("test", "open_app", {"app": "notepad"}),
                   provenance="explicit_command")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.index_pending() == 1
    # store.embedder.identity에 문자열을 대입합니다.
    store.embedder.identity = "test-model:digest-v2"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.index_pending() == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert store.search("메모장 실행").exact
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with store.connection() as db:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert db.execute("SELECT COUNT(*) FROM command_examples").fetchone()[0] == 1
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert db.execute("SELECT COUNT(*) FROM command_vectors").fetchone()[0] == 2


# pytest가 test_corrupt_database_is_not_reset()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
def test_corrupt_database_is_not_reset(tmp_path):
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "memory.sqlite3"
    # 바이트 데이터를 파일에 기록합니다.
    path.write_bytes(b"broken")
    # CommandMemory()의 반환값을 store에 대입합니다.
    store = CommandMemory(path, FakeEmbedder())
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(sqlite3.DatabaseError):
        # store.manage()을 호출해 작업을 수행합니다.
        store.manage("/commands")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert path.read_bytes() == b"broken"
