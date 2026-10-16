"""Download the pinned offline Korean wake-word and question STT models."""

# [파일 역할] Vosk 호출어 모델과 Whisper 질문 인식 모델을 지정한 폴더에 설치한다.
# STT(Speech To Text)는 음성 → 글자 변환이다. 이 파일은 음성을 직접 인식하지 않고
# 인식에 필요한 모델 파일을 준비한다. 설치 과정에는 네트워크가 필요할 수 있다.
# 실행 흐름: main() → 옵션 확인 → install()/install_whisper() → 경로 출력.
# 프로젝트 루트에서 `python -m scripts.setup_voice --help`로 옵션을 읽을 수 있다.
# 이 파일은 sys.path를 직접 수정하지 않으므로 -m 방식이면 프로젝트의 app을 찾기 쉽다.
# 학습 포인트: bytes, :=, 생성기, 해시, 임시 파일, finally, 압축 경로 확인.
from __future__ import annotations

# argparse: 명령줄 옵션 / hashlib: 내용의 해시 계산 / os: 파일 교체.
# shutil: 파일 스트림 복사 / urllib.request: URL에서 다운로드 / zipfile: ZIP 처리.
# Path는 운영체제별 경로 문자열을 직접 이어 붙이지 않고 파일을 다루게 해 준다.
import argparse
import hashlib
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

# 기본 저장 위치는 app의 공통 설정에서 가져와 다른 기능과 같은 기준을 사용한다.
from app.config.defaults import DEFAULT_DATA_ROOT

# 대문자는 상수 이름 관례다. URL의 f-string에는 MODEL_NAME 값이 들어간다.
# SHA-256은 파일 내용으로 계산하는 64자리 16진수 해시이며 암호화가 아니다.
# 다운로드 결과를 미리 정해 둔 해시와 비교해 예상한 파일인지 확인한다.
MODEL_NAME = "vosk-model-small-ko-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_SHA256 = "eea36124087fed26c59996a4761519458e3bd185e8ea9d9865ad8760c4a1d989"
DEFAULT_MODELS_DIR = DEFAULT_DATA_ROOT / "models"
# 모델이 갖춰야 할 상대 경로 목록이다. 나중에 모델 폴더와 / 연산으로 연결한다.
REQUIRED_FILES = (Path("am/final.mdl"), Path("conf/model.conf"), Path("graph/HCLr.fst"))
# revision은 특정 저장소 버전을 지정한다. 같은 이름의 최신 모델로 임의 변경되지 않게 한다.
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
    # type=Path는 문자열 입력을 경로 객체로 바꾸고 default는 옵션이 없을 때 적용한다.
    parser = argparse.ArgumentParser(description="Jarvis 로컬 한국어 음성 모델 설치")
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    # store_true는 별도의 값 없이 옵션 존재 여부를 bool로 받는다.
    # 옵션의 -는 속성명에서는 _가 된다. --skip-vosk → arguments.skip_vosk.
    parser.add_argument("--skip-vosk", action="store_true", help="Vosk 호출어 모델 설치 생략")
    parser.add_argument(
        "--skip-whisper", action="store_true", help="faster-whisper 질문 모델 설치 생략"
    )
    return parser


def _sha256(path: Path) -> str:
    # 큰 파일을 한 번에 메모리에 올리지 않고 조각(chunk) 단위로 읽어 해시를 누적한다.
    digest = hashlib.sha256()
    with path.open("rb") as source:
        # rb는 바이너리 읽기다. :=는 값을 변수에 넣으면서 그 값을 조건식에 사용한다.
        # 1024 * 1024는 1 MiB. 파일 끝에서 read()가 b''를 반환하면 반복이 끝난다.
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    # digest()는 bytes를, hexdigest()는 사람이 비교하기 쉬운 16진수 문자열을 반환한다.
    return digest.hexdigest()


def _valid_model(path: Path) -> bool:
    # all은 모든 결과가 True일 때 True다. False를 만나면 남은 항목은 평가하지 않는다.
    # 괄호 안의 for는 생성기 표현식으로, 검사 결과를 필요할 때 하나씩 만든다.
    # 여기서는 필수 파일의 존재만 확인한다. 개별 파일의 내용까지 검증하는 함수는 아니다.
    return all((path / relative).is_file() for relative in REQUIRED_FILES)


def _download(archive: Path) -> None:
    # 완성된 ZIP과 다운로드 중인 파일을 구분한다. 예: model.zip → model.zip.download.
    temporary = archive.with_suffix(".zip.download")
    try:
        # with (...) 안에 여러 자원을 열면 블록을 벗어날 때 각각 정리한다.
        # urlopen은 네트워크 응답을 열고, wb는 바이너리 쓰기(기존 파일이면 덮어쓰기)다.
        # timeout=60은 소켓 작업의 제한 시간이며 전체 다운로드가 60초라는 뜻은 아니다.
        with (
            urllib.request.urlopen(MODEL_URL, timeout=60) as response,
            temporary.open("wb") as output,
        ):
            # 응답 데이터를 파일로 복사한다. length는 복사에 사용할 버퍼 크기다.
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if _sha256(temporary) != MODEL_SHA256:
            raise RuntimeError("다운로드한 음성 모델의 SHA-256이 고정값과 다릅니다.")
        # 해시가 맞는 완성된 파일만 최종 이름으로 교체한다.
        os.replace(temporary, archive)
    finally:
        # 성공/실패 모두에서 정리한다. 이미 replace로 이동했다면 missing_ok가 허용한다.
        temporary.unlink(missing_ok=True)


