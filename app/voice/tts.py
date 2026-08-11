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

_SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$utf8 = [System.Text.UTF8Encoding]::new($false)
$reader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)
$text = $reader.ReadToEnd()
$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $speaker.SelectVoice($env:JARVIS_TTS_VOICE)
    $speaker.Speak($text)
}
finally {
    $speaker.Dispose()
    $reader.Dispose()
}
"""


class SpeechProcess(Protocol):
    returncode: int | None

    def communicate(self, input: bytes, timeout: float | None = None) -> tuple[bytes, bytes]: ...

    def kill(self) -> None: ...


class SpeechProcessFactory(Protocol):
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


@dataclass(frozen=True, slots=True)
class PreparedSpeech:
    text: str
    refused: bool
    truncated: bool


def prepare_speech(text: str, *, masker: LogMasker, max_chars: int) -> PreparedSpeech:
    if not isinstance(text, str):
        raise TypeError("TTS text must be a string")
    if max_chars <= 0:
        raise ValueError("TTS max_chars must be positive")
    masked, findings = masker.mask_text(text)
    if any(finding.kind in {"secret", "pii_high"} for finding in findings):
        return PreparedSpeech("민감한 내용이 포함되어 화면으로만 표시합니다.", True, False)
    truncated = len(masked) > max_chars
    rendered = masked[:max_chars].rstrip()
    if truncated:
        rendered += "… 나머지 내용은 화면에서 확인해 주세요."
    return PreparedSpeech(rendered, False, truncated)


class WindowsSapiTTS:
    """Speak Korean locally through an installed Windows SAPI voice."""

    def __init__(
        self,
        voice: str,
        *,
        timeout_s: float = 60,
        process_factory: SpeechProcessFactory = subprocess.Popen,
    ) -> None:
        if not voice.strip():
            raise ValueError("SAPI voice must not be empty")
        if timeout_s <= 0:
            raise ValueError("TTS timeout must be positive")
        self._voice = voice
        self._timeout_s = timeout_s
        self._process_factory = process_factory
        self._process: SpeechProcess | None = None
        self._lock = RLock()

    def speak(self, text: str, *, ctx: RequestContext | None = None) -> None:
        if not text.strip():
            return
        if ctx is not None:
            ctx.cancel.raise_if_cancelled()
        environment = os.environ.copy()
        environment["JARVIS_TTS_VOICE"] = self._voice
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
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
        with self._lock:
            self._process = process
        try:
            _, stderr = process.communicate(text.encode("utf-8"), timeout=self._timeout_s)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate(b"")
            raise JarvisError("음성 합성 시간이 초과되었습니다.") from error
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
        if process.returncode != 0:
            raise JarvisError(
                "로컬 음성을 재생하지 못했습니다.",
                {"engine": "windows-sapi", "stderr_bytes": len(stderr)},
            )

    def cancel(self) -> None:
        with self._lock:
            process = self._process
        if process is not None and process.returncode is None:
            process.kill()

    def close(self) -> None:
        self.cancel()
