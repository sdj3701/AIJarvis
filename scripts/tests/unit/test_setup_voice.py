# 파이썬 공부 | scripts/tests/unit/test_setup_voice.py
# setup_voice 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.

"""Tests for deterministic local voice-model setup."""

from pathlib import Path

import pytest

from scripts import setup_voice

# pytest.importorskip()의 반환값을 huggingface_hub에 대입합니다.
huggingface_hub = pytest.importorskip("huggingface_hub")


# _write_required_model_files(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: target.
# 반환 타입 힌트: 별도 결과 없음(None).
def _write_required_model_files(target: Path) -> None:
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    target.mkdir(parents=True, exist_ok=True)
    # for 반복문: 대상의 항목을 하나씩 relative에 대입하며 아래 블록을 실행합니다.
    for relative in setup_voice.WHISPER_REQUIRED_FILES:
        # 오른쪽 식을 계산한 값을 path에 대입합니다.
        path = target / relative
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        path.parent.mkdir(parents=True, exist_ok=True)
        # 바이트 데이터를 파일에 기록합니다.
        path.write_bytes(b"test")


# pytest가 test_install_whisper_downloads_exact_revision()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path, monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_install_whisper_downloads_exact_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # received에 딕셔너리(키와 값의 쌍)을 대입합니다.
    received: dict[str, object] = {}

    # fake_snapshot_download(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
    # 반환 타입 힌트: 문자열(str).
    def fake_snapshot_download(**kwargs: object) -> str:
        # received.update()을 호출해 작업을 수행합니다.
        received.update(kwargs)
        # Path()의 반환값을 target에 대입합니다.
        target = Path(str(kwargs["local_dir"]))
        # _write_required_model_files()을 호출해 작업을 수행합니다.
        _write_required_model_files(target)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return str(target)

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(setup_voice, "_sha256", lambda _path: setup_voice.WHISPER_MODEL_SHA256)

    # setup_voice.install_whisper()의 반환값을 target에 대입합니다.
    target = setup_voice.install_whisper(tmp_path)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert target == tmp_path / setup_voice.WHISPER_MODEL_NAME
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert received["repo_id"] == setup_voice.WHISPER_REPO_ID
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert received["revision"] == setup_voice.WHISPER_REVISION
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert received["local_dir"] == target


# pytest가 test_install_whisper_rejects_wrong_model_hash()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path, monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_install_whisper_rejects_wrong_model_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = tmp_path / setup_voice.WHISPER_MODEL_NAME
    # _write_required_model_files()을 호출해 작업을 수행합니다.
    _write_required_model_files(target)
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(setup_voice, "_sha256", lambda _path: "0" * 64)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(RuntimeError, match="SHA-256"):
        # setup_voice.install_whisper()을 호출해 작업을 수행합니다.
        setup_voice.install_whisper(tmp_path)
