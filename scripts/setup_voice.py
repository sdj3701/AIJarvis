# 파이썬 공부 | scripts/setup_voice.py
# 로컬 음성 인식에 필요한 모델을 다운로드하고 준비합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Download the pinned offline Korean wake-word and question STT models."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

from app.config.defaults import DEFAULT_DATA_ROOT

# MODEL_NAME에 문자열을 대입합니다.
MODEL_NAME = "vosk-model-small-ko-0.22"
# 오른쪽 식을 계산한 값을 MODEL_URL에 대입합니다.
# f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
# MODEL_SHA256에 문자열을 대입합니다.
MODEL_SHA256 = "eea36124087fed26c59996a4761519458e3bd185e8ea9d9865ad8760c4a1d989"
# 오른쪽 식을 계산한 값을 DEFAULT_MODELS_DIR에 대입합니다.
DEFAULT_MODELS_DIR = DEFAULT_DATA_ROOT / "models"
# REQUIRED_FILES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
REQUIRED_FILES = (Path("am/final.mdl"), Path("conf/model.conf"), Path("graph/HCLr.fst"))
# WHISPER_REPO_ID에 문자열을 대입합니다.
WHISPER_REPO_ID = "Systran/faster-whisper-small"
# WHISPER_REVISION에 문자열을 대입합니다.
WHISPER_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
# WHISPER_MODEL_NAME에 문자열을 대입합니다.
WHISPER_MODEL_NAME = "faster-whisper-small"
# WHISPER_MODEL_SHA256에 문자열을 대입합니다.
WHISPER_MODEL_SHA256 = "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"
# WHISPER_REQUIRED_FILES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
WHISPER_REQUIRED_FILES = (
    Path("config.json"),
    Path("model.bin"),
    Path("tokenizer.json"),
    Path("vocabulary.txt"),
)


