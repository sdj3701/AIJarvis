# 파이썬 공부 | scripts/bootstrap.py
# 앱에 필요한 데이터 폴더와 SQLite 데이터베이스를 준비합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Create the Jarvis data tree and initialize its SQLite database."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: str(REPOSITORY_ROOT) not in sys.path.
if str(REPOSITORY_ROOT) not in sys.path:
    # sys.path.insert()을 호출해 작업을 수행합니다.
    sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from app.config.defaults import DEFAULT_DATA_ROOT  # noqa: E402
from app.core.errors import ConfigError, JarvisError, exit_code_for  # noqa: E402
from app.memory.migrations import initialize_database  # noqa: E402

# 오른쪽 식을 계산한 값을 DEFAULT_CONFIG_SOURCE에 대입합니다.
DEFAULT_CONFIG_SOURCE = REPOSITORY_ROOT / "config"
# 오른쪽 식을 계산한 값을 DEFAULT_MIN_FREE_BYTES에 대입합니다.
DEFAULT_MIN_FREE_BYTES = 5 * 1024**3

# TREE_DIRECTORIES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
TREE_DIRECTORIES = (
    "config",
    "memory/raw",
    "memory/export",
    "docs/notes",
    "skills",
    "state/quarantine",
    "logs",
    "models",
    "backups",
)
# CONFIG_COPIES에 딕셔너리(키와 값의 쌍)을 대입합니다.
CONFIG_COPIES = {
    "settings.example.yaml": "settings.yaml",
    "privacy.example.yaml": "privacy.yaml",
    "tools.example.yaml": "tools.yaml",
}


# BootstrapAction: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class BootstrapAction:
    # kind: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    kind: str
    # status: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    status: str
    # target: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    target: Path


# BootstrapReport: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class BootstrapReport:
    # data_root: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    data_root: Path
    # database_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    database_path: Path
    # free_bytes: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    free_bytes: int
    # actions: tuple[BootstrapAction, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    actions: tuple[BootstrapAction, ...]


# create_tree(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data_root.
# 반환 타입 힌트: tuple[BootstrapAction, ...].
def create_tree(data_root: Path) -> tuple[BootstrapAction, ...]:
    """Create all required directories, reporting existing paths as skipped."""
    # actions에 리스트(순서가 있고 수정 가능)을 대입합니다.
    actions: list[BootstrapAction] = []
    # for 반복문: 대상의 항목을 하나씩 relative에 대입하며 아래 블록을 실행합니다.
    for relative in TREE_DIRECTORIES:
        # 오른쪽 식을 계산한 값을 target에 대입합니다.
        target = data_root / Path(relative)
        # target.is_dir()의 반환값을 existed에 대입합니다.
        existed = target.is_dir()
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        target.mkdir(parents=True, exist_ok=True)
        # 리스트 끝에 항목 하나를 추가합니다.
        actions.append(BootstrapAction("directory", "skipped" if existed else "created", target))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return tuple(actions)


# _copy_initial_configs(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data_root, source.
# 반환 타입 힌트: tuple[BootstrapAction, ...].
def _copy_initial_configs(data_root: Path, source: Path) -> tuple[BootstrapAction, ...]:
    # actions에 리스트(순서가 있고 수정 가능)을 대입합니다.
    actions: list[BootstrapAction] = []
    # for 반복문: 대상의 항목을 하나씩 (source_name, target_name)에 대입하며 아래 블록을
    # 실행합니다.
    for source_name, target_name in CONFIG_COPIES.items():
        # 오른쪽 식을 계산한 값을 source_path에 대입합니다.
        source_path = source / source_name
        # 오른쪽 식을 계산한 값을 target_path에 대입합니다.
        target_path = data_root / "config" / target_name
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not source_path.is_file().
        if not source_path.is_file():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ConfigError("초기 설정 원본 파일이 없습니다.", {"source": str(source_path)})
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # "xb" creates the file only when missing so a rerun cannot clobber live config.
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with source_path.open("rb") as input_file, target_path.open("xb") as output_file:
                # shutil.copyfileobj()을 호출해 작업을 수행합니다.
                shutil.copyfileobj(input_file, output_file)
        # FileExistsError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except FileExistsError:
            # 리스트 끝에 항목 하나를 추가합니다.
            actions.append(BootstrapAction("config", "skipped", target_path))
        else:
            # 리스트 끝에 항목 하나를 추가합니다.
            actions.append(BootstrapAction("config", "copied", target_path))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return tuple(actions)


