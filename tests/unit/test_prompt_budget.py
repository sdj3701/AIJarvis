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

pytestmark = pytest.mark.phase1


def _context(
    *,
    max_input_tokens: int = 400,
    reserve_output_tokens: int = 20,
    history_share: float = 0.5,
    keep_recent_turns: int = 3,
) -> ContextSettings:
    return ContextSettings(
        max_input_tokens=max_input_tokens,
        reserve_output_tokens=reserve_output_tokens,
        memory_share=0.2,
        history_share=history_share,
        keep_recent_turns=keep_recent_turns,
    )


@pytest.fixture
def short_prompt(tmp_path: Path) -> Path:
    path = tmp_path / "system.md"
    path.write_text("<!-- version: 9 -->\n한국어 규칙", encoding="utf-8")
    return path


def _turn(index: int, *, width: int = 20) -> tuple[Message, Message]:
    return (
        Message("user", f"질문-{index}-" + "가" * width),
        Message("assistant", f"답변-{index}-" + "나" * width),
    )


def test_default_system_prompt_has_version_and_safety_rules() -> None:
    assembler = PromptAssembler(
        FakeLLMClient(),
        _context(max_input_tokens=12_288, reserve_output_tokens=2_000),
    )

    plan = assembler.build(
        current_user_text="지금 무엇을 할 수 있나요?",
        history=[Message("user", "안녕"), Message("assistant", "안녕하세요")],
    )

    assert plan.prompt_version == "1"
    assert [message.role for message in plan.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "한국어" in plan.messages[0].content
    assert "추측" in plan.messages[0].content
    assert "untrusted_content" in plan.messages[0].content
    assert plan.messages[-1].content == "지금 무엇을 할 수 있나요?"
    assert plan.input_tokens + 2_000 <= 12_288


def test_old_turns_are_compacted_while_recent_three_are_unchanged(
    short_prompt: Path,
) -> None:
    turns = [_turn(index) for index in range(6)]
    history = [message for turn in turns for message in turn]
    assembler = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt)

    plan = assembler.build(current_user_text="현재 질문", history=history)

    assert plan.compressed is True
    assert plan.compressed_turns == 3
    assert plan.messages[1].role == "assistant"
    assert plan.messages[1].content.startswith("[이전 대화 3턴 압축]")
    assert plan.messages[-7:-1] == tuple(message for turn in turns[-3:] for message in turn)
    assert plan.messages[-1] == Message("user", "현재 질문")
    assert plan.history_tokens <= plan.history_cap
    assert plan.input_tokens + 20 <= 400


def test_short_history_is_not_compacted(short_prompt: Path) -> None:
    history = [message for turn in [_turn(1, width=2), _turn(2, width=2)] for message in turn]
    plan = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt).build(
        current_user_text="새 질문",
        history=history,
    )

    assert plan.compressed is False
    assert plan.compressed_turns == 0
    assert plan.messages[1:-1] == tuple(history)


def test_large_current_input_is_rejected_before_model_call(short_prompt: Path) -> None:
    assembler = PromptAssembler(
        FakeLLMClient(),
        _context(max_input_tokens=100, reserve_output_tokens=10),
        prompt_path=short_prompt,
    )

    with pytest.raises(PromptTooLong, match="입력이 너무") as captured:
        assembler.build(current_user_text="가" * 100)

    assert captured.value.detail["max_input_tokens"] == 100


def test_recent_protected_turns_are_never_dropped(short_prompt: Path) -> None:
    history = [message for index in range(3) for message in _turn(index, width=40)]
    assembler = PromptAssembler(
        FakeLLMClient(),
        _context(max_input_tokens=200, reserve_output_tokens=10),
        prompt_path=short_prompt,
    )

    with pytest.raises(PromptTooLong, match="최근 대화") as captured:
        assembler.build(current_user_text="현재", history=history)

    assert captured.value.detail["protected_turns"] == 3


@pytest.mark.parametrize(
    "history",
    [
        [Message("user", "짝이 없음")],
        [Message("assistant", "순서 오류"), Message("user", "순서 오류")],
        [Message("system", "금지"), Message("assistant", "금지")],
    ],
)
def test_history_requires_completed_user_assistant_pairs(history: list[Message]) -> None:
    with pytest.raises(ValueError, match="히스토리"):
        PromptAssembler(FakeLLMClient(), _context()).build(
            current_user_text="질문",
            history=history,
        )


def test_prompt_file_requires_integer_version(tmp_path: Path) -> None:
    missing_version = tmp_path / "missing-version.md"
    missing_version.write_text("규칙", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        PromptAssembler(FakeLLMClient(), _context(), prompt_path=missing_version)

    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        PromptAssembler(FakeLLMClient(), _context(), prompt_path=tmp_path / "missing.md")


def test_cancellation_is_checked_before_and_after_assembly(short_prompt: Path) -> None:
    token = CancellationToken()
    token.cancel()
    assembler = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt)

    with pytest.raises(InterruptedError):
        assembler.build(current_user_text="취소", cancel=token)


def test_extractive_compressor_normalizes_space_and_long_content() -> None:
    text = ExtractiveHistoryCompressor().compress(
        [(Message("user", "여러\n  공백 " + "가" * 300), Message("assistant", "답변"))]
    )

    assert "여러 공백" in text
    assert "..." in text


def test_empty_current_input_is_rejected(short_prompt: Path) -> None:
    assembler = PromptAssembler(FakeLLMClient(), _context(), prompt_path=short_prompt)
    with pytest.raises(ValueError, match="비어"):
        assembler.build(current_user_text="   ")
