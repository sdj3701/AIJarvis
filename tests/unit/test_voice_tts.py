"""Tests for local Windows TTS and its privacy boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import Event, Thread

import pytest

from app.config.loader import load_config
from app.telemetry.masking import LogMasker
from app.voice.tts import WindowsSapiTTS, prepare_speech

pytestmark = pytest.mark.phase7
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class FakeProcess:
    def __init__(self, *, returncode: int = 0) -> None:
        self.returncode: int | None = returncode
        self.input = b""
        self.killed = False

    def communicate(self, input: bytes, timeout: float | None = None) -> tuple[bytes, bytes]:
        del timeout
        self.input += input
        return b"", b"failure" if self.returncode else b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -1


class FakeFactory:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.args: Sequence[str] = ()
        self.environment: Mapping[str, str] = {}

    def __call__(
        self,
        args: Sequence[str],
        *,
        stdin: int,
        stdout: int,
        stderr: int,
        env: Mapping[str, str],
        creationflags: int,
    ) -> FakeProcess:
        del stdin, stdout, stderr, creationflags
        self.args = args
        self.environment = env
        return self.process


class BlockingProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self.returncode = None
        self.started = Event()
        self.released = Event()

    def communicate(self, input: bytes, timeout: float | None = None) -> tuple[bytes, bytes]:
        del timeout
        self.input += input
        self.started.set()
        self.released.wait(timeout=2)
        return b"", b""

    def kill(self) -> None:
        super().kill()
        self.released.set()


@pytest.fixture
def masker(tmp_path: Path) -> LogMasker:
    from scripts.bootstrap import create_tree

    root = tmp_path / "Jarvis"
    create_tree(root)
    config = load_config(
        _copy_config(tmp_path, root)
    )
    return LogMasker.from_policy(config.policies.privacy)


def _copy_config(tmp_path: Path, root: Path) -> Path:
    import shutil

    import yaml

    destination = tmp_path / "config"
    destination.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )
    settings = destination / "settings.yaml"
    document = yaml.safe_load(settings.read_text(encoding="utf-8"))
    document["paths"]["data_root"] = str(root)
    settings.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return destination


def test_sapi_receives_utf8_text_via_stdin_not_command_line() -> None:
    process = FakeProcess()
    factory = FakeFactory(process)
    tts = WindowsSapiTTS("Microsoft Heami Desktop", process_factory=factory)

    tts.speak("무엇을 도와드릴까요.")

    assert process.input.decode("utf-8") == "무엇을 도와드릴까요."
    assert all("무엇을" not in argument for argument in factory.args)
    assert factory.environment["JARVIS_TTS_VOICE"] == "Microsoft Heami Desktop"
    assert factory.environment["JARVIS_TTS_RATE"] == "4"


@pytest.mark.parametrize("rate", [-11, 11])
def test_sapi_rejects_rate_outside_windows_range(rate: int) -> None:
    with pytest.raises(ValueError, match="rate"):
        WindowsSapiTTS("Microsoft Heami Desktop", rate=rate)


def test_high_risk_private_text_is_never_spoken(masker: LogMasker) -> None:
    prepared = prepare_speech("주민번호는 900101-1234567입니다", masker=masker, max_chars=400)

    assert prepared.refused is True
    assert "900101" not in prepared.text
    assert prepared.text == "민감한 내용이 포함되어 화면으로만 표시합니다."


def test_long_speech_is_limited(masker: LogMasker) -> None:
    prepared = prepare_speech("가" * 500, masker=masker, max_chars=20)

    assert prepared.truncated is True
    assert prepared.text.startswith("가" * 20)
    assert "화면" in prepared.text


def test_sapi_failure_does_not_expose_text() -> None:
    from app.core.errors import JarvisError

    tts = WindowsSapiTTS(
        "Microsoft Heami Desktop", process_factory=FakeFactory(FakeProcess(returncode=1))
    )

    with pytest.raises(JarvisError) as captured:
        tts.speak("비밀 응답")
    assert "비밀 응답" not in str(captured.value)


def test_cancel_kills_active_sapi_process() -> None:
    process = BlockingProcess()
    tts = WindowsSapiTTS("Microsoft Heami Desktop", process_factory=FakeFactory(process))
    errors: list[BaseException] = []

    def speak() -> None:
        try:
            tts.speak("긴 답변")
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=speak)
    worker.start()
    assert process.started.wait(timeout=1)

    tts.cancel()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert process.killed is True
    assert len(errors) == 1
