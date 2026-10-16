# 파이썬 공부 | scripts/app/config/loader.py
# YAML 설정을 읽고 값과 설정 사이의 관계를 검증합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Load, validate, cross-check, and hash Jarvis YAML configuration."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from app.config.defaults import DEFAULT_CONFIG_DIR
from app.config.models import LoadedConfig, Policies, PrivacyPolicy, Settings, ToolPolicy
from app.core.errors import ConfigError

# _CONFIG_FILENAMES에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
_CONFIG_FILENAMES = ("settings.yaml", "tools.yaml", "privacy.yaml")
# _SETTINGS_RELATIVE_PATHS에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
_SETTINGS_RELATIVE_PATHS = (
    "memory_db",
    "raw_dir",
    "export_dir",
    "docs_dir",
    "notes_dir",
    "skills_dir",
    "state_dir",
    "logs_dir",
    "models_dir",
    "backups_dir",
)
# _ROOT_SETTINGS_FIELDS에 딕셔너리(키와 값의 쌍)을 대입합니다.
_ROOT_SETTINGS_FIELDS = {
    "docs": "docs_dir",
    "notes": "notes_dir",
    "memory_export": "export_dir",
}

# TypeVar()의 반환값을 ModelT에 대입합니다.
ModelT = TypeVar("ModelT", bound=BaseModel)


