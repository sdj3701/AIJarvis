# 파이썬 공부 | scripts/tests/unit/test_voice_stt.py
# voice_stt 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for offline Vosk transcription."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.voice.base import AudioFrame, Transcript
from app.voice.stt import (
    FasterWhisperSTTEngine,
    VoskRecognizer,
    VoskSTTEngine,
    transcript_passes_quality,
    validate_model_directory,
)

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase7


# FakeRecognizer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeRecognizer:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # self.calls에 숫자 등 고정된 값을 대입합니다.
        self.calls = 0
        # self.words을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.words = False

    # AcceptWaveform(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: pcm.
    # 반환 타입 힌트: 참/거짓(bool).
    def AcceptWaveform(self, pcm: bytes) -> bool:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del pcm
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self.calls += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.calls == 2

    # Result(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def Result(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return json.dumps({"text": "자비스"}, ensure_ascii=False)

    # PartialResult(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def PartialResult(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return json.dumps({"partial": "자"}, ensure_ascii=False)

    # FinalResult(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    def FinalResult(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return json.dumps({"text": "오늘 날씨"}, ensure_ascii=False)

    # SetWords(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: enabled.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def SetWords(self, enabled: bool) -> None:
        # 오른쪽 식을 계산한 값을 self.words에 대입합니다.
        self.words = enabled


# _model_directory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
def _model_directory(tmp_path: Path) -> Path:
    # 오른쪽 식을 계산한 값을 model에 대입합니다.
    model = tmp_path / "model"
    # for 반복문: 대상의 항목을 하나씩 relative에 대입하며 아래 블록을 실행합니다.
    for relative in ("am/final.mdl", "conf/model.conf", "graph/HCLr.fst"):
        # 오른쪽 식을 계산한 값을 path에 대입합니다.
        path = model / relative
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        path.parent.mkdir(parents=True, exist_ok=True)
        # path.touch()을 호출해 작업을 수행합니다.
        path.touch()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return model


# pytest가 test_batch_transcription_keeps_final_segments()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_batch_transcription_keeps_final_segments(tmp_path: Path) -> None:
    # recognizers에 리스트(순서가 있고 수정 가능)을 대입합니다.
    recognizers: list[FakeRecognizer] = []

    # factory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: model, rate, grammar.
    # 반환 타입 힌트: VoskRecognizer.
    def factory(model: object, rate: int, grammar: str | None) -> VoskRecognizer:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del model, rate, grammar
        # FakeRecognizer()의 반환값을 recognizer에 대입합니다.
        recognizer = FakeRecognizer()
        # 리스트 끝에 항목 하나를 추가합니다.
        recognizers.append(recognizer)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return recognizer

    # VoskSTTEngine()의 반환값을 engine에 대입합니다.
    engine = VoskSTTEngine(
        _model_directory(tmp_path),
        model_loader=lambda path: object(),
        recognizer_factory=factory,
    )
    # frames에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    frames: Sequence[AudioFrame] = (
        AudioFrame(b"\x00\x00" * 160, 16_000),
        AudioFrame(b"\x01\x00" * 160, 16_000),
    )

    # engine.transcribe()의 반환값을 transcript에 대입합니다.
    transcript = engine.transcribe(frames)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.text == "자비스 오늘 날씨"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.duration_ms == 20
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert recognizers[0].words is True


# pytest가 test_streaming_recognizer_exposes_partial_and_final()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_streaming_recognizer_exposes_partial_and_final(tmp_path: Path) -> None:
    # grammars에 리스트(순서가 있고 수정 가능)을 대입합니다.
    grammars: list[str | None] = []

    # factory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: model, rate, grammar.
    # 반환 타입 힌트: VoskRecognizer.
    def factory(model: object, rate: int, grammar: str | None) -> VoskRecognizer:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del model, rate
        # 리스트 끝에 항목 하나를 추가합니다.
        grammars.append(grammar)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return FakeRecognizer()

    # VoskSTTEngine()의 반환값을 engine에 대입합니다.
    engine = VoskSTTEngine(
        _model_directory(tmp_path),
        model_loader=lambda path: object(),
        recognizer_factory=factory,
    )
    # engine.stream()의 반환값을 stream에 대입합니다.
    stream = engine.stream(phrases=["자비스"])

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert stream.feed(b"\x00\x00").text == "자"
    # stream.feed()의 반환값을 update에 대입합니다.
    update = stream.feed(b"\x00\x00")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert update.final is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert update.text == "자비스"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert grammars == ['["자비스", "[unk]"]']


# pytest가 test_missing_model_is_reported_without_network_fallback()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_missing_model_is_reported_without_network_fallback(tmp_path: Path) -> None:
    from app.core.errors import JarvisError

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisError) as captured:
        # validate_model_directory()으로 입력 형식과 허용 조건을 검사합니다.
        validate_model_directory(tmp_path / "missing")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "setup_voice.py" in captured.value.user_message


