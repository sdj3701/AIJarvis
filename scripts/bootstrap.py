"""Create the Jarvis data tree and initialize its SQLite database."""

# [파일 역할] 자비스가 사용할 폴더, 초기 설정 파일, SQLite DB를 준비한다.
# 실행 흐름: main() → bootstrap() → 폴더 생성 → 쓰기/용량 확인 → 설정 복사 → DB 준비.
# 공부할 때는 main()을 먼저 읽고, main()이 호출하는 함수를 따라 올라가도 좋다.
# `python -m scripts.bootstrap --help`는 옵션 설명을 보여 주고 작업 없이 종료한다.
# 실제 실행하면 --data-root에 파일을 만든다. 기본 경로는 app.config.defaults에서 온다.
#
# 타입 힌트를 정의 시점에 바로 평가하지 않도록 한다. 예를 들어 함수의 반환 타입을
# 읽기 좋은 형태로 적을 수 있으며, 힌트만으로 실행 중 타입 검사가 생기지는 않는다.
from __future__ import annotations

# import는 다른 모듈의 기능을 현재 파일에서 사용할 수 있게 가져오는 문법이다.
# argparse: 명령줄 옵션 해석 / os: 운영체제 기능 / shutil: 파일 복사와 디스크 정보.
# sys: import 검색 경로와 오류 출력 / tempfile: 임시 파일 생성.
# dataclass: 데이터를 담는 클래스의 기본 메서드 생성 / Path: 파일 경로를 객체로 표현.
import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# __file__은 현재 파이썬 파일의 경로다. resolve()는 절대 경로로 정리한다.
# parents[0]은 scripts 폴더, parents[1]은 그 위의 AIJarvis 프로젝트 폴더다.
# 현재 터미널 위치가 아니라 이 파일의 위치를 기준으로 프로젝트를 찾는 것이다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# 파일 경로로 직접 실행해도 app을 import할 수 있도록 프로젝트를 검색 경로에 넣는다.
# insert(0, ...)의 0은 목록 맨 앞이다. str()은 Path 객체를 문자열로 바꾼다.
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

# from A import B는 A 모듈에서 B라는 이름만 가져온다.
# noqa: E402는 경로 설정 뒤에 import하는 구조를 코드 검사 도구에 예외로 알린다.
from app.config.defaults import DEFAULT_DATA_ROOT  # noqa: E402
from app.core.errors import ConfigError, JarvisError, exit_code_for  # noqa: E402
from app.memory.migrations import initialize_database  # noqa: E402

# 대문자 이름은 '상수처럼 사용할 값'이라는 관례다. 파이썬이 변경을 막지는 않는다.
# Path 객체의 /는 숫자 나눗셈이 아니라 경로를 연결하는 연산으로 동작한다.
DEFAULT_CONFIG_SOURCE = REPOSITORY_ROOT / "config"
# **는 거듭제곱이다. 1024**3 바이트는 1 GiB이며 여기서는 최소 5 GiB를 요구한다.
DEFAULT_MIN_FREE_BYTES = 5 * 1024**3

# 괄호와 쉼표로 나열한 tuple은 순서가 있고 항목을 직접 바꿀 수 없는 자료형이다.
# 데이터 루트 아래에 만들 하위 폴더의 상대 경로를 보관한다.
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
# dict는 '키: 값'의 대응표다. 여기서는 '예제 파일명: 실제 설정 파일명'이다.
CONFIG_COPIES = {
    "settings.example.yaml": "settings.yaml",
    "privacy.example.yaml": "privacy.yaml",
    "tools.example.yaml": "tools.yaml",
}


# @로 시작하는 데코레이터는 바로 아래 클래스나 함수에 추가 처리를 적용한다.
# dataclass는 아래 필드에서 생성자(__init__), 비교, 출력용 표현 등을 만들어 준다.
# frozen=True는 생성 후 필드 재할당을 막고, slots=True는 지정된 필드만 갖게 한다.
@dataclass(frozen=True, slots=True)
class BootstrapAction:
    # 작업 종류, 처리 결과, 대상 경로를 하나의 객체로 묶어 반환하기 위한 자료형이다.
    kind: str
    status: str
    target: Path


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    # 전체 준비 결과다. actions는 BootstrapAction이 여러 개 들어가는 튜플이다.
    # tuple[BootstrapAction, ...]의 ...는 항목 수가 고정되어 있지 않다는 타입 표기다.
    data_root: Path
    database_path: Path
    free_bytes: int
    actions: tuple[BootstrapAction, ...]


