"""Tests for deterministic local voice-model setup."""

from pathlib import Path

import pytest

from scripts import setup_voice

huggingface_hub = pytest.importorskip("huggingface_hub")


def _write_required_model_files(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for relative in setup_voice.WHISPER_REQUIRED_FILES:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")


def test_install_whisper_downloads_exact_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, object] = {}

    def fake_snapshot_download(**kwargs: object) -> str:
        received.update(kwargs)
        target = Path(str(kwargs["local_dir"]))
        _write_required_model_files(target)
        return str(target)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(setup_voice, "_sha256", lambda _path: setup_voice.WHISPER_MODEL_SHA256)

    target = setup_voice.install_whisper(tmp_path)

    assert target == tmp_path / setup_voice.WHISPER_MODEL_NAME
    assert received["repo_id"] == setup_voice.WHISPER_REPO_ID
    assert received["revision"] == setup_voice.WHISPER_REVISION
    assert received["local_dir"] == target


def test_install_whisper_rejects_wrong_model_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / setup_voice.WHISPER_MODEL_NAME
    _write_required_model_files(target)
    monkeypatch.setattr(setup_voice, "_sha256", lambda _path: "0" * 64)

    with pytest.raises(RuntimeError, match="SHA-256"):
        setup_voice.install_whisper(tmp_path)
