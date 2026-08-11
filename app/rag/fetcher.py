"""SSRF-safe HTTP fetcher for untrusted web content."""

from __future__ import annotations

import html
import http.client
import ipaddress
import re
import socket
import ssl
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse

from app.config.models import FetchSettings, NetworkPolicy
from app.core.errors import JarvisError, PolicyDenied
from app.rag.models import FetchedDocument

_SCRIPT_RE = re.compile(r"(?is)<script[^>]*>.*?</script>")
_STYLE_RE = re.compile(r"(?is)<style[^>]*>.*?</style>")
_FORM_RE = re.compile(r"(?is)<form[^>]*>.*?</form>")
_TAG_RE = re.compile(r"(?is)<[^>]+>")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")


class FetchFailed(JarvisError):
    """HTTP fetch failed or response violated policy."""


@dataclass(frozen=True, slots=True)
class UrlFetcher:
    fetch_settings: FetchSettings
    network: NetworkPolicy

    def fetch(self, url: str, *, timeout_s: float | None = None) -> FetchedDocument:
        timeout = timeout_s if timeout_s is not None else self.fetch_settings.timeout_s
        deadline = time.monotonic() + timeout
        requested = url.strip()
        current = requested
        redirects = 0
        while True:
            connect_ip = self._validate_url(current)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchFailed("URL 가져오기 시간이 초과되었습니다.")
            response = _open(current, timeout=remaining, connect_ip=connect_ip)
            try:
                if 300 <= response.status < 400:
                    location = response.headers.get("Location")
                    if location is None:
                        raise FetchFailed("리다이렉트 Location 헤더가 없습니다.")
                    redirects += 1
                    if redirects > self.fetch_settings.max_redirects:
                        raise PolicyDenied("리다이렉트 횟수 한도를 초과했습니다.")
                    current = urljoin(current, location)
                    continue
                if response.status >= 400:
                    raise FetchFailed(
                        f"HTTP {response.status} 응답으로 본문을 가져올 수 없습니다.",
                        {"status": response.status, "url": current},
                    )
                content_type = _normalize_content_type(
                    response.headers.get("Content-Type", "")
                )
                if content_type not in self.fetch_settings.allowed_content_types:
                    raise PolicyDenied(
                        "허용되지 않은 Content-Type입니다.",
                        {"content_type": content_type},
                    )
                body, truncated = _read_limited(response, self.fetch_settings.max_bytes)
            finally:
                response.close()
            fetched_at = datetime.now().astimezone()
            title, text = _extract_text(body, content_type)
            return FetchedDocument(
                requested_url=requested,
                final_url=current,
                title=title,
                content=text,
                content_type=content_type,
                fetched_at=fetched_at,
                truncated=truncated,
            )

    def validate_url(self, url: str) -> None:
        self._validate_url(url)

    def _validate_url(self, url: str) -> str:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in self.network.allowed_schemes:
            raise PolicyDenied(f"허용되지 않은 URL 스킴입니다: {scheme or '(없음)'}")
        if self.network.deny_credentials_in_url and (parsed.username or parsed.password):
            raise PolicyDenied("URL에 자격증명을 포함할 수 없습니다.")
        host = parsed.hostname
        if host is None:
            raise PolicyDenied("URL 호스트가 없습니다.")
        lowered = host.lower()
        if lowered.endswith(".local"):
            raise PolicyDenied("로컬 호스트 이름은 차단됩니다.")
        if self.network.deny_mixed_script_idn and _has_mixed_script(lowered):
            raise PolicyDenied("혼합 스크립트 IDN 호스트는 차단됩니다.")
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as error:
            raise PolicyDenied("URL 포트가 올바르지 않습니다.") from error
        return self._validate_host_ip(lowered, port)

    def _validate_host_ip(self, host: str, port: int) -> str:
        if host == "localhost":
            if self.network.deny_loopback:
                raise PolicyDenied("loopback 호스트는 차단됩니다.")
            return "127.0.0.1"
        try:
            literal_ip = ipaddress.ip_address(host)
        except ValueError:
            literal_ip = None
        if literal_ip is not None:
            self._assert_ip_allowed(literal_ip)
            return str(literal_ip)
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            raise PolicyDenied("호스트 이름을 확인할 수 없습니다.") from error
        validated: list[str] = []
        for info in infos:
            ip_text = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_text)
            except ValueError as error:
                raise PolicyDenied("호스트 IP 형식이 올바르지 않습니다.") from error
            self._assert_ip_allowed(ip)
            validated.append(str(ip))
        if not validated:
            raise PolicyDenied("호스트 IP를 확인할 수 없습니다.")
        # 검증한 주소를 실제 연결에 그대로 사용해 DNS rebinding을 막는다.
        return validated[0]

    def _assert_ip_allowed(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        if self.network.deny_loopback and ip.is_loopback:
            raise PolicyDenied("loopback IP는 차단됩니다.")
        if self.network.deny_private_ranges and (
            ip.is_private or ip.is_link_local or ip.is_reserved
        ):
            raise PolicyDenied("사설·링크로컬 IP는 차단됩니다.")


def _normalize_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _read_limited(response: http.client.HTTPResponse, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    while True:
        piece = response.read(65536)
        if not piece:
            break
        total += len(piece)
        if total > max_bytes:
            allowed = max_bytes - (total - len(piece))
            if allowed > 0:
                chunks.append(piece[:allowed])
            truncated = True
            break
        chunks.append(piece)
    return b"".join(chunks), truncated


def _open(url: str, *, timeout: float, connect_ip: str) -> http.client.HTTPResponse:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    if host is None:
        raise PolicyDenied("URL 호스트가 없습니다.")
    ascii_host = host.encode("idna").decode("ascii")
    port = parsed.port or (443 if scheme == "https" else 80)
    default_port = 443 if scheme == "https" else 80
    host_header = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    if port != default_port:
        host_header = f"{host_header}:{port}"
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if parsed.query:
        path += "?" + quote(parsed.query, safe="=&%:@!$'()*+,;/?-._~")

    connection: http.client.HTTPConnection
    if scheme == "https":
        connection = _PinnedHTTPSConnection(
            ascii_host,
            port,
            connect_ip=connect_ip,
            timeout=timeout,
        )
    else:
        connection = _PinnedHTTPConnection(
            ascii_host,
            port,
            connect_ip=connect_ip,
            timeout=timeout,
        )
    try:
        connection.request(
            "GET",
            path,
            headers={"Host": host_header, "User-Agent": "Jarvis/0.0"},
        )
        return connection.getresponse()
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        connection.close()
        raise FetchFailed("URL을 열 수 없습니다.", {"url": url}) from error


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_ip: str,
        timeout: float,
    ) -> None:
        super().__init__(host, port, timeout=timeout)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_ip: str,
        timeout: float,
    ) -> None:
        context = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=context)
        self._connect_ip = connect_ip
        self._ssl_context = context

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
        )
        self.sock = self._ssl_context.wrap_socket(self.sock, server_hostname=self.host)