def create_tree(data_root: Path) -> tuple[BootstrapAction, ...]:
    """Create all required directories, reporting existing paths as skipped."""
    # def는 함수 정의, data_root는 입력 매개변수, -> 뒤는 반환값의 타입 힌트다.
    # list는 항목을 추가할 수 있어 작업 결과를 모으기에 적합하다.
    actions: list[BootstrapAction] = []
    for relative in TREE_DIRECTORIES:
        # for는 목록의 항목을 순서대로 relative에 넣고 들여쓴 코드를 반복한다.
        target = data_root / Path(relative)
        existed = target.is_dir()
        # parents=True: 중간 부모 폴더도 생성. exist_ok=True: 이미 폴더가 있어도 허용.
        target.mkdir(parents=True, exist_ok=True)
        # A if 조건 else B는 값 하나를 고르는 조건 표현식이다.
        # append()로 방금 처리한 폴더의 결과 객체를 목록 끝에 추가한다.
        actions.append(BootstrapAction("directory", "skipped" if existed else "created", target))
    # return은 함수 실행을 끝내고 호출한 곳에 값을 돌려준다.
    # 내부에서는 list로 모았지만 반환할 때는 tuple로 바꿔 전달한다.
    return tuple(actions)


# 이름 앞의 _는 '이 모듈 내부에서 사용할 보조 함수'라는 관례이며 접근 제한은 아니다.
def _copy_initial_configs(data_root: Path, source: Path) -> tuple[BootstrapAction, ...]:
    actions: list[BootstrapAction] = []
    # items()는 dict의 (키, 값) 쌍을 꺼낸다. 두 변수에 나눠 받는 것을 언패킹이라 한다.
    for source_name, target_name in CONFIG_COPIES.items():
        source_path = source / source_name
        target_path = data_root / "config" / target_name
        if not source_path.is_file():
            # raise는 정상 흐름을 중단하고 예외를 발생시킨다. 여기서는 설정 오류다.
            raise ConfigError("초기 설정 원본 파일이 없습니다.", {"source": str(source_path)})
        try:
            # with는 블록을 벗어날 때 파일을 닫는다. 중간에 예외가 나도 정리한다.
            # rb는 바이너리 읽기, xb는 파일이 없을 때만 가능한 바이너리 새 파일 쓰기다.
            # 이미 사용자가 설정을 바꾼 파일이 있으면 덮어쓰지 않고 예외가 발생한다.
            # "xb" creates the file only when missing so a rerun cannot clobber live config.
            with source_path.open("rb") as input_file, target_path.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file)
        except FileExistsError:
            # try 안에서 '이미 파일이 있음' 예외가 발생한 경우만 여기서 처리한다.
            actions.append(BootstrapAction("config", "skipped", target_path))
        else:
            # try/except의 else는 try가 예외 없이 완료됐을 때 실행된다.
            actions.append(BootstrapAction("config", "copied", target_path))
    return tuple(actions)


def _verify_writable(data_root: Path) -> None:
    # -> None은 돌려줄 결과 데이터가 없다는 뜻이다. 실패하면 예외로 알린다.
    # 권한 정보만 보는 대신 작은 임시 파일을 실제로 쓰고 삭제해 쓰기 가능 여부를 본다.
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".bootstrap-write-", dir=data_root / "state", delete=False
        ) as probe:
            # b"ok"는 str이 아닌 bytes다. 바이너리 모드 파일에는 bytes를 쓴다.
            probe.write(b"ok")
            # flush()는 파이썬 버퍼를 비우고, fsync()는 OS에 디스크 동기화를 요청한다.
            probe.flush()
            os.fsync(probe.fileno())
            probe_path = Path(probe.name)
        # Windows에서도 열린 파일을 지우지 않도록 with로 닫은 다음 삭제한다.
        probe_path.unlink()
    except OSError as error:
        # as error로 예외 객체를 받는다. from error는 원인 예외를 함께 보존한다.
        raise ConfigError(
            "데이터 루트에 쓸 수 없습니다.",
            {"data_root": str(data_root), "error_type": type(error).__name__},
        ) from error


