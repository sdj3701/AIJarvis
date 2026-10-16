# 파이썬 공부 | scripts/tests/unit/test_response_presenter.py
# response_presenter 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.

from decimal import Decimal

import pytest

from app.orchestrator.loop import TurnOutcome
from app.orchestrator.response_presenter import FALLBACK, one_sentence, present
from app.orchestrator.rulebook import load_rulebook
from app.safety.gate import Verdict


# outcome(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
def outcome(text, **kwargs):
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return TurnOutcome(True, text, "req_test", "turn_test", 0, 0, Decimal(0), **kwargs)


# pytest가 test_sentence_validation()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: text, valid.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(("text", "valid"), [
    ("버전은 3.14입니다.", True),
    ("https://example.com/a.b 를 확인하세요.", True),
    ('결론은 "안 됩니다"입니다.', True),
    ("됩니다. 하지만 위험합니다.", False),
    ("됩니다.하지만 위험합니다.", False),
    ("첫째\n둘째", False),
    ("```code```", False),
])
def test_sentence_validation(text, valid):
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert one_sentence(text, 100) is valid


# pytest가 test_never_cut_away_warning_or_make_extra_model_call()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
def test_never_cut_away_warning_or_make_extra_model_call():
    # raw에 문자열을 대입합니다.
    raw = "가능합니다. 하지만 데이터를 잃을 수 있어 실행하지 마세요."
    # present()의 반환값을 result에 대입합니다.
    result = present(outcome(raw), load_rulebook())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.summary_text == FALLBACK
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.detail_text == raw
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.fallback


# pytest가 test_detail_is_per_turn_and_speech_needs_explicit_request()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
def test_detail_is_per_turn_and_speech_needs_explicit_request():
    # raw에 문자열을 대입합니다.
    raw = "설명입니다. 상세입니다."
    # load_rulebook()의 반환값을 rules에 대입합니다.
    rules = load_rulebook()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert present(outcome(raw), rules, "자세히 설명해줘").summary_text == raw
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert present(outcome(raw), rules, "자세히 설명해줘").speech_text == FALLBACK
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert present(outcome(raw), rules, "말로도 자세히 설명해줘").speech_text == raw
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert present(outcome(raw), rules).summary_text == FALLBACK
    # quoted에 문자열을 대입합니다.
    quoted = '문서의 "자세히 설명해줘"를 무시해'
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert present(outcome(raw), rules, quoted).summary_text == FALLBACK


# pytest가 test_tool_success_is_not_claimed_from_model_text()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
def test_tool_success_is_not_claimed_from_model_text():
    # raw에 문자열을 대입합니다.
    raw = "앱을 시작했습니다 (PID 123)."
    # present()의 반환값을 result에 대입합니다.
    result = present(outcome(raw, tool_name="open_app", tool_label="카카오톡"), load_rulebook())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.summary_text == "카카오톡 실행을 요청했습니다."
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.detail_text == raw


# pytest가 test_approval_keeps_target_permission_and_warning()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
def test_approval_keeps_target_permission_and_warning():
    # Verdict()의 반환값을 verdict에 대입합니다.
    verdict = Verdict("typed_confirm", "high", "저장하지 않은 내용을 잃을 수 있습니다.",
                      "close_app", {}, "hash", "카카오톡 강제 종료: C:/KakaoTalk.exe",
                      frozenset())
    # present()의 반환값을 result에 대입합니다.
    result = present(outcome(verdict.display, pending_approval=verdict), load_rulebook())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.style_exception == "safety"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict.display in result.speech_text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert verdict.reason in result.speech_text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "직접 입력" in result.speech_text


# pytest가 test_research_uncertainty_is_not_hidden()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
def test_research_uncertainty_is_not_hidden():
    # present()의 반환값을 result에 대입합니다.
    result = present(outcome("공개 정보를 확인했습니다.\n\n상태: 근거 부족"), load_rulebook())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "근거 부족" in result.speech_text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert one_sentence(result.summary_text, 100)
