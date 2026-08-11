"""Configuration tests for the explicitly local voice mode."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from app.config.loader import load_config
from app.core.errors import ConfigError
from scripts.bootstrap import create_tree

pytestmark = pytest.mark.phase7
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "config"
    destination.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )
    root = tmp_path / "Jarvis"
    create_tree(root)
    settings_path = destination / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["paths"]["data_root"] = str(root)
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return destination


def test_local_wake_word_configuration_loads(config_dir: Path) -> None:
    settings = load_config(config_dir).settings

    assert settings.voice.enabled is True
    assert settings.voice.wake_word == "자비스"
    assert settings.voice.acknowledgement == "무엇을 도와드릴까요."
    assert settings.voice.stt.engine == "hybrid"
    assert settings.voice.stt.wake.engine == "vosk"
    assert settings.voice.stt.command.engine == "faster-whisper"
    assert settings.voice.stt.command.model == "faster-whisper-small"
    assert settings.voice.stt.command.device == "cuda"
    assert settings.voice.barge_in.enabled is True
    assert settings.voice.barge_in.speech_threshold_dbfs == -32
    assert settings.voice.barge_in.min_onset_rise_db == 8
    assert settings.voice.barge_in.vad_mode == 2
    assert settings.voice.barge_in.interrupt_hotkey_enabled is True
    assert settings.voice.barge_in.interrupt_hotkey == "ctrl+alt+j"
    assert settings.voice.tts.voice == "Microsoft Heami Desktop"
    assert settings.voice.tts.rate == 4


def test_enabled_voice_rejects_non_local_tts(config_dir: Path) -> None:
    settings_path = config_dir / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["voice"]["tts"]["engine"] = "edge-tts"
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("speech_threshold_dbfs", -97),
        ("min_onset_rise_db", 97),
        ("vad_mode", 4),
        ("vad_frame_ms", 25),
        ("vad_min_voiced_ratio", 0),
    ],
)
def test_barge_in_gate_rejects_invalid_settings(
    config_dir: Path,
    field: str,
    value: float,
) -> None:
    settings_path = config_dir / "settings.yaml"
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    document["voice"]["barge_in"][field] = value
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ConfigError):
        load_config(config_dir)
