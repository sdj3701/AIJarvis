# 파이썬 공부 | scripts/tests/unit/test_wake_match.py
# wake_match 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Unit tests for wake-word matching helpers."""

from __future__ import annotations

import pytest

from app.voice.stt import VoskSTTEngine
from app.voice.wake_match import (
    normalize_spoken_command,
    strip_leading_wake_word,
    wake_match_kind,
)

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase7


# pytest가 test_wake_match_rejects_non_prefix_speech()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_wake_match_rejects_non_prefix_speech() -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert wake_match_kind("안녕하세요", "자비스") == "none"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert wake_match_kind("오늘 자비스 날씨", "자비스") == "none"


# pytest가 test_wake_match_accepts_standalone_and_prefix()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_wake_match_accepts_standalone_and_prefix() -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert wake_match_kind("자비스", "자비스") == "standalone"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert wake_match_kind("자 비스", "자비스") == "standalone"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert wake_match_kind("자비스 수돗물 성분 알려줘", "자비스") == "prefix"


# pytest가 test_strip_leading_wake_word()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_strip_leading_wake_word() -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert strip_leading_wake_word("자비스", "자비스") == ""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert (
        strip_leading_wake_word("자비스 수돗물의 성분에 대해서 알려줘", "자비스")
        == "수돗물의 성분에 대해서 알려줘"
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert strip_leading_wake_word("자비스 자비스 가나다", "자비스") == "가나다"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert normalize_spoken_command("자 비스") == "자비스"


# pytest가 test_vosk_grammar_includes_unk()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_vosk_grammar_includes_unk(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    # captured에 딕셔너리(키와 값의 쌍)을 대입합니다.
    captured: dict[str, object] = {}

    # FakeRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
    class FakeRecognizer:
        # AcceptWaveform(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 입력: pcm.
        # 반환 타입 힌트: 참/거짓(bool).
        def AcceptWaveform(self, pcm: bytes) -> bool:
            # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
            # 아닙니다.
            del pcm
            # False을 반환하고 이 함수의 실행을 끝냅니다.
            return False

        # Result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 문자열(str).
        def Result(self) -> str:
            # '{"text":""}'을 반환하고 이 함수의 실행을 끝냅니다.
            return '{"text":""}'

        # PartialResult(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 문자열(str).
        def PartialResult(self) -> str:
            # '{"partial":""}'을 반환하고 이 함수의 실행을 끝냅니다.
            return '{"partial":""}'

        # FinalResult(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 반환 타입 힌트: 문자열(str).
        def FinalResult(self) -> str:
            # '{"text":""}'을 반환하고 이 함수의 실행을 끝냅니다.
            return '{"text":""}'

        # SetWords(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
        # self는 이 메서드를 호출한 객체입니다.
        # 입력: enabled.
        # 반환 타입 힌트: 별도 결과 없음(None).
        def SetWords(self, enabled: bool) -> None:
            # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
            # 아닙니다.
            del enabled

    # fake_factory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: model, sample_rate, grammar.
    # 반환 타입 힌트: FakeRecognizer.
    def fake_factory(model: object, sample_rate: int, grammar: str | None) -> FakeRecognizer:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del model, sample_rate
        # 오른쪽 식을 계산한 값을 captured['grammar']에 대입합니다.
        captured["grammar"] = grammar
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return FakeRecognizer()

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(
        "app.voice.stt.validate_model_directory",
        lambda path, expected_archive_sha256=None: path,
    )
    # VoskSTTEngine()의 반환값을 engine에 대입합니다.
    engine = VoskSTTEngine(
        Path(__file__),
        model_loader=lambda path: object(),
        recognizer_factory=fake_factory,
    )
    # engine.stream()을 호출해 작업을 수행합니다.
    engine.stream(phrases=("자비스", "자 비스"))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured["grammar"] is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[unk]" in str(captured["grammar"])
