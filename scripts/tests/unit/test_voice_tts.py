# 파이썬 공부 | scripts/tests/unit/test_voice_tts.py
# voice_tts 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for local Windows TTS and its privacy boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import Event, Thread

import pytest

from app.config.loader import load_config
from app.telemetry.masking import LogMasker
from app.voice.tts import WindowsSapiTTS, prepare_speech

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase7
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


# FakeProcess: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeProcess:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: returncode.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, *, returncode: int = 0) -> None:
        # 오른쪽 식을 계산한 값을 self.returncode에 대입합니다.
        self.returncode: int | None = returncode
        # self.input에 숫자 등 고정된 값을 대입합니다.
        self.input = b""
        # self.killed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.killed = False

    # communicate(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: input, timeout.
    # 반환 타입 힌트: tuple[bytes, bytes].
    def communicate(self, input: bytes, timeout: float | None = None) -> tuple[bytes, bytes]:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del timeout
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self.input += input
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return b"", b"failure" if self.returncode else b""

    # kill(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def kill(self) -> None:
        # self.killed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.killed = True
        # 오른쪽 식을 계산한 값을 self.returncode에 대입합니다.
        self.returncode = -1


# FakeFactory: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeFactory:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: process.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, process: FakeProcess) -> None:
        # 오른쪽 식을 계산한 값을 self.process에 대입합니다.
        self.process = process
        # self.args에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        self.args: Sequence[str] = ()
        # self.environment에 딕셔너리(키와 값의 쌍)을 대입합니다.
        self.environment: Mapping[str, str] = {}

    # __call__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, stdin, stdout, stderr, env, creationflags.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: FakeProcess.
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
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del stdin, stdout, stderr, creationflags
        # 오른쪽 식을 계산한 값을 self.args에 대입합니다.
        self.args = args
        # 오른쪽 식을 계산한 값을 self.environment에 대입합니다.
        self.environment = env
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.process


# BlockingProcess: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: FakeProcess.
class BlockingProcess(FakeProcess):
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self) -> None:
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__()
        # self.returncode을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self.returncode = None
        # Event()의 반환값을 self.started에 대입합니다.
        self.started = Event()
        # Event()의 반환값을 self.released에 대입합니다.
        self.released = Event()

    # communicate(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: input, timeout.
    # 반환 타입 힌트: tuple[bytes, bytes].
    def communicate(self, input: bytes, timeout: float | None = None) -> tuple[bytes, bytes]:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del timeout
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        self.input += input
        # self.started.set()을 호출해 작업을 수행합니다.
        self.started.set()
        # self.released.wait()을 호출해 작업을 수행합니다.
        self.released.wait(timeout=2)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return b"", b""

    # kill(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def kill(self) -> None:
        # super().kill()을 호출해 작업을 수행합니다.
        super().kill()
        # self.released.set()을 호출해 작업을 수행합니다.
        self.released.set()


# masker(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: LogMasker.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def masker(tmp_path: Path) -> LogMasker:
    from scripts.bootstrap import create_tree

    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)
    # load_config()의 반환값을 config에 대입합니다.
    config = load_config(
        _copy_config(tmp_path, root)
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return LogMasker.from_policy(config.policies.privacy)


# _copy_config(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path, root.
# 반환 타입 힌트: Path.
def _copy_config(tmp_path: Path, root: Path) -> Path:
    import shutil

    import yaml

    # 오른쪽 식을 계산한 값을 destination에 대입합니다.
    destination = tmp_path / "config"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    destination.mkdir()
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("settings", "tools", "privacy"):
        # shutil.copyfile()을 호출해 작업을 수행합니다.
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )
    # 오른쪽 식을 계산한 값을 settings에 대입합니다.
    settings = destination / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings.read_text(encoding="utf-8"))
    # str()의 반환값을 document['paths']['data_root']에 대입합니다.
    document["paths"]["data_root"] = str(root)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return destination