# 기본값이 있는 인수는 생략 가능하다. 단독 * 뒤의 인수는 이름을 써서 전달해야 한다.
# 예: bootstrap(root, min_free_bytes=0). 위치만으로 두 번째 인수를 넘길 수는 없다.
def bootstrap(
    data_root: Path = DEFAULT_DATA_ROOT,
    *,
    config_source: Path = DEFAULT_CONFIG_SOURCE,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
) -> BootstrapReport:
    """Run the complete idempotent bootstrap sequence."""
    # 멱등성(idempotent)은 여러 번 실행해도 같은 준비 상태에 도달한다는 뜻이다.
    # 기존 폴더와 설정을 보존하고, DB 생성/검증의 세부 내용은 app 함수에 맡긴다.
    if min_free_bytes < 0:
        raise ValueError("min_free_bytes must be non-negative")
    actions = list(create_tree(data_root))
    _verify_writable(data_root)
    free_bytes = shutil.disk_usage(data_root).free
    if free_bytes < min_free_bytes:
        raise ConfigError(
            "데이터 저장 공간이 부족합니다.",
            {"required_bytes": min_free_bytes, "free_bytes": free_bytes},
        )
    # append는 값 하나를 추가하고, extend는 iterable 안의 여러 값을 각각 추가한다.
    actions.extend(_copy_initial_configs(data_root, config_source))

    # 스크립트는 순서를 조율한다. 실제 DB 스키마 준비는 initialize_database의 역할이다.
    database_path = data_root / "memory" / "jarvis.sqlite3"
    database_result = initialize_database(database_path)
    actions.append(
        BootstrapAction(
            "database", "created" if database_result.created else "verified", database_path
        )
    )
    return BootstrapReport(data_root, database_path, free_bytes, tuple(actions))


def _parser() -> argparse.ArgumentParser:
    # ArgumentParser는 프로그램 사용 설명과 명령줄 입력 규칙을 담는 객체다.
    # 여기서는 규칙만 만들고, 입력을 실제 해석하는 parse_args는 main에서 호출한다.
    parser = argparse.ArgumentParser(description="Jarvis 데이터 폴더와 DB를 초기화합니다.")
    # type=Path는 입력 문자열을 Path로 변환한다. default는 옵션 생략 시의 값이다.
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=DEFAULT_MIN_FREE_BYTES / 1024**3,
        help="필요한 최소 여유 공간(GB)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # list[str] | None은 문자열 목록 또는 None이라는 뜻이다.
    # argv=None이면 터미널 인수를 사용하고, 테스트에서는 목록을 직접 넘길 수 있다.
    args = _parser().parse_args(argv)
    if args.min_free_gb < 0:
        # parser.error()는 사용법과 오류를 출력하고 종료 코드 2로 종료한다.
        _parser().error("--min-free-gb는 0 이상이어야 합니다.")
    try:
        # 입력한 용량을 바이트로 바꾸고 int()로 정수화해 실제 준비 함수에 전달한다.
        report = bootstrap(args.data_root, min_free_bytes=int(args.min_free_gb * 1024**3))
    except JarvisError as error:
        # stderr는 일반 결과(stdout)와 별도로 오류 메시지를 보내는 출력 통로다.
        print(f"실패: {error.user_message}", file=sys.stderr)
        return int(exit_code_for(error))

    labels = {"created": "완료", "copied": "완료", "verified": "확인", "skipped": "건너뜀"}
    for action in report.actions:
        # f"...{표현식}..."은 표현식 결과를 문자열에 끼워 넣는 f-string이다.
        print(f"[{labels[action.status]}] {action.kind}: {action.target}")
    # :.2f는 소수점 아래 두 자리까지 표시하는 서식이다.
    print(f"남은 공간: {report.free_bytes / 1024**3:.2f} GB")
    # 명령줄 프로그램의 종료 코드는 관례상 0이면 성공, 0이 아니면 실패다.
    return 0


# 직접 실행할 때만 main을 호출한다. 다른 파일에서 import할 때는 호출하지 않는다.
# SystemExit 예외는 main의 정수를 프로그램 종료 코드로 전달한다.
if __name__ == "__main__":
    raise SystemExit(main())
