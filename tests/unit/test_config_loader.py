"""Tests for strict loading of the three Jarvis configuration files."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config.loader import load_config, load_policies, load_settings
from app.core.errors import ConfigError

pytestmark = pytest.mark.phase0

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Copy the examples and point them at a writable temporary data root."""
    destination = tmp_path / "config"
    destination.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPO_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )

    data_root = tmp_path / "JarvisTest"
    data_root.mkdir()
    _mutate_yaml(
        destination / "settings.yaml",
        lambda document: document["paths"].__setitem__("data_root", str(data_root)),
    )
    return destination


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    assert isinstance(document, dict)
    return document


def _mutate_yaml(path: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    document = _load_yaml(path)
    mutation(document)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(document, stream, allow_unicode=True, sort_keys=False)


def _tool_definition(document: dict[str, Any], name: str) -> dict[str, Any]:
    for tool in document["tools"]:
        if tool["name"] == name:
            return tool
    raise AssertionError(f"missing tool fixture: {name}")


def test_example_yaml_files_load(config_dir: Path) -> None:
    loaded = load_config(config_dir)

    assert loaded.settings.schema_version == 1
    assert loaded.policies.tools.default == "deny"
    assert loaded.policies.privacy.api_transmission.default == "deny"
    assert len(loaded.config_hash) == 64
    assert set(loaded.config_hash) <= set("0123456789abcdef")


def test_missing_config_directory_reports_bootstrap(config_dir: Path) -> None:
    missing = config_dir.parent / "missing"

    with pytest.raises(ConfigError, match="bootstrap") as error:
        load_config(missing)

    assert "bootstrap" in error.value.user_message


def test_data_root_must_exist(config_dir: Path) -> None:
    missing = config_dir.parent / "missing-data-root"
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["paths"].__setitem__("data_root", str(missing)),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_settings_path_cannot_escape_data_root(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["paths"].__setitem__("docs_dir", "..\\outside"),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_unknown_key_rejected(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["llm"]["context"].__setitem__("typo_share", 0.1),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


@pytest.mark.parametrize("filename", ["settings.yaml", "tools.yaml", "privacy.yaml"])
def test_newer_schema_version_rejected(config_dir: Path, filename: str) -> None:
    _mutate_yaml(
        config_dir / filename,
        lambda document: document.__setitem__("schema_version", 2),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


@pytest.mark.parametrize(
    ("filename", "mutation"),
    [
        ("tools.yaml", lambda document: document.__setitem__("default", "allow")),
        (
            "privacy.yaml",
            lambda document: document["api_transmission"].__setitem__("default", "allow"),
        ),
    ],
)
def test_cannot_disable_default_deny(
    config_dir: Path,
    filename: str,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    _mutate_yaml(config_dir / filename, mutation)

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_write_root_outside_data_root_rejected(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "tools.yaml",
        lambda document: document["sandbox"].__setitem__("write_roots", ["..\\outside"]),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_absolute_sandbox_root_rejected(config_dir: Path) -> None:
    absolute = config_dir.parent / "absolute"
    _mutate_yaml(
        config_dir / "tools.yaml",
        lambda document: document["sandbox"].__setitem__("read_roots", [str(absolute)]),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_context_share_sum_over_one_rejected(config_dir: Path) -> None:
    def make_invalid(document: dict[str, Any]) -> None:
        document["llm"]["context"]["memory_share"] = 0.6
        document["llm"]["context"]["history_share"] = 0.5

    _mutate_yaml(config_dir / "settings.yaml", make_invalid)

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_cannot_weaken_budget_on_exceed(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["budget"].__setitem__("on_exceed", "warn_only"),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_budget_limit_is_required(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["budget"].pop("daily_limit"),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_pricing_must_contain_selected_model(config_dir: Path) -> None:
    def remove_selected_model(document: dict[str, Any]) -> None:
        model = document["llm"]["model"]
        document["llm"]["pricing"].pop(model)

    _mutate_yaml(config_dir / "settings.yaml", remove_selected_model)

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_pdf_cannot_be_enabled_without_parser(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["rag"]["supported_extensions"].append(".pdf"),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_sandbox_root_mapping_must_match_settings(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "tools.yaml",
        lambda document: document["sandbox"]["roots"].__setitem__("notes", "docs\\other"),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


@pytest.mark.parametrize("field", ["risk", "execution_mode"])
def test_tool_risk_and_execution_mode_are_required(config_dir: Path, field: str) -> None:
    def remove_field(document: dict[str, Any]) -> None:
        _tool_definition(document, "web_search").pop(field)

    _mutate_yaml(config_dir / "tools.yaml", remove_field)

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_run_skill_must_be_managed(config_dir: Path) -> None:
    def weaken_execution_mode(document: dict[str, Any]) -> None:
        _tool_definition(document, "run_skill")["execution_mode"] = "in_process"

    _mutate_yaml(config_dir / "tools.yaml", weaken_execution_mode)

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_open_app_must_be_detached_allowlisted(config_dir: Path) -> None:
    def weaken_execution_mode(document: dict[str, Any]) -> None:
        _tool_definition(document, "open_app")["execution_mode"] = "managed_process"

    _mutate_yaml(config_dir / "tools.yaml", weaken_execution_mode)

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_open_app_executable_must_exist(config_dir: Path) -> None:
    def set_missing_executable(document: dict[str, Any]) -> None:
        _tool_definition(document, "open_app")["app_map"] = {
            "missing": str(config_dir.parent / "missing.exe")
        }

    _mutate_yaml(config_dir / "tools.yaml", set_missing_executable)

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_privacy_requires_secret_detector(config_dir: Path) -> None:
    def remove_secret_detectors(document: dict[str, Any]) -> None:
        document["detectors"] = [
            detector for detector in document["detectors"] if detector["kind"] != "secret"
        ]

    _mutate_yaml(config_dir / "privacy.yaml", remove_secret_detectors)

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_memory_write_refusal_cannot_be_empty(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "privacy.yaml",
        lambda document: document["outputs"]["memory_write"].__setitem__("refuse_kinds", []),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_external_service_configuration_is_required(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "privacy.yaml",
        lambda document: document["api_transmission"]["services"].pop("llm"),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_online_tts_requires_transmission_permission(config_dir: Path) -> None:
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["voice"]["tts"].__setitem__("engine", "edge-tts"),
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_registered_tools_must_match_enabled_policy(config_dir: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(config_dir, registered_tools=set())


def test_documented_settings_overrides(config_dir: Path) -> None:
    settings = load_settings(
        config_dir / "settings.yaml",
        overrides={
            "dev_mode": True,
            "llm.model": "fake-model",
            "llm.pricing": {
                "fake-model": {"input_per_1k": "0.001", "output_per_1k": "0.002"}
            },
        },
    )

    assert settings.dev_mode is True
    assert settings.llm.model == "fake-model"


def test_documented_app_map_override(config_dir: Path) -> None:
    fake_executable = config_dir.parent / "fake.exe"
    fake_executable.touch()
    settings = load_settings(config_dir / "settings.yaml")

    policies = load_policies(
        config_dir / "tools.yaml",
        config_dir / "privacy.yaml",
        settings=settings,
        overrides={"tools.app_map": {"fake": str(fake_executable)}},
    )

    open_app = next(tool for tool in policies.tools.tools if tool.name == "open_app")
    assert open_app.app_map == {"fake": fake_executable}


def test_config_hash_is_stable_and_tracks_changes(config_dir: Path) -> None:
    first = load_config(config_dir)
    second = load_config(config_dir)
    assert first.config_hash == second.config_hash

    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["metrics"].__setitem__("p95_window", 201),
    )
    changed = load_config(config_dir)

    assert changed.config_hash != first.config_hash
