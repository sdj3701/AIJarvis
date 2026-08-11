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
_SHORT_NAME_RE = re.compile(r"^[A-Za-z0-9]{1,8}~[0-9]$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def normalize_config_path(path: str | Path) -> Path:
    """Expand environment variables for configuration paths only."""
    return Path(os.path.expandvars(str(path))).expanduser().resolve(strict=False)


def normalize_arg_path(root: Path, relative: str) -> Path:
    """Resolve a tool-relative path without expanding environment variables."""
    if not isinstance(relative, str):
        raise ToolArgInvalid("상대 경로는 문자열이어야 합니다.")
    if "%" in relative or "$" in relative:
        raise ToolArgInvalid("경로에 환경 변수 표기를 쓸 수 없습니다.")
    if relative.startswith(("/", "\\")):
        raise ToolArgInvalid("절대 경로는 사용할 수 없습니다.")
    _reject_path_syntax(relative)
    for part in PureWindowsPath(relative).parts:
        if part in {".", ".."}:
            raise ToolArgInvalid("경로에 .. 또는 . 세그먼트를 사용할 수 없습니다.")
        _validate_component_name(part)
    return (root / relative).resolve(strict=False)


def is_reparse_point(path: Path) -> bool:
    if os.name != "nt":
        return path.is_symlink()
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == -1:
        return False
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


@dataclass(frozen=True, slots=True)
class Sandbox:
    data_root: Path
    write_roots: tuple[Path, ...]
    read_roots: tuple[Path, ...]
    root_map: dict[str, Path]
    policy: SandboxPolicy
    deny_paths: tuple[Path, ...]


def build_sandbox(settings: Settings, policy: SandboxPolicy) -> Sandbox:
    root = settings.paths.data_root.resolve(strict=False)
    write_roots = tuple(
        (root / item).resolve(strict=False) for item in policy.write_roots
    )
    read_roots = tuple((root / item).resolve(strict=False) for item in policy.read_roots)
    root_map = {
        name: (root / rel).resolve(strict=False) for name, rel in policy.roots.items()
    }
    deny_paths = tuple(normalize_config_path(item) for item in policy.deny_paths)
    return Sandbox(
        data_root=root,
        write_roots=write_roots,
        read_roots=read_roots,
        root_map=root_map,
        policy=policy,
        deny_paths=deny_paths,
    )


def assert_in_sandbox(
    path: Path,
    roots: Sequence[Path],
    *,
    sandbox: Sandbox,
    for_write: bool = False,
) -> None:
    """Ensure path stays inside allowed roots and passes Windows path guards."""
    resolved = path.resolve(strict=False)
    _reject_absolute_escape(resolved, sandbox)
    if not sandbox.policy.follow_reparse_points:
        _check_reparse_chain(resolved)
    if not _is_under_any_root(resolved, roots):
        raise PolicyDenied("허용된 sandbox 루트 밖의 경로입니다.")
    if for_write:
        check_write_extension(resolved, sandbox.policy)


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
    if root_name not in allowed_roots:
        raise PolicyDenied(f"허용되지 않은 root입니다: {root_name}")
    if root_name not in sandbox.root_map:
        raise PolicyDenied(f"등록되지 않은 root입니다: {root_name}")
    root = sandbox.root_map[root_name]
    target = normalize_arg_path(root, relative)
    assert_in_sandbox(target, (root,), sandbox=sandbox, for_write=for_write)
    if must_exist and not target.exists():
        raise PolicyDenied("경로가 존재하지 않습니다.")
    if must_be_dir and not target.is_dir():
        raise PolicyDenied("디렉터리가 아닙니다.")
    return target


def check_write_extension(path: Path, policy: SandboxPolicy) -> None:
    suffix = path.suffix.lower()
    forbidden = {item.lower() for item in policy.forbidden_write_extensions}
    allowed = {item.lower() for item in policy.allowed_write_extensions}
    if suffix in forbidden:
        raise PolicyDenied(f"금지된 확장자입니다: {suffix}")
    if suffix and suffix not in allowed:
        raise PolicyDenied(f"허용되지 않은 확장자입니다: {suffix}")
    if not suffix:
        raise PolicyDenied("확장자가 없는 파일은 생성할 수 없습니다.")


def _reject_path_syntax(relative: str) -> None:
    if relative.startswith("\\\\"):
        raise ToolArgInvalid("UNC 경로는 사용할 수 없습니다.")
    if relative.startswith("\\\\?\\") or relative.startswith("\\\\.\\"):
        raise ToolArgInvalid("장치 경로는 사용할 수 없습니다.")
    if ":$" in relative or "::$" in relative:
        raise ToolArgInvalid("NTFS 대체 데이터 스트림은 사용할 수 없습니다.")
    if relative != relative.strip():
        raise ToolArgInvalid("경로 앞뒤 공백은 허용되지 않습니다.")
    if relative.endswith(" ") or relative.endswith("."):
        raise ToolArgInvalid("경로 끝의 공백이나 점은 허용되지 않습니다.")
    if PureWindowsPath(relative).drive:
        raise ToolArgInvalid("절대 경로는 사용할 수 없습니다.")


def _validate_component_name(part: str) -> None:
    if part != part.strip():
        raise ToolArgInvalid("경로 구성 요소의 앞뒤 공백은 허용되지 않습니다.")
    if part.endswith(" ") or part.endswith("."):
        raise ToolArgInvalid("경로 구성 요소 끝의 공백이나 점은 허용되지 않습니다.")
    base = part.split(".", 1)[0].upper()
    if base in _WINDOWS_RESERVED:
        raise ToolArgInvalid(f"Windows 예약 이름은 사용할 수 없습니다: {part}")
    if _SHORT_NAME_RE.fullmatch(part):
        raise ToolArgInvalid("8.3 짧은 파일 이름 형식은 사용할 수 없습니다.")


def _reject_absolute_escape(path: Path, sandbox: Sandbox) -> None:
    text = str(path)
    if sandbox.policy.deny_unc_paths and text.startswith("\\\\"):
        raise PolicyDenied("UNC 경로는 차단됩니다.")
    if sandbox.policy.deny_device_paths and (
        text.startswith("\\\\?\\") or text.startswith("\\\\.\\")
    ):
        raise PolicyDenied("장치 경로는 차단됩니다.")
    for denied in sandbox.deny_paths:
        if _is_under_any_root(path, (denied,)):
            raise PolicyDenied("명시적으로 거부된 경로입니다.")


def _check_reparse_chain(path: Path) -> None:
    current = path
    seen: set[Path] = set()
    while True:
        if current in seen:
            break
        seen.add(current)
        if current.exists() and is_reparse_point(current):
            raise PolicyDenied("reparse point(junction/symlink) 경유 접근은 차단됩니다.")
        parent = current.parent
        if parent == current:
            break
        current = parent


def _is_under_any_root(path: Path, roots: Sequence[Path]) -> bool:
    path_text = os.path.normcase(str(path.resolve(strict=False)))
    for root in roots:
        root_text = os.path.normcase(str(root.resolve(strict=False)))
        try:
            common = os.path.commonpath([path_text, root_text])
        except ValueError:
            continue
        if common == root_text:
            return True
    return False
