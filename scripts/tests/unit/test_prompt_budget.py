# 파이썬 공부 | scripts/tests/unit/test_prompt_budget.py
# prompt_budget 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for versioned prompt ordering and protected context compaction."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.models import ContextSettings
from app.core.context import CancellationToken
from app.core.errors import PromptTooLong
from app.llm.base import Message
from app.llm.fake import FakeLLMClient
from app.orchestrator.prompt import ExtractiveHistoryCompressor, PromptAssembler
from app.orchestrator.rulebook import load_rulebook

# 오른쪽 식을 계산한 값을 RULEBOOK_TOKENS에 대입합니다.
RULEBOOK_TOKENS = len(load_rulebook().system_text) + 2

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase1


# _context(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: max_input_tokens, reserve_output_tokens, history_share, keep_recent_turns.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: ContextSettings.
def _context(
    *,
    max_input_tokens: int = 400,
    reserve_output_tokens: int = 20,
    history_share: float = 0.5,
    keep_recent_turns: int = 3,
) -> ContextSettings:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return ContextSettings(
        max_input_tokens=max_input_tokens + RULEBOOK_TOKENS,
        reserve_output_tokens=reserve_output_tokens,
        memory_share=0.2,
        history_share=history_share,
        keep_recent_turns=keep_recent_turns,
    )


# short_prompt(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def short_prompt(tmp_path: Path) -> Path:
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "system.md"
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    path.write_text("<!-- version: 9 -->\n한국어 규칙", encoding="utf-8")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return path


# _turn(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: index, width.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[Message, Message].
def _turn(index: int, *, width: int = 20) -> tuple[Message, Message]:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (
        Message("user", f"질문-{index}-" + "가" * width),
        Message("assistant", f"답변-{index}-" + "나" * width),
    )


def test_oversized_recall_is_optional_and_preserves_current_question(short_prompt: Path) -> None:
    assembler = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt)
    plan = assembler.build(current_user_text="현재 질문", retrieved_context="과거 대화" * 10000)
    assert plan.messages[-1] == Message("user", "현재 질문")
    assert all("과거 대화" not in message.content for message in plan.messages)


# pytest가 test_default_system_prompt_has_version_and_safety_rules()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_default_system_prompt_has_version_and_safety_rules() -> None:
    # PromptAssembler()의 반환값을 assembler에 대입합니다.
    assembler = PromptAssembler(
        FakeLLMClient(),
        _context(max_input_tokens=12_288, reserve_output_tokens=2_000),
    )

    # assembler.build()의 반환값을 plan에 대입합니다.
    plan = assembler.build(
        current_user_text="지금 무엇을 할 수 있나요?",
        history=[Message("user", "안녕"), Message("assistant", "안녕하세요")],
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.prompt_version == "1"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [message.role for message in plan.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "한국어" in plan.messages[0].content
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "추측" in plan.messages[0].content
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "untrusted_content" in plan.messages[0].content
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.messages[-1].content == "지금 무엇을 할 수 있나요?"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.input_tokens + 2_000 <= 12_288


# pytest가 test_old_turns_are_compacted_while_recent_three_are_unchanged()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: short_prompt.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_old_turns_are_compacted_while_recent_three_are_unchanged(
    short_prompt: Path,
) -> None:
    # 오른쪽 식을 계산한 값을 turns에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    turns = [_turn(index) for index in range(6)]
    # 오른쪽 식을 계산한 값을 history에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    history = [message for turn in turns for message in turn]
    # PromptAssembler()의 반환값을 assembler에 대입합니다.
    assembler = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt)

    # assembler.build()의 반환값을 plan에 대입합니다.
    plan = assembler.build(current_user_text="현재 질문", history=history)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.compressed is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.compressed_turns == 3
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.messages[1].role == "assistant"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.messages[1].content.startswith("[이전 대화 3턴 압축]")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.messages[-7:-1] == tuple(message for turn in turns[-3:] for message in turn)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.messages[-1] == Message("user", "현재 질문")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.history_tokens <= plan.history_cap
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.input_tokens + 20 <= 400 + RULEBOOK_TOKENS


