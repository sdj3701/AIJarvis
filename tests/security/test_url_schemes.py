"""URL scheme blocking for fetch_url validation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config.loader import load_policies, load_settings
from app.core.errors import PolicyDenied
from app.rag.fetcher import UrlFetcher

pytestmark = [pytest.mark.phase3, pytest.mark.security]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

SCHEME_CORPUS = Path(__file__).resolve().parents[1] / "data" / "web" / "scheme_corpus.txt"


@pytest.fixture
def fetcher(tmp_path: Path) -> UrlFetcher:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("settings", "tools", "privacy"):
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    settings = load_settings(config_dir / "settings.yaml")
    policies = load_policies(
        config_dir / "tools.yaml",
        config_dir / "privacy.yaml",
        settings=settings,
    )
    return UrlFetcher(
        fetch_settings=settings.rag.fetch,
        network=policies.tools.network,
    )


def test_scheme_corpus_blocked(fetcher: UrlFetcher) -> None:
    urls = SCHEME_CORPUS.read_text(encoding="utf-8").splitlines()
    for url in urls:
        url = url.strip()
        if not url or url.startswith("#"):
            continue
        with pytest.raises(PolicyDenied):
            fetcher.validate_url(url)