# _parser(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: argparse.ArgumentParser.
def _parser() -> argparse.ArgumentParser:
    # argparse.ArgumentParser()의 반환값을 parser에 대입합니다.
    parser = argparse.ArgumentParser(description="Jarvis 로컬 한국어 음성 모델 설치")
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--skip-vosk", action="store_true", help="Vosk 호출어 모델 설치 생략")
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument(
        "--skip-whisper", action="store_true", help="faster-whisper 질문 모델 설치 생략"
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parser


# _sha256(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 문자열(str).
def _sha256(path: Path) -> str:
    # hashlib.sha256()의 반환값을 digest에 대입합니다.
    digest = hashlib.sha256()
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with path.open("rb") as source:
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while chunk := source.read(1024 * 1024):
            # digest.update()을 호출해 작업을 수행합니다.
            digest.update(chunk)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return digest.hexdigest()


# _valid_model(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 참/거짓(bool).
def _valid_model(path: Path) -> bool:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return all((path / relative).is_file() for relative in REQUIRED_FILES)


# _download(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: archive.
# 반환 타입 힌트: 별도 결과 없음(None).
def _download(archive: Path) -> None:
    # archive.with_suffix()의 반환값을 temporary에 대입합니다.
    temporary = archive.with_suffix(".zip.download")
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with (
            urllib.request.urlopen(MODEL_URL, timeout=60) as response,
            temporary.open("wb") as output,
        ):
            # shutil.copyfileobj()을 호출해 작업을 수행합니다.
            shutil.copyfileobj(response, output, length=1024 * 1024)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _sha256(temporary) != MODEL_SHA256.
        if _sha256(temporary) != MODEL_SHA256:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RuntimeError("다운로드한 음성 모델의 SHA-256이 고정값과 다릅니다.")
        # os.replace()을 호출해 작업을 수행합니다.
        os.replace(temporary, archive)
    # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
    finally:
        # 지정한 파일 또는 링크를 삭제합니다.
        temporary.unlink(missing_ok=True)


# _safe_extract(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: archive, models_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def _safe_extract(archive: Path, models_dir: Path) -> None:
    # models_dir.resolve()의 반환값을 root에 대입합니다.
    root = models_dir.resolve(strict=True)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with zipfile.ZipFile(archive) as package:
        # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
        for item in package.infolist():
            # (root / item.filename).resolve()의 반환값을 destination에 대입합니다.
            destination = (root / item.filename).resolve(strict=False)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not
            # destination.is_relative_to(root).
            if not destination.is_relative_to(root):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise RuntimeError("음성 모델 압축 파일에 잘못된 경로가 있습니다.")
        # package.extractall()을 호출해 작업을 수행합니다.
        package.extractall(root)


# install(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: models_dir.
# 반환 타입 힌트: Path.
def install(models_dir: Path) -> Path:
    # models_dir.resolve()의 반환값을 root에 대입합니다.
    root = models_dir.resolve(strict=False)
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    root.mkdir(parents=True, exist_ok=True)
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = root / MODEL_NAME
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _valid_model(target).
    if _valid_model(target):
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return target
    # 오른쪽 식을 계산한 값을 archive에 대입합니다.
    archive = root / f"{MODEL_NAME}.zip"
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not archive.is_file().
    if not archive.is_file():
        # _download()을 호출해 작업을 수행합니다.
        _download(archive)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _sha256(archive) != MODEL_SHA256.
    if _sha256(archive) != MODEL_SHA256:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError("음성 모델 압축 파일의 SHA-256이 고정값과 다릅니다.")
    # _safe_extract()을 호출해 작업을 수행합니다.
    _safe_extract(archive, root)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not _valid_model(target).
    if not _valid_model(target):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError("음성 모델 필수 파일이 누락되었습니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return target


# install_whisper(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: models_dir.
# 반환 타입 힌트: Path.
def install_whisper(models_dir: Path) -> Path:
    """Install the exact faster-whisper snapshot without using a floating model name."""
    # models_dir.resolve()의 반환값을 root에 대입합니다.
    root = models_dir.resolve(strict=False)
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    root.mkdir(parents=True, exist_ok=True)
    # 오른쪽 식을 계산한 값을 target에 대입합니다.
    target = root / WHISPER_MODEL_NAME
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if all((target / relative).is_file() for relative in WHISPER_REQUIRED_FILES):
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _sha256(target / 'model.bin') !=
        # WHISPER_MODEL_SHA256.
        if _sha256(target / "model.bin") != WHISPER_MODEL_SHA256:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RuntimeError("Whisper model.bin의 SHA-256이 고정값과 다릅니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return target

    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        from huggingface_hub import snapshot_download
    # ImportError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ImportError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError(
            'Whisper 설치 도구가 없습니다. python -m pip install -e ".[voice]"를 실행하세요.'
        ) from error

    # snapshot_download()을 호출해 작업을 수행합니다.
    snapshot_download(
        repo_id=WHISPER_REPO_ID,
        revision=WHISPER_REVISION,
        local_dir=target,
        ignore_patterns=["*.md", ".gitattributes"],
    )
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if not all((target / relative).is_file() for relative in WHISPER_REQUIRED_FILES):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError("Whisper 모델 필수 파일이 누락되었습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _sha256(target / 'model.bin') !=
    # WHISPER_MODEL_SHA256.
    if _sha256(target / "model.bin") != WHISPER_MODEL_SHA256:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError("Whisper model.bin의 SHA-256이 고정값과 다릅니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return target


# main(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: argv.
# 반환 타입 힌트: 정수(int).
def main(argv: list[str] | None = None) -> int:
    # _parser().parse_args()의 반환값을 arguments에 대입합니다.
    arguments = _parser().parse_args(argv)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not arguments.skip_vosk.
    if not arguments.skip_vosk:
        # install()의 반환값을 target에 대입합니다.
        target = install(arguments.models_dir)
        # 값을 텍스트로 출력합니다.
        print(f"호출어 모델 준비 완료: {target}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not arguments.skip_whisper.
    if not arguments.skip_whisper:
        # install_whisper()의 반환값을 target에 대입합니다.
        target = install_whisper(arguments.models_dir)
        # 값을 텍스트로 출력합니다.
        print(f"질문 인식 모델 준비 완료: {target}")
    # 0을 반환하고 이 함수의 실행을 끝냅니다.
    return 0


# 이 파일을 실행 진입점으로 사용할 때만 아래 코드를 실행합니다. import할 때는 실행하지 않습니다.
if __name__ == "__main__":
    # SystemExit 예외로 프로그램 종료를 요청합니다. 전달한 값은 종료 상태를 나타냅니다.
    raise SystemExit(main())