def _safe_extract(archive: Path, models_dir: Path) -> None:
    # strict=True는 대상 폴더가 실제로 있어야 한다는 뜻이다.
    root = models_dir.resolve(strict=True)
    with zipfile.ZipFile(archive) as package:
        # ZIP 내부 항목마다 최종 경로를 계산해 폴더 밖으로 나가는지 검사한다.
        # 예를 들어 ../../outside.txt 같은 경로를 그대로 풀지 않도록 하는 검사다.
        for item in package.infolist():
            # 추출 전이라 파일이 없어도 경로를 계산할 수 있도록 strict=False를 쓴다.
            destination = (root / item.filename).resolve(strict=False)
            if not destination.is_relative_to(root):
                raise RuntimeError("음성 모델 압축 파일에 잘못된 경로가 있습니다.")
        # 모든 항목의 경로 검사가 끝난 다음에 실제 압축을 해제한다.
        package.extractall(root)


def install(models_dir: Path) -> Path:
    # Vosk 설치 순서: 폴더 준비 → 기존 모델 확인 → ZIP 확보 → 해시 확인 → 압축 해제.
    root = models_dir.resolve(strict=False)
    # parents=True는 중간 폴더 생성, exist_ok=True는 이미 있는 폴더 허용이다.
    root.mkdir(parents=True, exist_ok=True)
    target = root / MODEL_NAME
    if _valid_model(target):
        # 필수 파일이 이미 있으면 조기 반환한다. 이 경로에서는 해시 재검사를 하지 않는다.
        return target
    archive = root / f"{MODEL_NAME}.zip"
    if not archive.is_file():
        _download(archive)
    # 새로 받았든 기존 ZIP을 재사용하든 압축을 풀기 전에 해시를 확인한다.
    if _sha256(archive) != MODEL_SHA256:
        raise RuntimeError("음성 모델 압축 파일의 SHA-256이 고정값과 다릅니다.")
    _safe_extract(archive, root)
    # 다운로드 파일 검증과 모델 폴더 구성 검증은 각각 별도로 수행한다.
    if not _valid_model(target):
        raise RuntimeError("음성 모델 필수 파일이 누락되었습니다.")
    return target


def install_whisper(models_dir: Path) -> Path:
    """Install the exact faster-whisper snapshot without using a floating model name."""
    # Whisper는 ZIP URL 대신 Hugging Face 저장소의 고정 revision을 다운로드한다.
    root = models_dir.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    target = root / WHISPER_MODEL_NAME
    if all((target / relative).is_file() for relative in WHISPER_REQUIRED_FILES):
        # 기존 모델도 model.bin의 내용을 해시로 확인한 후 재사용한다.
        if _sha256(target / "model.bin") != WHISPER_MODEL_SHA256:
            raise RuntimeError("Whisper model.bin의 SHA-256이 고정값과 다릅니다.")
        return target

    try:
        # 이 기능이 필요할 때만 외부 패키지를 import한다. Vosk만 설치할 수도 있기 때문.
        from huggingface_hub import snapshot_download
    except ImportError as error:
        # 라이브러리가 없으면 설치 방법이 포함된 예외로 바꾼다.
        # from error는 원래 ImportError를 연결해 디버깅할 때 원인을 추적할 수 있게 한다.
        raise RuntimeError(
            'Whisper 설치 도구가 없습니다. python -m pip install -e ".[voice]"를 실행하세요.'
        ) from error

    # repo_id=저장소, revision=고정 버전, local_dir=설치 위치.
    # ignore_patterns는 여기서 필요 없는 문서와 Git 속성 파일을 제외한다.
    snapshot_download(
        repo_id=WHISPER_REPO_ID,
        revision=WHISPER_REVISION,
        local_dir=target,
        ignore_patterns=["*.md", ".gitattributes"],
    )
    # 다운로드 함수가 반환됐더라도 필수 파일과 핵심 모델 해시는 직접 확인한다.
    if not all((target / relative).is_file() for relative in WHISPER_REQUIRED_FILES):
        raise RuntimeError("Whisper 모델 필수 파일이 누락되었습니다.")
    if _sha256(target / "model.bin") != WHISPER_MODEL_SHA256:
        raise RuntimeError("Whisper model.bin의 SHA-256이 고정값과 다릅니다.")
    return target


def main(argv: list[str] | None = None) -> int:
    # argv는 테스트용 입력 목록도 받을 수 있다. None이면 실제 터미널 인수를 해석한다.
    arguments = _parser().parse_args(argv)
    # not은 True/False를 반대로 만든다. '건너뛰기'가 False일 때 설치한다.
    if not arguments.skip_vosk:
        target = install(arguments.models_dir)
        print(f"호출어 모델 준비 완료: {target}")
    if not arguments.skip_whisper:
        # elif가 아닌 별개의 if이므로 기본 실행에서는 두 모델을 차례로 설치한다.
        target = install_whisper(arguments.models_dir)
        print(f"질문 인식 모델 준비 완료: {target}")
    return 0


# 직접 실행 시 main을 호출하고, 그 결과 0을 정상 종료 코드로 전달한다.
# 처리하지 않은 예외가 나면 main의 return 0까지 도달하지 않고 실패로 종료한다.
if __name__ == "__main__":
    raise SystemExit(main())
