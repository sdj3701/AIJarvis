# 파이썬 공부 | scripts/app/safety/paths.py
# 파일 경로가 허용 폴더 안에 있는지와 링크를 통한 우회 여부를 검사합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Path normalization, sandbox containment, and reparse-point checks."""

from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from app.config.models import SandboxPolicy, Settings
from app.core.errors import PolicyDenied, ToolArgInvalid

# frozenset()의 반환값을 _WINDOWS_RESERVED에 대입합니다.
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)
# re.compile()의 반환값을 _SHORT_NAME_RE에 대입합니다.
_SHORT_NAME_RE = re.compile(r"^[A-Za-z0-9]{1,8}~[0-9]$")
# _FILE_ATTRIBUTE_REPARSE_POINT에 숫자 등 고정된 값을 대입합니다.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


# normalize_config_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: Path.
def normalize_config_path(path: str | Path) -> Path:
    """Expand environment variables for configuration paths only."""
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Path(os.path.expandvars(str(path))).expanduser().resolve(strict=False)


# normalize_arg_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: root, relative.
# 반환 타입 힌트: Path.
def normalize_arg_path(root: Path, relative: str) -> Path:
    """Resolve a tool-relative path without expanding environment variables."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(relative, str).
    if not isinstance(relative, str):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("상대 경로는 문자열이어야 합니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: '%' in relative or '$' in relative.
    if "%" in relative or "$" in relative:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("경로에 환경 변수 표기를 쓸 수 없습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: relative.startswith(('/', '\\')).
    if relative.startswith(("/", "\\")):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("절대 경로는 사용할 수 없습니다.")
    # _reject_path_syntax()을 호출해 작업을 수행합니다.
    _reject_path_syntax(relative)
    # for 반복문: 대상의 항목을 하나씩 part에 대입하며 아래 블록을 실행합니다.
    for part in PureWindowsPath(relative).parts:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: part in {'.', '..'}.
        if part in {".", ".."}:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolArgInvalid("경로에 .. 또는 . 세그먼트를 사용할 수 없습니다.")
        # _validate_component_name()으로 입력 형식과 허용 조건을 검사합니다.
        _validate_component_name(part)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return (root / relative).resolve(strict=False)


# is_reparse_point(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 참/거짓(bool).
def is_reparse_point(path: Path) -> bool:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: os.name != 'nt'.
    if os.name != "nt":
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return path.is_symlink()
    # ctypes.windll.kernel32.GetFileAttributesW()의 반환값을 attrs에 대입합니다.
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: attrs == -1.
    if attrs == -1:
        # False을 반환하고 이 함수의 실행을 끝냅니다.
        return False
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


# Sandbox: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class Sandbox:
    # data_root: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    data_root: Path
    # write_roots: tuple[Path, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    write_roots: tuple[Path, ...]
    # read_roots: tuple[Path, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    read_roots: tuple[Path, ...]
    # root_map: dict[str, Path] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    root_map: dict[str, Path]
    # policy: SandboxPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    policy: SandboxPolicy
    # deny_paths: tuple[Path, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    deny_paths: tuple[Path, ...]


# build_sandbox(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: settings, policy.
# 반환 타입 힌트: Sandbox.
def build_sandbox(settings: Settings, policy: SandboxPolicy) -> Sandbox:
    # settings.paths.data_root.resolve()의 반환값을 root에 대입합니다.
    root = settings.paths.data_root.resolve(strict=False)
    # tuple()의 반환값을 write_roots에 대입합니다.
    write_roots = tuple(
        (root / item).resolve(strict=False) for item in policy.write_roots
    )
    # tuple()의 반환값을 read_roots에 대입합니다.
    read_roots = tuple((root / item).resolve(strict=False) for item in policy.read_roots)
    # 오른쪽 식을 계산한 값을 root_map에 대입합니다.
    # 딕셔너리 컴프리헨션: 반복하면서 키와 값을 만들어 사전으로 모읍니다.
    root_map = {
        name: (root / rel).resolve(strict=False) for name, rel in policy.roots.items()
    }
    # tuple()의 반환값을 deny_paths에 대입합니다.
    deny_paths = tuple(normalize_config_path(item) for item in policy.deny_paths)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Sandbox(
        data_root=root,
        write_roots=write_roots,
        read_roots=read_roots,
        root_map=root_map,
        policy=policy,
        deny_paths=deny_paths,
    )


# assert_in_sandbox(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, roots, sandbox, for_write.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def assert_in_sandbox(
    path: Path,
    roots: Sequence[Path],
    *,
    sandbox: Sandbox,
    for_write: bool = False,
) -> None:
    """Ensure path stays inside allowed roots and passes Windows path guards."""
    # path.resolve()의 반환값을 resolved에 대입합니다.
    resolved = path.resolve(strict=False)
    # _reject_absolute_escape()을 호출해 작업을 수행합니다.
    _reject_absolute_escape(resolved, sandbox)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not sandbox.policy.follow_reparse_points.
    if not sandbox.policy.follow_reparse_points:
        # _check_reparse_chain()을 호출해 작업을 수행합니다.
        _check_reparse_chain(resolved)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not _is_under_any_root(resolved, roots).
    if not _is_under_any_root(resolved, roots):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("허용된 sandbox 루트 밖의 경로입니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: for_write.
    if for_write:
        # check_write_extension()을 호출해 작업을 수행합니다.
        check_write_extension(resolved, sandbox.policy)


# resolve_tool_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: sandbox, root_name, relative, allowed_roots, must_exist, must_be_dir, for_write.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Path.
def resolve_tool_path(
    sandbox: Sandbox,
    *,
    root_name: str,
    relative: str,
    allowed_roots: Sequence[str],
    must_exist: bool = False,
    must_be_dir: bool = False,
    for_write: bool = False,
) -> Path:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: root_name not in allowed_roots.
    if root_name not in allowed_roots:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied(f"허용되지 않은 root입니다: {root_name}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: root_name not in sandbox.root_map.
    if root_name not in sandbox.root_map:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied(f"등록되지 않은 root입니다: {root_name}")
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = sandbox.root_map[root_name]
    # normalize_arg_path()의 반환값을 target에 대입합니다.
    target = normalize_arg_path(root, relative)
    # assert_in_sandbox()을 호출해 작업을 수행합니다.
    assert_in_sandbox(target, (root,), sandbox=sandbox, for_write=for_write)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: must_exist and (not target.exists()).
    if must_exist and not target.exists():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("경로가 존재하지 않습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: must_be_dir and (not target.is_dir()).
    if must_be_dir and not target.is_dir():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("디렉터리가 아닙니다.")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return target


# check_write_extension(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, policy.
# 반환 타입 힌트: 별도 결과 없음(None).
def check_write_extension(path: Path, policy: SandboxPolicy) -> None:
    # path.suffix.lower()의 반환값을 suffix에 대입합니다.
    suffix = path.suffix.lower()
    # 오른쪽 식을 계산한 값을 forbidden에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    forbidden = {item.lower() for item in policy.forbidden_write_extensions}
    # 오른쪽 식을 계산한 값을 allowed에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    allowed = {item.lower() for item in policy.allowed_write_extensions}
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: suffix in forbidden.
    if suffix in forbidden:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied(f"금지된 확장자입니다: {suffix}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: suffix and suffix not in allowed.
    if suffix and suffix not in allowed:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied(f"허용되지 않은 확장자입니다: {suffix}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not suffix.
    if not suffix:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("확장자가 없는 파일은 생성할 수 없습니다.")


# _reject_path_syntax(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: relative.
# 반환 타입 힌트: 별도 결과 없음(None).
def _reject_path_syntax(relative: str) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: relative.startswith('\\\\').
    if relative.startswith("\\\\"):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("UNC 경로는 사용할 수 없습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: relative.startswith('\\\\?\\') or
    # relative.startswith('\\\\.\\').
    if relative.startswith("\\\\?\\") or relative.startswith("\\\\.\\"):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("장치 경로는 사용할 수 없습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ':$' in relative or '::$' in relative.
    if ":$" in relative or "::$" in relative:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("NTFS 대체 데이터 스트림은 사용할 수 없습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: relative != relative.strip().
    if relative != relative.strip():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("경로 앞뒤 공백은 허용되지 않습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: relative.endswith(' ') or
    # relative.endswith('.').
    if relative.endswith(" ") or relative.endswith("."):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("경로 끝의 공백이나 점은 허용되지 않습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: PureWindowsPath(relative).drive.
    if PureWindowsPath(relative).drive:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("절대 경로는 사용할 수 없습니다.")


# _validate_component_name(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: part.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_component_name(part: str) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: part != part.strip().
    if part != part.strip():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("경로 구성 요소의 앞뒤 공백은 허용되지 않습니다.")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: part.endswith(' ') or part.endswith('.').
    if part.endswith(" ") or part.endswith("."):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("경로 구성 요소 끝의 공백이나 점은 허용되지 않습니다.")
    # part.split('.', 1)[0].upper()의 반환값을 base에 대입합니다.
    base = part.split(".", 1)[0].upper()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: base in _WINDOWS_RESERVED.
    if base in _WINDOWS_RESERVED:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid(f"Windows 예약 이름은 사용할 수 없습니다: {part}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _SHORT_NAME_RE.fullmatch(part).
    if _SHORT_NAME_RE.fullmatch(part):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolArgInvalid("8.3 짧은 파일 이름 형식은 사용할 수 없습니다.")


# _reject_absolute_escape(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, sandbox.
# 반환 타입 힌트: 별도 결과 없음(None).
def _reject_absolute_escape(path: Path, sandbox: Sandbox) -> None:
    # str()의 반환값을 text에 대입합니다.
    text = str(path)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: sandbox.policy.deny_unc_paths and
    # text.startswith('\\\\').
    if sandbox.policy.deny_unc_paths and text.startswith("\\\\"):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("UNC 경로는 차단됩니다.")
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if sandbox.policy.deny_device_paths and (
        text.startswith("\\\\?\\") or text.startswith("\\\\.\\")
    ):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("장치 경로는 차단됩니다.")
    # for 반복문: 대상의 항목을 하나씩 denied에 대입하며 아래 블록을 실행합니다.
    for denied in sandbox.deny_paths:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _is_under_any_root(path, (denied,)).
        if _is_under_any_root(path, (denied,)):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("명시적으로 거부된 경로입니다.")


# _check_reparse_chain(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 별도 결과 없음(None).
def _check_reparse_chain(path: Path) -> None:
    # 오른쪽 식을 계산한 값을 current에 대입합니다.
    current = path
    # set()의 반환값을 seen에 대입합니다.
    seen: set[Path] = set()
    # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
    while True:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current in seen.
        if current in seen:
            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
            break
        # add 메서드를 호출해 항목이나 기록을 추가합니다.
        seen.add(current)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current.exists() and
        # is_reparse_point(current).
        if current.exists() and is_reparse_point(current):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("reparse point(junction/symlink) 경유 접근은 차단됩니다.")
        # 오른쪽 식을 계산한 값을 parent에 대입합니다.
        parent = current.parent
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: parent == current.
        if parent == current:
            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
            break
        # 오른쪽 식을 계산한 값을 current에 대입합니다.
        current = parent


# _is_under_any_root(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, roots.
# 반환 타입 힌트: 참/거짓(bool).
def _is_under_any_root(path: Path, roots: Sequence[Path]) -> bool:
    # os.path.normcase()의 반환값을 path_text에 대입합니다.
    path_text = os.path.normcase(str(path.resolve(strict=False)))
    # for 반복문: 대상의 항목을 하나씩 root에 대입하며 아래 블록을 실행합니다.
    for root in roots:
        # os.path.normcase()의 반환값을 root_text에 대입합니다.
        root_text = os.path.normcase(str(root.resolve(strict=False)))
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # os.path.commonpath()의 반환값을 common에 대입합니다.
            common = os.path.commonpath([path_text, root_text])
        # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ValueError:
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: common == root_text.
        if common == root_text:
            # True을 반환하고 이 함수의 실행을 끝냅니다.
            return True
    # False을 반환하고 이 함수의 실행을 끝냅니다.
    return False