# pytest가 test_sapi_receives_utf8_text_via_stdin_not_command_line()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_sapi_receives_utf8_text_via_stdin_not_command_line() -> None:
    # FakeProcess()의 반환값을 process에 대입합니다.
    process = FakeProcess()
    # FakeFactory()의 반환값을 factory에 대입합니다.
    factory = FakeFactory(process)
    # WindowsSapiTTS()의 반환값을 tts에 대입합니다.
    tts = WindowsSapiTTS("Microsoft Heami Desktop", process_factory=factory)

    # tts.speak()을 호출해 작업을 수행합니다.
    tts.speak("무엇을 도와드릴까요.")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert process.input.decode("utf-8") == "무엇을 도와드릴까요."
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all("무엇을" not in argument for argument in factory.args)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert factory.environment["JARVIS_TTS_VOICE"] == "Microsoft Heami Desktop"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert factory.environment["JARVIS_TTS_RATE"] == "4"


# pytest가 test_sapi_rejects_rate_outside_windows_range()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: rate.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("rate", [-11, 11])
def test_sapi_rejects_rate_outside_windows_range(rate: int) -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="rate"):
        # WindowsSapiTTS()을 호출해 작업을 수행합니다.
        WindowsSapiTTS("Microsoft Heami Desktop", rate=rate)


# pytest가 test_high_risk_private_text_is_never_spoken()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: masker.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_high_risk_private_text_is_never_spoken(masker: LogMasker) -> None:
    # prepare_speech()의 반환값을 prepared에 대입합니다.
    prepared = prepare_speech("주민번호는 900101-1234567입니다", masker=masker, max_chars=400)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert prepared.refused is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "900101" not in prepared.text
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert prepared.text == "민감한 내용이 포함되어 화면으로만 표시합니다."


# pytest가 test_long_speech_is_limited()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: masker.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_long_speech_is_limited(masker: LogMasker) -> None:
    # prepare_speech()의 반환값을 prepared에 대입합니다.
    prepared = prepare_speech("가" * 500, masker=masker, max_chars=20)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert prepared.truncated is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert prepared.text == "내용이 길어 화면에서 확인해 주세요."
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "화면" in prepared.text


# pytest가 test_sapi_failure_does_not_expose_text()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_sapi_failure_does_not_expose_text() -> None:
    from app.core.errors import JarvisError

    # WindowsSapiTTS()의 반환값을 tts에 대입합니다.
    tts = WindowsSapiTTS(
        "Microsoft Heami Desktop", process_factory=FakeFactory(FakeProcess(returncode=1))
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(JarvisError) as captured:
        # tts.speak()을 호출해 작업을 수행합니다.
        tts.speak("비밀 응답")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "비밀 응답" not in str(captured.value)


# pytest가 test_cancel_kills_active_sapi_process()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cancel_kills_active_sapi_process() -> None:
    # BlockingProcess()의 반환값을 process에 대입합니다.
    process = BlockingProcess()
    # WindowsSapiTTS()의 반환값을 tts에 대입합니다.
    tts = WindowsSapiTTS("Microsoft Heami Desktop", process_factory=FakeFactory(process))
    # errors에 리스트(순서가 있고 수정 가능)을 대입합니다.
    errors: list[BaseException] = []

    # speak(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def speak() -> None:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # tts.speak()을 호출해 작업을 수행합니다.
            tts.speak("긴 답변")
        # BaseException를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except BaseException as error:
            # 리스트 끝에 항목 하나를 추가합니다.
            errors.append(error)

    # Thread()의 반환값을 worker에 대입합니다.
    worker = Thread(target=speak)
    # worker.start()을 호출해 작업을 수행합니다.
    worker.start()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert process.started.wait(timeout=1)

    # tts.cancel()을 호출해 작업을 수행합니다.
    tts.cancel()
    # join을 호출합니다. 문자열에서는 조각 결합, 스레드에서는 종료 대기를 뜻합니다.
    worker.join(timeout=1)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not worker.is_alive()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert process.killed is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(errors) == 1
