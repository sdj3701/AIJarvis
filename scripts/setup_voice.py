"""Download and verify the pinned offline Korean Vosk model."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

MODEL_NAME = "vosk-model-small-ko-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_SHA256 = "eea36124087fed26c59996a4761519458e3bd185e8ea9d9865ad8760c4a1d989"
DEFAULT_MODELS_DIR = Path(r"D:\Jarvis\models")
REQUIRED_FILES = (Path("am/final.mdl"), Path("conf/model.conf"), Path("graph/HCLr.fst"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis 로컬 한국어 음성 모델 설치")
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
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


def main(argv: list[str] | None = None) -> int:
    target = install(_parser().parse_args(argv).models_dir)
    print(f"음성 모델 준비 완료: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
