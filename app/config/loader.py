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

_CONFIG_FILENAMES = ("settings.yaml", "tools.yaml", "privacy.yaml")
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
_ROOT_SETTINGS_FIELDS = {
    "docs": "docs_dir",
    "notes": "notes_dir",
    "memory_export": "export_dir",
}

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_settings(
    path: Path,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Load settings.yaml and validate its local filesystem contract."""
    document = _read_yaml_mapping(path)
    _apply_overrides(document, overrides)
    settings = _validate_model(Settings, document, path)
    return _validate_settings_paths(settings, source=path)


def load_policies(
    tools_path: Path,
    privacy_path: Path,
    *,
    settings: Settings,
    overrides: Mapping[str, Any] | None = None,
    registered_tools: set[str] | None = None,
) -> Policies:
    """Load both policy files and enforce their cross-file constraints."""
    tools_document = _read_yaml_mapping(tools_path)
    privacy_document = _read_yaml_mapping(privacy_path)
    _apply_policy_overrides(tools_document, privacy_document, overrides)

    tools = _validate_model(ToolPolicy, tools_document, tools_path)
    privacy = _validate_model(PrivacyPolicy, privacy_document, privacy_path)
    policies = Policies(tools=tools, privacy=privacy)
    _validate_policy_paths(settings, policies)
    _validate_policy_contracts(settings, policies, registered_tools=registered_tools)
    return policies


def load_config(
    config_dir: Path = DEFAULT_CONFIG_DIR,
    *,
    registered_tools: set[str] | None = None,
) -> LoadedConfig:
    """Load the operational configuration directory as one immutable bundle.

    Missing files mean bootstrap has not run. Unknown YAML keys are rejected by
    the Pydantic models (``extra="forbid"``), not by this function.
    """
    directory = Path(config_dir)
    if not directory.is_dir():
        raise ConfigError(
            "설정 디렉터리가 없습니다. 먼저 python scripts\\bootstrap.py를 실행하세요.",
            {"config_dir": str(directory), "reason": "missing_config_directory"},
        )

    missing = [name for name in _CONFIG_FILENAMES if not (directory / name).is_file()]
    if missing:
        raise ConfigError(
            "운영 설정 파일이 없습니다. 먼저 python scripts\\bootstrap.py를 실행하세요.",
            {"config_dir": str(directory), "missing": missing},
        )

    settings = load_settings(directory / "settings.yaml")
    policies = load_policies(
        directory / "tools.yaml",
        directory / "privacy.yaml",
        settings=settings,
        registered_tools=registered_tools,
    )
    return LoadedConfig(
        settings=settings,
        policies=policies,
        config_hash=calculate_config_hash(settings, policies),
    )


def calculate_config_hash(settings: Settings, policies: Policies) -> str:
    """Return a stable SHA-256 over the effective three-file configuration."""
    merged = {
        "privacy": policies.privacy.model_dump(mode="json", by_alias=True),
        "settings": settings.model_dump(mode="json", by_alias=True),
        "tools": policies.tools.model_dump(mode="json", by_alias=True),
    }
    canonical = json.dumps(
        merged,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
    except FileNotFoundError as error:
        raise ConfigError(
            f"설정 파일 {path.name}이 없습니다. bootstrap을 먼저 실행하세요.",
            {"file": str(path), "reason": "missing_file"},
        ) from error
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ConfigError(
            f"설정 파일 {path.name}을 읽을 수 없습니다.",
            {"file": str(path), "error_type": type(error).__name__},
        ) from error

    if not isinstance(document, dict):
        raise ConfigError(
            f"설정 파일 {path.name}의 최상위 값은 객체여야 합니다.",
            {"file": str(path), "reason": "root_not_mapping"},
        )
    return document


def _validate_model(model_type: type[ModelT], document: dict[str, Any], path: Path) -> ModelT:
    try:
        return model_type.model_validate(document)
    except ValidationError as error:
        raise ConfigError(
            f"설정 파일 {path.name}의 값이 올바르지 않습니다.",
            {
                "file": str(path),
                "errors": error.errors(include_input=False, include_url=False),
            },
        ) from error


def _apply_overrides(
    document: dict[str, Any],
    overrides: Mapping[str, Any] | None,
) -> None:
    for dotted_key, value in (overrides or {}).items():
        _set_existing_dotted_value(document, dotted_key, deepcopy(value))


def _apply_policy_overrides(
    tools_document: dict[str, Any],
    privacy_document: dict[str, Any],
    overrides: Mapping[str, Any] | None,
) -> None:
    for dotted_key, value in (overrides or {}).items():
        if dotted_key == "tools.app_map":
            definitions = tools_document.get("tools")
            if not isinstance(definitions, list):
                raise ConfigError("tools 정책의 도구 목록이 올바르지 않습니다.")
            open_app = next(
                (
                    item
                    for item in definitions
                    if isinstance(item, dict) and item.get("name") == "open_app"
                ),
                None,
            )
            if open_app is None:
                raise ConfigError("tools 정책에 open_app 정의가 없습니다.")
            open_app["app_map"] = deepcopy(value)
        elif dotted_key.startswith("tools."):
            _set_existing_dotted_value(
                tools_document,
                dotted_key.removeprefix("tools."),
                deepcopy(value),
            )
        elif dotted_key.startswith("privacy."):
            _set_existing_dotted_value(
                privacy_document,
                dotted_key.removeprefix("privacy."),
                deepcopy(value),
            )
        else:
            raise ConfigError(
                "정책 override는 tools. 또는 privacy.로 시작해야 합니다.",
                {"override": dotted_key},
            )


def _set_existing_dotted_value(document: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    current: Any = document
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ConfigError(
                "존재하지 않는 설정 override 경로입니다.",
                {"override": dotted_key},
            )
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise ConfigError(
            "존재하지 않는 설정 override 경로입니다.",
            {"override": dotted_key},
        )
    current[parts[-1]] = value


def _validate_settings_paths(settings: Settings, *, source: Path) -> Settings:
    root = _normalize_config_path(settings.paths.data_root)
    if not root.is_absolute():
        raise ConfigError(
            "settings.paths.data_root는 절대 경로여야 합니다.",
            {"file": str(source), "field": "paths.data_root"},
        )
    if not root.is_dir():
        raise ConfigError(
            "settings.paths.data_root가 존재하는 디렉터리가 아닙니다.",
            {"file": str(source), "field": "paths.data_root", "path": str(root)},
        )
    if not os.access(root, os.W_OK):
        raise ConfigError(
            "settings.paths.data_root에 쓸 수 없습니다.",
            {"file": str(source), "field": "paths.data_root", "path": str(root)},
        )

    for field_name in _SETTINGS_RELATIVE_PATHS:
        configured = getattr(settings.paths, field_name)
        _resolve_inside(root, configured, field=f"paths.{field_name}")

    normalized_paths = settings.paths.model_copy(update={"data_root": root})
    return settings.model_copy(update={"paths": normalized_paths})


def _validate_policy_paths(settings: Settings, policies: Policies) -> None:
    root = settings.paths.data_root.resolve(strict=False)
    sandbox = policies.tools.sandbox

    for index, configured in enumerate(sandbox.write_roots):
        _resolve_inside(root, configured, field=f"sandbox.write_roots[{index}]")
    for index, configured in enumerate(sandbox.read_roots):
        _resolve_inside(root, configured, field=f"sandbox.read_roots[{index}]")

    for name, configured in sandbox.roots.items():
        resolved = _resolve_inside(root, configured, field=f"sandbox.roots.{name}")
        settings_field = _ROOT_SETTINGS_FIELDS.get(name)
        if settings_field is None:
            raise ConfigError(
                "sandbox.roots의 이름에 대응하는 settings 경로가 없습니다.",
                {"root_name": name},
            )
        expected = _resolve_inside(
            root,
            getattr(settings.paths, settings_field),
            field=f"paths.{settings_field}",
        )
        if resolved != expected:
            raise ConfigError(
                "sandbox.roots와 settings.paths가 서로 다른 위치를 가리킵니다.",
                {"root_name": name, "settings_field": settings_field},
            )

    for index, denied_configured in enumerate(sandbox.deny_paths):
        denied = _normalize_config_path(denied_configured)
        if not denied.is_absolute():
            raise ConfigError(
                "sandbox.deny_paths에는 절대 경로만 사용할 수 있습니다.",
                {"field": f"sandbox.deny_paths[{index}]"},
            )

    for tool in policies.tools.tools:
        for app_name, executable in (tool.app_map or {}).items():
            resolved = _normalize_config_path(executable)
            if not resolved.is_absolute() or not resolved.is_file():
                raise ConfigError(
                    "app_map의 실행 파일이 존재하지 않습니다.",
                    {"tool": tool.name, "app": app_name, "path": str(resolved)},
                )


def _validate_policy_contracts(
    settings: Settings,
    policies: Policies,
    *,
    registered_tools: set[str] | None,
) -> None:
    if ".pdf" in {extension.lower() for extension in settings.rag.supported_extensions}:
        raise ConfigError(
            "PDF parser가 결정되지 않아 .pdf 확장자를 활성화할 수 없습니다.",
            {"field": "rag.supported_extensions"},
        )

    if (
        settings.voice.tts.engine == "edge-tts"
        and not policies.privacy.api_transmission.services.online_tts
    ):
        raise ConfigError(
            "edge-tts를 사용하려면 privacy의 online_tts 전송을 명시적으로 허용해야 합니다.",
            {"field": "api_transmission.services.online_tts"},
        )

    if registered_tools is not None:
        configured = {tool.name for tool in policies.tools.tools if tool.enabled}
        if configured != registered_tools:
            raise ConfigError(
                "활성화된 도구 설정과 코드 registry가 일치하지 않습니다.",
                {
                    "missing_in_registry": sorted(configured - registered_tools),
                    "missing_in_config": sorted(registered_tools - configured),
                },
            )


def _normalize_config_path(path: str | Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser().resolve(strict=False)


def _resolve_inside(root: Path, configured: Path, *, field: str) -> Path:
    expanded = Path(os.path.expandvars(str(configured))).expanduser()
    if expanded.is_absolute():
        raise ConfigError(
            "data_root 하위 경로에는 절대 경로를 사용할 수 없습니다.",
            {"field": field, "path": str(expanded)},
        )
    resolved = (root / expanded).resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ConfigError(
            "설정 경로가 data_root 밖을 가리킵니다.",
            {"field": field, "path": str(resolved)},
        )
    return resolved
