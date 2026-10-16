# 파이썬 공부 | scripts/tests/integration/test_rulebook_parity.py
# rulebook_parity 관련 여러 기능의 연결을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.

from decimal import Decimal
from unittest.mock import patch

from app.llm.base import LLMUsage
from app.orchestrator.response_presenter import FALLBACK
from tests.helpers.phase4_app import build_phase4_app


# pytest가 test_restart_clear_and_details_keep_rules()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_restart_clear_and_details_keep_rules(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # 오른쪽 식을 계산한 값을 rules에 대입합니다.
    rules = app.chat._prompt.rulebook
    # app.chat.handle_turn()의 반환값을 first에 대입합니다.
    first = app.chat.handle_turn("안녕")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.presentation.rulebook_hash == rules.sha256
    # app.chat.clear()을 호출해 작업을 수행합니다.
    app.chat.clear()
    # app.llm.reply()을 호출해 작업을 수행합니다.
    app.llm.reply("긴 답변입니다. 두 번째 문장입니다.", usage=LLMUsage(1, 1, Decimal(0), 1))
    # app.chat.handle_turn()의 반환값을 second에 대입합니다.
    second = app.chat.handle_turn("다시 안녕")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.display_text == FALLBACK
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.presentation.speech_text == FALLBACK
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "두 번째" in app.chat.handle_turn("/details").display_text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert rules.sha256 in app.chat.handle_turn("/status").display_text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert rules.sha256 == build_phase4_app(config_dir).chat._prompt.rulebook.sha256


# pytest가 test_every_prompt_includes_same_snapshot_without_rereading()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
def test_every_prompt_includes_same_snapshot_without_rereading(config_dir):
    # build_phase4_app()의 반환값을 app에 대입합니다.
    app = build_phase4_app(config_dir)
    # 오른쪽 식을 계산한 값을 rules에 대입합니다.
    rules = app.chat._prompt.rulebook
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with patch("app.orchestrator.rulebook.Path.open", side_effect=AssertionError("reread")):
        # app.chat._prompt.build()의 반환값을 first에 대입합니다.
        first = app.chat._prompt.build(current_user_text="질문")
        # app.chat._prompt.build()의 반환값을 second에 대입합니다.
        second = app.chat._prompt.build(current_user_text="자세히 설명해줘")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert rules.sha256 in first.messages[0].content
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert rules.sha256 in second.messages[0].content
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "상세 설명 예외" in second.messages[0].content