# _verify_writable(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data_root.
# 반환 타입 힌트: 별도 결과 없음(None).
def _verify_writable(data_root: Path) -> None:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".bootstrap-write-", dir=data_root / "state", delete=False
        ) as probe:
            # 열린 출력 대상에 데이터를 기록합니다.
            probe.write(b"ok")
            # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
            probe.flush()
            # 운영체제에 파일 내용을 저장 장치로 동기화하도록 요청합니다.
            os.fsync(probe.fileno())
            # Path()의 반환값을 probe_path에 대입합니다.
            probe_path = Path(probe.name)
        # 지정한 파일 또는 링크를 삭제합니다.
        probe_path.unlink()
    # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except OSError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "데이터 루트에 쓸 수 없습니다.",
            {"data_root": str(data_root), "error_type": type(error).__name__},
        ) from error


# bootstrap(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data_root, config_source, min_free_bytes.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: BootstrapReport.
def bootstrap(
    data_root: Path = DEFAULT_DATA_ROOT,
    *,
    config_source: Path = DEFAULT_CONFIG_SOURCE,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
) -> BootstrapReport:
    """Run the complete idempotent bootstrap sequence."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: min_free_bytes < 0.
    if min_free_bytes < 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("min_free_bytes must be non-negative")
    # list()의 반환값을 actions에 대입합니다.
    actions = list(create_tree(data_root))
    # _verify_writable()을 호출해 작업을 수행합니다.
    _verify_writable(data_root)
    # 오른쪽 식을 계산한 값을 free_bytes에 대입합니다.
    free_bytes = shutil.disk_usage(data_root).free
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: free_bytes < min_free_bytes.
    if free_bytes < min_free_bytes:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "데이터 저장 공간이 부족합니다.",
            {"required_bytes": min_free_bytes, "free_bytes": free_bytes},
        )
    # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
    actions.extend(_copy_initial_configs(data_root, config_source))

    # 오른쪽 식을 계산한 값을 database_path에 대입합니다.
    database_path = data_root / "memory" / "jarvis.sqlite3"
    # initialize_database()의 반환값을 database_result에 대입합니다.
    database_result = initialize_database(database_path)
    # 리스트 끝에 항목 하나를 추가합니다.
    actions.append(
        BootstrapAction(
            "database", "created" if database_result.created else "verified", database_path
        )
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return BootstrapReport(data_root, database_path, free_bytes, tuple(actions))


# _parser(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: argparse.ArgumentParser.
def _parser() -> argparse.ArgumentParser:
    # argparse.ArgumentParser()의 반환값을 parser에 대입합니다.
    parser = argparse.ArgumentParser(description="Jarvis 데이터 폴더와 DB를 초기화합니다.")
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=DEFAULT_MIN_FREE_BYTES / 1024**3,
        help="필요한 최소 여유 공간(GB)",
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parser


# main(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: argv.
# 반환 타입 힌트: 정수(int).
def main(argv: list[str] | None = None) -> int:
    # _parser().parse_args()의 반환값을 args에 대입합니다.
    args = _parser().parse_args(argv)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.min_free_gb < 0.
    if args.min_free_gb < 0:
        # _parser().error()을 호출해 작업을 수행합니다.
        _parser().error("--min-free-gb는 0 이상이어야 합니다.")
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # bootstrap()의 반환값을 report에 대입합니다.
        report = bootstrap(args.data_root, min_free_bytes=int(args.min_free_gb * 1024**3))
    # JarvisError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except JarvisError as error:
        # 값을 텍스트로 출력합니다.
        print(f"실패: {error.user_message}", file=sys.stderr)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return int(exit_code_for(error))

    # labels에 딕셔너리(키와 값의 쌍)을 대입합니다.
    labels = {"created": "완료", "copied": "완료", "verified": "확인", "skipped": "건너뜀"}
    # for 반복문: 대상의 항목을 하나씩 action에 대입하며 아래 블록을 실행합니다.
    for action in report.actions:
        # 값을 텍스트로 출력합니다.
        print(f"[{labels[action.status]}] {action.kind}: {action.target}")
    # 값을 텍스트로 출력합니다.
    print(f"남은 공간: {report.free_bytes / 1024**3:.2f} GB")
    # 0을 반환하고 이 함수의 실행을 끝냅니다.
    return 0


# 이 파일을 실행 진입점으로 사용할 때만 아래 코드를 실행합니다. import할 때는 실행하지 않습니다.
if __name__ == "__main__":
    # SystemExit 예외로 프로그램 종료를 요청합니다. 전달한 값은 종료 상태를 나타냅니다.
    raise SystemExit(main())