# pytest가 test_model_archive_hash_must_match_configuration()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_model_archive_hash_must_match_configuration(tmp_path: Path) -> None:
    from app.core.errors import JarvisError

    # _model_directory()의 반환값을 model에 대입합니다.
    model = _model_directory(tmp_path)
    # 바이트 데이터를 파일에 기록합니다.
    model.with_suffix(".zip").write_bytes(b"not-the-pinned-model")

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisError) as captured:
        # validate_model_directory()으로 입력 형식과 허용 조건을 검사합니다.
        validate_model_directory(model, expected_archive_sha256="0" * 64)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "SHA-256" in captured.value.user_message


# FakeWhisperSegment: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class FakeWhisperSegment:
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # start: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    start: float
    # end: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    end: float
    # avg_logprob: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    avg_logprob: float
    # no_speech_prob: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    no_speech_prob: float


# FakeWhisperModel: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeWhisperModel:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: segments.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, segments: list[FakeWhisperSegment]) -> None:
        # 오른쪽 식을 계산한 값을 self.segments에 대입합니다.
        self.segments = segments
        # self.calls에 리스트(순서가 있고 수정 가능)을 대입합니다.
        self.calls: list[dict[str, Any]] = []

    # transcribe(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: audio.
    # **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: tuple[list[FakeWhisperSegment], object].
    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[list[FakeWhisperSegment], object]:
        # 리스트 끝에 항목 하나를 추가합니다.
        self.calls.append({"audio": audio, **kwargs})
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.segments, object()


# pytest가 test_faster_whisper_transcribes_pcm_in_memory_and_reports_quality()을 실행해 아래
# 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_faster_whisper_transcribes_pcm_in_memory_and_reports_quality(tmp_path: Path) -> None:
    # FakeWhisperModel()의 반환값을 model에 대입합니다.
    model = FakeWhisperModel(
        [FakeWhisperSegment(" 오늘 날짜를 알려줘.", 0.0, 1.0, -0.25, 0.03)]
    )
    # FasterWhisperSTTEngine()의 반환값을 engine에 대입합니다.
    engine = FasterWhisperSTTEngine(
        tmp_path / "model",
        expected_model_sha256="1" * 64,
        model_factory=lambda path, device, compute: model,  # type: ignore[arg-type]
        model_validator=lambda path, digest: path,
    )

    # engine.transcribe()의 반환값을 transcript에 대입합니다.
    transcript = engine.transcribe([AudioFrame(b"\x00\x10" * 16_000, 16_000)])

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.text == "오늘 날짜를 알려줘."
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.avg_logprob == pytest.approx(-0.25)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.no_speech_probability == pytest.approx(0.03)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.confidence == pytest.approx(0.7788, abs=0.0001)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert model.calls[0]["language"] == "ko"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert model.calls[0]["beam_size"] == 5
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(model.calls[0]["audio"]) == 16_000
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript_passes_quality(
        transcript, min_avg_logprob=-1.0, max_no_speech_probability=0.6
    )


# pytest가 test_faster_whisper_falls_back_to_cpu_once_after_cuda_failure()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_faster_whisper_falls_back_to_cpu_once_after_cuda_failure(tmp_path: Path) -> None:
    # FakeWhisperModel()의 반환값을 model에 대입합니다.
    model = FakeWhisperModel(
        [FakeWhisperSegment("테스트", 0.0, 0.5, -0.2, 0.01)]
    )
    # attempts에 리스트(순서가 있고 수정 가능)을 대입합니다.
    attempts: list[tuple[str, str]] = []

    # factory(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: path, device, compute_type.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def factory(path: Path, device: str, compute_type: str) -> Any:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del path
        # 리스트 끝에 항목 하나를 추가합니다.
        attempts.append((device, compute_type))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: device == 'cuda'.
        if device == "cuda":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RuntimeError("CUDA DLL missing")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return model

    # FasterWhisperSTTEngine()의 반환값을 engine에 대입합니다.
    engine = FasterWhisperSTTEngine(
        tmp_path / "model",
        expected_model_sha256="1" * 64,
        model_factory=factory,
        model_validator=lambda path, digest: path,
    )

    # engine.transcribe()의 반환값을 transcript에 대입합니다.
    transcript = engine.transcribe([AudioFrame(b"\x00\x00" * 8_000, 16_000)])

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert transcript.text == "테스트"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert engine.active_device == "cpu"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "CUDA DLL missing" in (engine.fallback_reason or "")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert attempts == [("cuda", "int8_float16"), ("cpu", "int8")]


# pytest가 test_quality_guard_rejects_uncertain_or_no_speech_result()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_quality_guard_rejects_uncertain_or_no_speech_result() -> None:
    # Transcript()의 반환값을 uncertain에 대입합니다.
    uncertain = Transcript("엉뚱한 문장", "ko", 1_000, 0.1, -2.0, 0.8)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not transcript_passes_quality(
        uncertain, min_avg_logprob=-1.0, max_no_speech_probability=0.6
    )
