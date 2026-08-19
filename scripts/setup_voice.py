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

MODEL_NAME = "vosk-model-small-ko-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_SHA256 = "eea36124087fed26c59996a4761519458e3bd185e8ea9d9865ad8760c4a1d989"
DEFAULT_MODELS_DIR = DEFAULT_DATA_ROOT / "models"
REQUIRED_FILES = (Path("am/final.mdl"), Path("conf/model.conf"), Path("graph/HCLr.fst"))
WHISPER_REPO_ID = "Systran/faster-whisper-small"
WHISPER_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
WHISPER_MODEL_NAME = "faster-whisper-small"
WHISPER_MODEL_SHA256 = "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"
WHISPER_REQUIRED_FILES = (
    Path("config.json"),
    Path("model.bin"),
    Path("tokenizer.json"),
    Path("vocabulary.txt"),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis 로컬 한국어 음성 모델 설치")
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--skip-vosk", action="store_true", help="Vosk 호출어 모델 설치 생략")
    parser.add_argument(
        "--skip-whisper", action="store_true", help="faster-whisper 질문 모델 설치 생략"
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_model(path: Path) -> bool:
    return all((path / relative).is_file() for relative in REQUIRED_FILES)


def _download(archive: Path) -> None:
    temporary = archive.with_suffix(".zip.download")
    try:
        with (
            urllib.request.urlopen(MODEL_URL, timeout=60) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if _sha256(temporary) != MODEL_SHA256:
            raise RuntimeError("다운로드한 음성 모델의 SHA-256이 고정값과 다릅니다.")
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_extract(archive: Path, models_dir: Path) -> None:
    root = models_dir.resolve(strict=True)
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            destination = (root / item.filename).resolve(strict=False)
            if not destination.is_relative_to(root):
                raise RuntimeError("음성 모델 압축 파일에 잘못된 경로가 있습니다.")
        package.extractall(root)


def install(models_dir: Path) -> Path:
    root = models_dir.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    target = root / MODEL_NAME
    if _valid_model(target):
        return target
    archive = root / f"{MODEL_NAME}.zip"
    if not archive.is_file():
        _download(archive)
    if _sha256(archive) != MODEL_SHA256:
        raise RuntimeError("음성 모델 압축 파일의 SHA-256이 고정값과 다릅니다.")
    _safe_extract(archive, root)
    if not _valid_model(target):
        raise RuntimeError("음성 모델 필수 파일이 누락되었습니다.")
    return target


def install_whisper(models_dir: Path) -> Path:
    """Install the exact faster-whisper snapshot without using a floating model name."""
    root = models_dir.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    target = root / WHISPER_MODEL_NAME
    if all((target / relative).is_file() for relative in WHISPER_REQUIRED_FILES):
        if _sha256(target / "model.bin") != WHISPER_MODEL_SHA256:
            raise RuntimeError("Whisper model.bin의 SHA-256이 고정값과 다릅니다.")
        return target

    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError(
            'Whisper 설치 도구가 없습니다. python -m pip install -e ".[voice]"를 실행하세요.'
        ) from error

    snapshot_download(
        repo_id=WHISPER_REPO_ID,
        revision=WHISPER_REVISION,
        local_dir=target,
        ignore_patterns=["*.md", ".gitattributes"],
    )
    if not all((target / relative).is_file() for relative in WHISPER_REQUIRED_FILES):
        raise RuntimeError("Whisper 모델 필수 파일이 누락되었습니다.")
    if _sha256(target / "model.bin") != WHISPER_MODEL_SHA256:
        raise RuntimeError("Whisper model.bin의 SHA-256이 고정값과 다릅니다.")
    return target


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.skip_vosk:
        target = install(arguments.models_dir)
        print(f"호출어 모델 준비 완료: {target}")
    if not arguments.skip_whisper:
        target = install_whisper(arguments.models_dir)
        print(f"질문 인식 모델 준비 완료: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