def _extract_text(body: bytes, content_type: str) -> tuple[str, str]:
    text = body.decode("utf-8", errors="replace")
    if content_type == "text/html":
        title_match = _TITLE_RE.search(text)
        title = html.unescape(title_match.group(1).strip()) if title_match else ""
        cleaned = _SCRIPT_RE.sub(" ", text)
        cleaned = _STYLE_RE.sub(" ", cleaned)
        cleaned = _FORM_RE.sub(" ", cleaned)
        cleaned = _TAG_RE.sub(" ", cleaned)
        cleaned = html.unescape(re.sub(r"\s+", " ", cleaned)).strip()
        return title, cleaned
    if content_type in {"text/plain", "text/markdown", "application/json"}:
        return "", text.strip()
    return "", text.strip()


def _has_mixed_script(host: str) -> bool:
    try:
        decoded = host.encode("ascii").decode("idna")
    except UnicodeError:
        decoded = host
    scripts: set[str] = set()
    for char in decoded:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        if "LATIN" in name:
            scripts.add("LATIN")
        elif "CYRILLIC" in name:
            scripts.add("CYRILLIC")
        elif "GREEK" in name:
            scripts.add("GREEK")
        else:
            scripts.add(name.split()[0] if name else "OTHER")
    return len(scripts) > 1 and "LATIN" in scripts
