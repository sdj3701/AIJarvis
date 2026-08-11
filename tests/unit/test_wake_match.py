"""Unit tests for wake-word matching helpers."""

from __future__ import annotations

import pytest

from app.voice.stt import VoskSTTEngine
from app.voice.wake_match import (
    normalize_spoken_command,
    strip_leading_wake_word,
    wake_match_kind,
)

pytestmark = pytest.mark.phase7


def test_wake_match_rejects_non_prefix_speech() -> None:
    assert wake_match_kind("안녕하세요", "자비스") == "none"
    assert wake_match_kind("오늘 자비스 날씨", "자비스") == "none"


def test_wake_match_accepts_standalone_and_prefix() -> None:
    assert wake_match_kind("자비스", "자비스") == "standalone"
    assert wake_match_kind("자 비스", "자비스") == "standalone"
    assert wake_match_kind("자비스 수돗물 성분 알려줘", "자비스") == "prefix"


def test_strip_leading_wake_word() -> None:
    assert strip_leading_wake_word("자비스", "자비스") == ""
    assert (
        strip_leading_wake_word("자비스 수돗물의 성분에 대해서 알려줘", "자비스")
        == "수돗물의 성분에 대해서 알려줘"
    )
    assert strip_leading_wake_word("자비스 자비스 가나다", "자비스") == "가나다"
    assert normalize_spoken_command("자 비스") == "자비스"


def test_vosk_grammar_includes_unk(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    captured: dict[str, object] = {}

    class FakeRecognizer:
        def AcceptWaveform(self, pcm: bytes) -> bool:
            del pcm
            return False

        def Result(self) -> str:
            return '{"text":""}'

        def PartialResult(self) -> str:
            return '{"partial":""}'

        def FinalResult(self) -> str:
            return '{"text":""}'

        def SetWords(self, enabled: bool) -> None:
            del enabled

    def fake_factory(model: object, sample_rate: int, grammar: str | None) -> FakeRecognizer:
        del model, sample_rate
        captured["grammar"] = grammar
        return FakeRecognizer()

    monkeypatch.setattr(
        "app.voice.stt.validate_model_directory",
        lambda path, expected_archive_sha256=None: path,
    )
    engine = VoskSTTEngine(
        Path(__file__),
        model_loader=lambda path: object(),
        recognizer_factory=fake_factory,
    )
    engine.stream(phrases=("자비스", "자 비스"))
    assert captured["grammar"] is not None
    assert "[unk]" in str(captured["grammar"])
