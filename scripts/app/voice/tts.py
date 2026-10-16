# 파이썬 공부 | scripts/app/voice/tts.py
# 개인정보 규칙을 적용한 텍스트를 Windows SAPI로 읽어 줍니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Windows SAPI text-to-speech with privacy filtering."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from app.core.context import RequestContext
from app.core.errors import JarvisError
from app.telemetry.masking import LogMasker

# _SAPI_SCRIPT에 문자열을 대입합니다.
_SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$utf8 = [System.Text.UTF8Encoding]::new($false)
$reader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)
$text = $reader.ReadToEnd()
$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $speaker.SelectVoice($env:JARVIS_TTS_VOICE)
    $speaker.Rate = [int]$env:JARVIS_TTS_RATE
    $speaker.Speak($text)
}
finally {
    $speaker.Dispose()
    $reader.Dispose()
}
"""


# SpeechProcess: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class SpeechProcess(Protocol):
    # returncode: int | None 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    returncode: int | None

    # communicate(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: input, timeout.
    # 반환 타입 힌트: tuple[bytes, bytes].
    def communicate(self, input: bytes, timeout: float | None = None) -> tuple[bytes, bytes]: ...

    # kill(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def kill(self) -> None: ...


# SpeechProcessFactory: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class SpeechProcessFactory(Protocol):
    # __call__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, stdin, stdout, stderr, env, creationflags.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: SpeechProcess.
    def __call__(
        self,
        args: Sequence[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        env: Mapping[str, str],
        creationflags: int,
    ) -> SpeechProcess: ...


# PreparedSpeech: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class PreparedSpeech:
    # text: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    text: str
    # refused: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    refused: bool
    # truncated: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    truncated: bool


# prepare_speech(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, masker, max_chars.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: PreparedSpeech.
def prepare_speech(text: str, *, masker: LogMasker, max_chars: int) -> PreparedSpeech:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(text, str).
    if not isinstance(text, str):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise TypeError("TTS text must be a string")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: max_chars <= 0.
    if max_chars <= 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("TTS max_chars must be positive")
    # 언패킹: 오른쪽 결과를 순서대로 (masked, findings)에 나누어 담습니다.
    masked, findings = masker.mask_text(text)
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if any(finding.kind in {"secret", "pii_high"} for finding in findings):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return PreparedSpeech("민감한 내용이 포함되어 화면으로만 표시합니다.", True, False)
    # 오른쪽 식을 계산한 값을 truncated에 대입합니다.
    truncated = len(masked) > max_chars
    # masked.rstrip()의 반환값을 rendered에 대입합니다.
    rendered = masked.rstrip()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: truncated.
    if truncated:
        # rendered에 문자열을 대입합니다.
        rendered = "내용이 길어 화면에서 확인해 주세요."
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return PreparedSpeech(rendered, False, truncated)


# WindowsSapiTTS: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class WindowsSapiTTS:
    """Speak Korean locally through an installed Windows SAPI voice."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: voice, rate, timeout_s, process_factory.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        voice: str,
        *,
        rate: int = 4,
        timeout_s: float = 60,
        process_factory: SpeechProcessFactory = subprocess.Popen,
    ) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not voice.strip().
        if not voice.strip():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("SAPI voice must not be empty")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: timeout_s <= 0.
        if timeout_s <= 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("TTS timeout must be positive")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not -10 <= rate <= 10.
        if not -10 <= rate <= 10:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("SAPI rate must be between -10 and 10")
        # 오른쪽 식을 계산한 값을 self._voice에 대입합니다.
        self._voice = voice
        # 오른쪽 식을 계산한 값을 self._rate에 대입합니다.
        self._rate = rate
        # 오른쪽 식을 계산한 값을 self._timeout_s에 대입합니다.
        self._timeout_s = timeout_s
        # 오른쪽 식을 계산한 값을 self._process_factory에 대입합니다.
        self._process_factory = process_factory
        # self._process을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._process: SpeechProcess | None = None
        # RLock()의 반환값을 self._lock에 대입합니다.
        self._lock = RLock()

    # speak(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text, ctx.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def speak(self, text: str, *, ctx: RequestContext | None = None) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not text.strip().
        if not text.strip():
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ctx is not None.
        if ctx is not None:
            # ctx.cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
            ctx.cancel.raise_if_cancelled()
        # os.environ.copy()의 반환값을 environment에 대입합니다.
        environment = os.environ.copy()
        # 오른쪽 식을 계산한 값을 environment['JARVIS_TTS_VOICE']에 대입합니다.
        environment["JARVIS_TTS_VOICE"] = self._voice
        # str()의 반환값을 environment['JARVIS_TTS_RATE']에 대입합니다.
        environment["JARVIS_TTS_RATE"] = str(self._rate)
        # 오른쪽 식을 계산한 값을 creation_flags에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        # self._process_factory()의 반환값을 process에 대입합니다.
        process = self._process_factory(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _SAPI_SCRIPT,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            creationflags=creation_flags,
        )
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock:
            # 오른쪽 식을 계산한 값을 self._process에 대입합니다.
            self._process = process
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 언패킹: 오른쪽 결과를 순서대로 (_, stderr)에 나누어 담습니다.
            _, stderr = process.communicate(text.encode("utf-8"), timeout=self._timeout_s)
        # subprocess.TimeoutExpired를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
        # 담깁니다.
        except subprocess.TimeoutExpired as error:
            # process.kill()을 호출해 작업을 수행합니다.
            process.kill()
            # process.communicate()을 호출해 작업을 수행합니다.
            process.communicate(b"")
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisError("음성 합성 시간이 초과되었습니다.") from error
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with self._lock:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._process is process.
                if self._process is process:
                    # self._process을 아직 값이 없음을 뜻하는 None으로 설정합니다.
                    self._process = None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: process.returncode != 0.
        if process.returncode != 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisError(
                "로컬 음성을 재생하지 못했습니다.",
                {"engine": "windows-sapi", "stderr_bytes": len(stderr)},
            )

    # cancel(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def cancel(self) -> None:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self._lock:
            # 오른쪽 식을 계산한 값을 process에 대입합니다.
            process = self._process
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: process is not None and
        # process.returncode is None.
        if process is not None and process.returncode is None:
            # process.kill()을 호출해 작업을 수행합니다.
            process.kill()

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # self.cancel()을 호출해 작업을 수행합니다.
        self.cancel()
