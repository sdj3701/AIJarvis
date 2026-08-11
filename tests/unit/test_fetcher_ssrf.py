"""SSRF protections for URL fetcher."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from app.config.loader import load_policies, load_settings
from app.core.errors import PolicyDenied
from app.rag import fetcher as fetcher_module
from app.rag.fetcher import UrlFetcher

pytestmark = [pytest.mark.phase3, pytest.mark.security]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/System32/config/SAM",
        "javascript:alert(1)",
        "http://127.0.0.1:8080/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://user:pass@example.com/",
        "http://\u0430pple.com/",
        "http://xn--pple-43d.com/",
    ],
)
def test_blocked_urls(fetcher: UrlFetcher, url: str) -> None:
    with pytest.raises(PolicyDenied):
        fetcher.validate_url(url)


class FakeResponse:
    def __init__(
        self,
        status: int,
        *,
        headers: dict[str, str],
        body: bytes = b"",
    ) -> None:
        self.status = status
        self.headers = headers
        self._body = body
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        del size
        body, self._body = self._body, b""
        return body

    def close(self) -> None:
        self.closed = True


def test_validated_dns_address_is_pinned_to_connection(
    fetcher: UrlFetcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fetcher_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    captured: list[tuple[str, str]] = []

    def fake_open(url: str, *, timeout: float, connect_ip: str) -> Any:
        assert timeout > 0
        captured.append((url, connect_ip))
        return FakeResponse(200, headers={"Content-Type": "text/plain"}, body=b"ok")

    monkeypatch.setattr(fetcher_module, "_open", fake_open)
    document = fetcher.fetch("http://example.com/")

    assert document.content == "ok"
    assert captured == [("http://example.com/", "93.184.216.34")]


def test_redirect_to_private_address_is_rejected_before_second_connection(
    fetcher: UrlFetcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fetcher_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    calls = 0

    def fake_open(url: str, *, timeout: float, connect_ip: str) -> Any:
        nonlocal calls
        del url, timeout, connect_ip
        calls += 1
        return FakeResponse(302, headers={"Location": "http://127.0.0.1/admin"})

    monkeypatch.setattr(fetcher_module, "_open", fake_open)
    with pytest.raises(PolicyDenied):
        fetcher.fetch("http://example.com/start")

    assert calls == 1