# pytest가 test_short_history_is_not_compacted()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: short_prompt.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_short_history_is_not_compacted(short_prompt: Path) -> None:
    # 오른쪽 식을 계산한 값을 history에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    history = [message for turn in [_turn(1, width=2), _turn(2, width=2)] for message in turn]
    # 아래 함수()의 반환값을 plan에 대입합니다.
    plan = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt).build(
        current_user_text="새 질문",
        history=history,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.compressed is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.compressed_turns == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert plan.messages[1:-1] == tuple(history)


# pytest가 test_large_current_input_is_rejected_before_model_call()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: short_prompt.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_large_current_input_is_rejected_before_model_call(short_prompt: Path) -> None:
    # PromptAssembler()의 반환값을 assembler에 대입합니다.
    assembler = PromptAssembler(
        FakeLLMClient(),
        _context(max_input_tokens=100, reserve_output_tokens=10),
        prompt_path=short_prompt,
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PromptTooLong, match="입력이 너무") as captured:
        # assembler.build()을 호출해 작업을 수행합니다.
        assembler.build(current_user_text="가" * 100)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.detail["max_input_tokens"] == 100 + RULEBOOK_TOKENS


# pytest가 test_recent_protected_turns_are_never_dropped()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: short_prompt.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_recent_protected_turns_are_never_dropped(short_prompt: Path) -> None:
    # 오른쪽 식을 계산한 값을 history에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    history = [message for index in range(3) for message in _turn(index, width=40)]
    # PromptAssembler()의 반환값을 assembler에 대입합니다.
    assembler = PromptAssembler(
        FakeLLMClient(),
        _context(max_input_tokens=200, reserve_output_tokens=10),
        prompt_path=short_prompt,
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PromptTooLong, match="최근 대화") as captured:
        # assembler.build()을 호출해 작업을 수행합니다.
        assembler.build(current_user_text="현재", history=history)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured.value.detail["protected_turns"] == 3


# pytest가 test_history_requires_completed_user_assistant_pairs()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: history.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    "history",
    [
        [Message("user", "짝이 없음")],
        [Message("assistant", "순서 오류"), Message("user", "순서 오류")],
        [Message("system", "금지"), Message("assistant", "금지")],
    ],
)
def test_history_requires_completed_user_assistant_pairs(history: list[Message]) -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="히스토리"):
        # PromptAssembler(FakeLLMClient(), _context()).build()을 호출해 작업을 수행합니다.
        PromptAssembler(FakeLLMClient(), _context()).build(
            current_user_text="질문",
            history=history,
        )


# pytest가 test_prompt_file_requires_integer_version()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_prompt_file_requires_integer_version(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 missing_version에 대입합니다.
    missing_version = tmp_path / "missing-version.md"
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    missing_version.write_text("규칙", encoding="utf-8")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="version"):
        # PromptAssembler()을 호출해 작업을 수행합니다.
        PromptAssembler(FakeLLMClient(), _context(), prompt_path=missing_version)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        # PromptAssembler()을 호출해 작업을 수행합니다.
        PromptAssembler(FakeLLMClient(), _context(), prompt_path=tmp_path / "missing.md")


# pytest가 test_cancellation_is_checked_before_and_after_assembly()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: short_prompt.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cancellation_is_checked_before_and_after_assembly(short_prompt: Path) -> None:
    # CancellationToken()의 반환값을 token에 대입합니다.
    token = CancellationToken()
    # token.cancel()을 호출해 작업을 수행합니다.
    token.cancel()
    # PromptAssembler()의 반환값을 assembler에 대입합니다.
    assembler = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(InterruptedError):
        # assembler.build()을 호출해 작업을 수행합니다.
        assembler.build(current_user_text="취소", cancel=token)


# pytest가 test_extractive_compressor_normalizes_space_and_long_content()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_extractive_compressor_normalizes_space_and_long_content() -> None:
    # ExtractiveHistoryCompressor().compress()의 반환값을 text에 대입합니다.
    text = ExtractiveHistoryCompressor().compress(
        [(Message("user", "여러\n  공백 " + "가" * 300), Message("assistant", "답변"))]
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "여러 공백" in text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "..." in text


# pytest가 test_empty_current_input_is_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: short_prompt.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_empty_current_input_is_rejected(short_prompt: Path) -> None:
    # PromptAssembler()의 반환값을 assembler에 대입합니다.
    assembler = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="비어"):
        # assembler.build()을 호출해 작업을 수행합니다.
        assembler.build(current_user_text="   ")