# load_settings(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, overrides.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Settings.
def load_settings(
    path: Path,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Load settings.yaml and validate its local filesystem contract."""
    # _read_yaml_mapping()의 반환값을 document에 대입합니다.
    document = _read_yaml_mapping(path)
    # _apply_overrides()을 호출해 작업을 수행합니다.
    _apply_overrides(document, overrides)
    # _validate_model()의 반환값을 settings에 대입합니다.
    settings = _validate_model(Settings, document, path)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return _validate_settings_paths(settings, source=path)


# load_policies(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tools_path, privacy_path, settings, overrides, registered_tools.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Policies.
def load_policies(
    tools_path: Path,
    privacy_path: Path,
    *,
    settings: Settings,
    overrides: Mapping[str, Any] | None = None,
    registered_tools: set[str] | None = None,
) -> Policies:
    """Load both policy files and enforce their cross-file constraints."""
    # _read_yaml_mapping()의 반환값을 tools_document에 대입합니다.
    tools_document = _read_yaml_mapping(tools_path)
    # _read_yaml_mapping()의 반환값을 privacy_document에 대입합니다.
    privacy_document = _read_yaml_mapping(privacy_path)
    # _apply_policy_overrides()을 호출해 작업을 수행합니다.
    _apply_policy_overrides(tools_document, privacy_document, overrides)

    # _validate_model()의 반환값을 tools에 대입합니다.
    tools = _validate_model(ToolPolicy, tools_document, tools_path)
    # _validate_model()의 반환값을 privacy에 대입합니다.
    privacy = _validate_model(PrivacyPolicy, privacy_document, privacy_path)
    # Policies()의 반환값을 policies에 대입합니다.
    policies = Policies(tools=tools, privacy=privacy)
    # _validate_policy_paths()으로 입력 형식과 허용 조건을 검사합니다.
    _validate_policy_paths(settings, policies)
    # _validate_policy_contracts()으로 입력 형식과 허용 조건을 검사합니다.
    _validate_policy_contracts(settings, policies, registered_tools=registered_tools)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return policies


# load_config(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir, registered_tools.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: LoadedConfig.
def load_config(
    config_dir: Path = DEFAULT_CONFIG_DIR,
    *,
    registered_tools: set[str] | None = None,
) -> LoadedConfig:
    """Load the operational configuration directory as one immutable bundle.

    Missing files mean bootstrap has not run. Unknown YAML keys are rejected by
    the Pydantic models (``extra="forbid"``), not by this function.
    """
    # Path()의 반환값을 directory에 대입합니다.
    directory = Path(config_dir)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not directory.is_dir().
    if not directory.is_dir():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "설정 디렉터리가 없습니다. 먼저 python scripts\\bootstrap.py를 실행하세요.",
            {"config_dir": str(directory), "reason": "missing_config_directory"},
        )

    # 오른쪽 식을 계산한 값을 missing에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    missing = [name for name in _CONFIG_FILENAMES if not (directory / name).is_file()]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: missing.
    if missing:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "운영 설정 파일이 없습니다. 먼저 python scripts\\bootstrap.py를 실행하세요.",
            {"config_dir": str(directory), "missing": missing},
        )

    # load_settings()의 반환값을 settings에 대입합니다.
    settings = load_settings(directory / "settings.yaml")
    # load_policies()의 반환값을 policies에 대입합니다.
    policies = load_policies(
        directory / "tools.yaml",
        directory / "privacy.yaml",
        settings=settings,
        registered_tools=registered_tools,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return LoadedConfig(
        settings=settings,
        policies=policies,
        config_hash=calculate_config_hash(settings, policies),
    )


# calculate_config_hash(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: settings, policies.
# 반환 타입 힌트: 문자열(str).
def calculate_config_hash(settings: Settings, policies: Policies) -> str:
    """Return a stable SHA-256 over the effective three-file configuration."""
    # merged에 딕셔너리(키와 값의 쌍)을 대입합니다.
    merged = {
        "privacy": policies.privacy.model_dump(mode="json", by_alias=True),
        "settings": settings.model_dump(mode="json", by_alias=True),
        "tools": policies.tools.model_dump(mode="json", by_alias=True),
    }
    # 아래 함수()의 반환값을 canonical에 대입합니다.
    canonical = json.dumps(
        merged,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return hashlib.sha256(canonical).hexdigest()


# _read_yaml_mapping(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: dict[str, Any].
def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with path.open("r", encoding="utf-8") as stream:
            # yaml.safe_load()의 반환값을 document에 대입합니다.
            document = yaml.safe_load(stream)
    # FileNotFoundError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except FileNotFoundError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            f"설정 파일 {path.name}이 없습니다. bootstrap을 먼저 실행하세요.",
            {"file": str(path), "reason": "missing_file"},
        ) from error
    # (OSError, UnicodeError, yaml.YAMLError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외
    # 객체가 담깁니다.
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            f"설정 파일 {path.name}을 읽을 수 없습니다.",
            {"file": str(path), "error_type": type(error).__name__},
        ) from error

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(document, dict).
    if not isinstance(document, dict):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            f"설정 파일 {path.name}의 최상위 값은 객체여야 합니다.",
            {"file": str(path), "reason": "root_not_mapping"},
        )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return document


# _validate_model(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: model_type, document, path.
# 반환 타입 힌트: ModelT.
def _validate_model(model_type: type[ModelT], document: dict[str, Any], path: Path) -> ModelT:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return model_type.model_validate(document)
    # ValidationError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except ValidationError as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            f"설정 파일 {path.name}의 값이 올바르지 않습니다.",
            {
                "file": str(path),
                "errors": error.errors(include_input=False, include_url=False),
            },
        ) from error


# _apply_overrides(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: document, overrides.
# 반환 타입 힌트: 별도 결과 없음(None).
def _apply_overrides(
    document: dict[str, Any],
    overrides: Mapping[str, Any] | None,
) -> None:
    # for 반복문: 대상의 항목을 하나씩 (dotted_key, value)에 대입하며 아래 블록을 실행합니다.
    for dotted_key, value in (overrides or {}).items():
        # _set_existing_dotted_value()을 호출해 작업을 수행합니다.
        _set_existing_dotted_value(document, dotted_key, deepcopy(value))


# _apply_policy_overrides(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tools_document, privacy_document, overrides.
# 반환 타입 힌트: 별도 결과 없음(None).
def _apply_policy_overrides(
    tools_document: dict[str, Any],
    privacy_document: dict[str, Any],
    overrides: Mapping[str, Any] | None,
) -> None:
    # for 반복문: 대상의 항목을 하나씩 (dotted_key, value)에 대입하며 아래 블록을 실행합니다.
    for dotted_key, value in (overrides or {}).items():
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: dotted_key == 'tools.app_map'.
        if dotted_key == "tools.app_map":
            # tools_document.get()의 반환값을 definitions에 대입합니다.
            definitions = tools_document.get("tools")
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(definitions, list).
            if not isinstance(definitions, list):
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ConfigError("tools 정책의 도구 목록이 올바르지 않습니다.")
            # next()의 반환값을 open_app에 대입합니다.
            open_app = next(
                (
                    item
                    for item in definitions
                    if isinstance(item, dict) and item.get("name") == "open_app"
                ),
                None,
            )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: open_app is None.
            if open_app is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ConfigError("tools 정책에 open_app 정의가 없습니다.")
            # deepcopy()의 반환값을 open_app['app_map']에 대입합니다.
            open_app["app_map"] = deepcopy(value)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: dotted_key.startswith('tools.').
        elif dotted_key.startswith("tools."):
            # _set_existing_dotted_value()을 호출해 작업을 수행합니다.
            _set_existing_dotted_value(
                tools_document,
                dotted_key.removeprefix("tools."),
                deepcopy(value),
            )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: dotted_key.startswith('privacy.').
        elif dotted_key.startswith("privacy."):
            # _set_existing_dotted_value()을 호출해 작업을 수행합니다.
            _set_existing_dotted_value(
                privacy_document,
                dotted_key.removeprefix("privacy."),
                deepcopy(value),
            )
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ConfigError(
                "정책 override는 tools. 또는 privacy.로 시작해야 합니다.",
                {"override": dotted_key},
            )


# _set_existing_dotted_value(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: document, dotted_key, value.
# 반환 타입 힌트: 별도 결과 없음(None).
def _set_existing_dotted_value(document: dict[str, Any], dotted_key: str, value: Any) -> None:
    # dotted_key.split()의 반환값을 parts에 대입합니다.
    parts = dotted_key.split(".")
    # 오른쪽 식을 계산한 값을 current에 대입합니다.
    current: Any = document
    # for 반복문: 대상의 항목을 하나씩 part에 대입하며 아래 블록을 실행합니다.
    for part in parts[:-1]:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(current, dict) or part
        # not in current.
        if not isinstance(current, dict) or part not in current:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ConfigError(
                "존재하지 않는 설정 override 경로입니다.",
                {"override": dotted_key},
            )
        # 오른쪽 식을 계산한 값을 current에 대입합니다.
        current = current[part]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(current, dict) or parts[-1]
    # not in current.
    if not isinstance(current, dict) or parts[-1] not in current:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "존재하지 않는 설정 override 경로입니다.",
            {"override": dotted_key},
        )
    # 오른쪽 식을 계산한 값을 current[parts[-1]]에 대입합니다.
    current[parts[-1]] = value


# _validate_settings_paths(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: settings, source.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Settings.
def _validate_settings_paths(settings: Settings, *, source: Path) -> Settings:
    # _normalize_config_path()의 반환값을 root에 대입합니다.
    root = _normalize_config_path(settings.paths.data_root)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not root.is_absolute().
    if not root.is_absolute():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "settings.paths.data_root는 절대 경로여야 합니다.",
            {"file": str(source), "field": "paths.data_root"},
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not root.is_dir().
    if not root.is_dir():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "settings.paths.data_root가 존재하는 디렉터리가 아닙니다.",
            {"file": str(source), "field": "paths.data_root", "path": str(root)},
        )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not os.access(root, os.W_OK).
    if not os.access(root, os.W_OK):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "settings.paths.data_root에 쓸 수 없습니다.",
            {"file": str(source), "field": "paths.data_root", "path": str(root)},
        )

    # for 반복문: 대상의 항목을 하나씩 field_name에 대입하며 아래 블록을 실행합니다.
    for field_name in _SETTINGS_RELATIVE_PATHS:
        # getattr()의 반환값을 configured에 대입합니다.
        configured = getattr(settings.paths, field_name)
        # _resolve_inside()을 호출해 작업을 수행합니다.
        _resolve_inside(root, configured, field=f"paths.{field_name}")

    # settings.paths.model_copy()의 반환값을 normalized_paths에 대입합니다.
    normalized_paths = settings.paths.model_copy(update={"data_root": root})
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return settings.model_copy(update={"paths": normalized_paths})


# _validate_policy_paths(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: settings, policies.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_policy_paths(settings: Settings, policies: Policies) -> None:
    # settings.paths.data_root.resolve()의 반환값을 root에 대입합니다.
    root = settings.paths.data_root.resolve(strict=False)
    # 오른쪽 식을 계산한 값을 sandbox에 대입합니다.
    sandbox = policies.tools.sandbox

    # for 반복문: 대상의 항목을 하나씩 (index, configured)에 대입하며 아래 블록을 실행합니다.
    for index, configured in enumerate(sandbox.write_roots):
        # _resolve_inside()을 호출해 작업을 수행합니다.
        _resolve_inside(root, configured, field=f"sandbox.write_roots[{index}]")
    # for 반복문: 대상의 항목을 하나씩 (index, configured)에 대입하며 아래 블록을 실행합니다.
    for index, configured in enumerate(sandbox.read_roots):
        # _resolve_inside()을 호출해 작업을 수행합니다.
        _resolve_inside(root, configured, field=f"sandbox.read_roots[{index}]")

    # for 반복문: 대상의 항목을 하나씩 (name, configured)에 대입하며 아래 블록을 실행합니다.
    for name, configured in sandbox.roots.items():
        # _resolve_inside()의 반환값을 resolved에 대입합니다.
        resolved = _resolve_inside(root, configured, field=f"sandbox.roots.{name}")
        # _ROOT_SETTINGS_FIELDS.get()의 반환값을 settings_field에 대입합니다.
        settings_field = _ROOT_SETTINGS_FIELDS.get(name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: settings_field is None.
        if settings_field is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ConfigError(
                "sandbox.roots의 이름에 대응하는 settings 경로가 없습니다.",
                {"root_name": name},
            )
        # _resolve_inside()의 반환값을 expected에 대입합니다.
        expected = _resolve_inside(
            root,
            getattr(settings.paths, settings_field),
            field=f"paths.{settings_field}",
        )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: resolved != expected.
        if resolved != expected:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ConfigError(
                "sandbox.roots와 settings.paths가 서로 다른 위치를 가리킵니다.",
                {"root_name": name, "settings_field": settings_field},
            )

    # for 반복문: 대상의 항목을 하나씩 (index, denied_configured)에 대입하며 아래 블록을
    # 실행합니다.
    for index, denied_configured in enumerate(sandbox.deny_paths):
        # _normalize_config_path()의 반환값을 denied에 대입합니다.
        denied = _normalize_config_path(denied_configured)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not denied.is_absolute().
        if not denied.is_absolute():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ConfigError(
                "sandbox.deny_paths에는 절대 경로만 사용할 수 있습니다.",
                {"field": f"sandbox.deny_paths[{index}]"},
            )

    # for 반복문: 대상의 항목을 하나씩 tool에 대입하며 아래 블록을 실행합니다.
    for tool in policies.tools.tools:
        # for 반복문: 대상의 항목을 하나씩 (app_name, executable)에 대입하며 아래 블록을
        # 실행합니다.
        for app_name, executable in (tool.app_map or {}).items():
            # _normalize_config_path()의 반환값을 resolved에 대입합니다.
            resolved = _normalize_config_path(executable)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not resolved.is_absolute() or not
            # resolved.is_file().
            if not resolved.is_absolute() or not resolved.is_file():
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ConfigError(
                    "app_map의 실행 파일이 존재하지 않습니다.",
                    {"tool": tool.name, "app": app_name, "path": str(resolved)},
                )


# _validate_policy_contracts(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: settings, policies, registered_tools.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def _validate_policy_contracts(
    settings: Settings,
    policies: Policies,
    *,
    registered_tools: set[str] | None,
) -> None:
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if (
        settings.voice.tts.engine == "edge-tts"
        and not policies.privacy.api_transmission.services.online_tts
    ):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "edge-tts를 사용하려면 privacy의 online_tts 전송을 명시적으로 허용해야 합니다.",
            {"field": "api_transmission.services.online_tts"},
        )

    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: registered_tools is not None.
    if registered_tools is not None:
        # 오른쪽 식을 계산한 값을 configured에 대입합니다.
        # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
        configured = {tool.name for tool in policies.tools.tools if tool.enabled}
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: configured != registered_tools.
        if configured != registered_tools:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ConfigError(
                "활성화된 도구 설정과 코드 registry가 일치하지 않습니다.",
                {
                    "missing_in_registry": sorted(configured - registered_tools),
                    "missing_in_config": sorted(registered_tools - configured),
                },
            )


# _normalize_config_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: Path.
def _normalize_config_path(path: str | Path) -> Path:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return Path(os.path.expandvars(str(path))).expanduser().resolve(strict=False)


# _resolve_inside(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: root, configured, field.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: Path.
def _resolve_inside(root: Path, configured: Path, *, field: str) -> Path:
    # 아래 함수()의 반환값을 expanded에 대입합니다.
    expanded = Path(os.path.expandvars(str(configured))).expanduser()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: expanded.is_absolute().
    if expanded.is_absolute():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "data_root 하위 경로에는 절대 경로를 사용할 수 없습니다.",
            {"field": field, "path": str(expanded)},
        )
    # (root / expanded).resolve()의 반환값을 resolved에 대입합니다.
    resolved = (root / expanded).resolve(strict=False)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not resolved.is_relative_to(root).
    if not resolved.is_relative_to(root):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ConfigError(
            "설정 경로가 data_root 밖을 가리킵니다.",
            {"field": field, "path": str(resolved)},
        )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return resolved
