# 파이썬 공부 | scripts/app/rag/fetcher.py
# 웹 자료를 가져오되 내부망 등 허용되지 않는 주소 접근을 검사합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# re.compile()의 반환값을 _SCRIPT_RE에 대입합니다.
_SCRIPT_RE = re.compile(r"(?is)<script[^>]*>.*?</script>")
# re.compile()의 반환값을 _STYLE_RE에 대입합니다.
_STYLE_RE = re.compile(r"(?is)<style[^>]*>.*?</style>")
# re.compile()의 반환값을 _FORM_RE에 대입합니다.
_FORM_RE = re.compile(r"(?is)<form[^>]*>.*?</form>")
# re.compile()의 반환값을 _TAG_RE에 대입합니다.
_TAG_RE = re.compile(r"(?is)<[^>]+>")
# re.compile()의 반환값을 _TITLE_RE에 대입합니다.
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")


# FetchFailed: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class FetchFailed(JarvisError):
    """HTTP fetch failed or response violated policy."""


# UrlFetcher: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class UrlFetcher:
    # fetch_settings: FetchSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    fetch_settings: FetchSettings
    # network: NetworkPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    network: NetworkPolicy

    # fetch(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: url, timeout_s.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: FetchedDocument.
    def fetch(self, url: str, *, timeout_s: float | None = None) -> FetchedDocument:
        # 오른쪽 식을 계산한 값을 timeout에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        timeout = timeout_s if timeout_s is not None else self.fetch_settings.timeout_s
        # 오른쪽 식을 계산한 값을 deadline에 대입합니다.
        deadline = time.monotonic() + timeout
        # url.strip()의 반환값을 requested에 대입합니다.
        requested = url.strip()
        # 오른쪽 식을 계산한 값을 current에 대입합니다.
        current = requested
        # redirects에 숫자 등 고정된 값을 대입합니다.
        redirects = 0
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while True:
            # self._validate_url()의 반환값을 connect_ip에 대입합니다.
            connect_ip = self._validate_url(current)
            # 오른쪽 식을 계산한 값을 remaining에 대입합니다.
            remaining = deadline - time.monotonic()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: remaining <= 0.
            if remaining <= 0:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise FetchFailed("URL 가져오기 시간이 초과되었습니다.")
            # _open()의 반환값을 response에 대입합니다.
            response = _open(current, timeout=remaining, connect_ip=connect_ip)
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 300 <= response.status < 400.
                if 300 <= response.status < 400:
                    # response.headers.get()의 반환값을 location에 대입합니다.
                    location = response.headers.get("Location")
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: location is None.
                    if location is None:
                        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                        # 이동합니다.
                        raise FetchFailed("리다이렉트 Location 헤더가 없습니다.")
                    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
                    redirects += 1
                    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: redirects >
                    # self.fetch_settings.max_redirects.
                    if redirects > self.fetch_settings.max_redirects:
                        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                        # 이동합니다.
                        raise PolicyDenied("리다이렉트 횟수 한도를 초과했습니다.")
                    # urljoin()의 반환값을 current에 대입합니다.
                    current = urljoin(current, location)
                    # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                    continue
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: response.status >= 400.
                if response.status >= 400:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise FetchFailed(
                        f"HTTP {response.status} 응답으로 본문을 가져올 수 없습니다.",
                        {"status": response.status, "url": current},
                    )
                # _normalize_content_type()의 반환값을 content_type에 대입합니다.
                content_type = _normalize_content_type(
                    response.headers.get("Content-Type", "")
                )
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: content_type not in
                # self.fetch_settings.allowed_content_types.
                if content_type not in self.fetch_settings.allowed_content_types:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied(
                        "허용되지 않은 Content-Type입니다.",
                        {"content_type": content_type},
                    )
                # 언패킹: 오른쪽 결과를 순서대로 (body, truncated)에 나누어 담습니다.
                body, truncated = _read_limited(response, self.fetch_settings.max_bytes)
            # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
            finally:
                # 사용하던 연결이나 자원을 닫습니다.
                response.close()
            # datetime.now().astimezone()의 반환값을 fetched_at에 대입합니다.
            fetched_at = datetime.now().astimezone()
            # 언패킹: 오른쪽 결과를 순서대로 (title, text)에 나누어 담습니다.
            title, text = _extract_text(body, content_type)
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return FetchedDocument(
                requested_url=requested,
                final_url=current,
                title=title,
                content=text,
                content_type=content_type,
                fetched_at=fetched_at,
                truncated=truncated,
            )

    # validate_url(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: url.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def validate_url(self, url: str) -> None:
        # self._validate_url()으로 입력 형식과 허용 조건을 검사합니다.
        self._validate_url(url)

    # _validate_url(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: url.
    # 반환 타입 힌트: 문자열(str).
    def _validate_url(self, url: str) -> str:
        # urlparse()의 반환값을 parsed에 대입합니다.
        parsed = urlparse(url)
        # parsed.scheme.lower()의 반환값을 scheme에 대입합니다.
        scheme = parsed.scheme.lower()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: scheme not in
        # self.network.allowed_schemes.
        if scheme not in self.network.allowed_schemes:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(f"허용되지 않은 URL 스킴입니다: {scheme or '(없음)'}")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.network.deny_credentials_in_url and (parsed.username or parsed.password):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("URL에 자격증명을 포함할 수 없습니다.")
        # 오른쪽 식을 계산한 값을 host에 대입합니다.
        host = parsed.hostname
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: host is None.
        if host is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("URL 호스트가 없습니다.")
        # host.lower()의 반환값을 lowered에 대입합니다.
        lowered = host.lower()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lowered.endswith('.local').
        if lowered.endswith(".local"):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("로컬 호스트 이름은 차단됩니다.")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.network.deny_mixed_script_idn and
        # _has_mixed_script(lowered).
        if self.network.deny_mixed_script_idn and _has_mixed_script(lowered):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("혼합 스크립트 IDN 호스트는 차단됩니다.")
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # 오른쪽 식을 계산한 값을 port에 대입합니다.
            port = parsed.port or (443 if scheme == "https" else 80)
        # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ValueError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("URL 포트가 올바르지 않습니다.") from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._validate_host_ip(lowered, port)

    # _validate_host_ip(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: host, port.
    # 반환 타입 힌트: 문자열(str).
    def _validate_host_ip(self, host: str, port: int) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: host == 'localhost'.
        if host == "localhost":
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.network.deny_loopback.
            if self.network.deny_loopback:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("loopback 호스트는 차단됩니다.")
            # '127.0.0.1'을 반환하고 이 함수의 실행을 끝냅니다.
            return "127.0.0.1"
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # ipaddress.ip_address()의 반환값을 literal_ip에 대입합니다.
            literal_ip = ipaddress.ip_address(host)
        # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ValueError:
            # literal_ip을 아직 값이 없음을 뜻하는 None으로 설정합니다.
            literal_ip = None
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: literal_ip is not None.
        if literal_ip is not None:
            # self._assert_ip_allowed()을 호출해 작업을 수행합니다.
            self._assert_ip_allowed(literal_ip)
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return str(literal_ip)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # socket.getaddrinfo()의 반환값을 infos에 대입합니다.
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        # socket.gaierror를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except socket.gaierror as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("호스트 이름을 확인할 수 없습니다.") from error
        # validated에 리스트(순서가 있고 수정 가능)을 대입합니다.
        validated: list[str] = []
        # for 반복문: 대상의 항목을 하나씩 info에 대입하며 아래 블록을 실행합니다.
        for info in infos:
            # 오른쪽 식을 계산한 값을 ip_text에 대입합니다.
            ip_text = info[4][0]
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # ipaddress.ip_address()의 반환값을 ip에 대입합니다.
                ip = ipaddress.ip_address(ip_text)
            # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except ValueError as error:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("호스트 IP 형식이 올바르지 않습니다.") from error
            # self._assert_ip_allowed()을 호출해 작업을 수행합니다.
            self._assert_ip_allowed(ip)
            # 리스트 끝에 항목 하나를 추가합니다.
            validated.append(str(ip))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not validated.
        if not validated:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("호스트 IP를 확인할 수 없습니다.")
        # 검증한 주소를 실제 연결에 그대로 사용해 DNS rebinding을 막는다.
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return validated[0]

    # _assert_ip_allowed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: ip.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def _assert_ip_allowed(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self.network.deny_loopback and
        # ip.is_loopback.
        if self.network.deny_loopback and ip.is_loopback:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("loopback IP는 차단됩니다.")
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if self.network.deny_private_ranges and (
            ip.is_private or ip.is_link_local or ip.is_reserved
        ):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("사설·링크로컬 IP는 차단됩니다.")


# _normalize_content_type(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value.
# 반환 타입 힌트: 문자열(str).
def _normalize_content_type(value: str) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return value.split(";", 1)[0].strip().lower()


# _read_limited(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: response, max_bytes.
# 반환 타입 힌트: tuple[bytes, bool].
def _read_limited(response: http.client.HTTPResponse, max_bytes: int) -> tuple[bytes, bool]:
    # chunks에 리스트(순서가 있고 수정 가능)을 대입합니다.
    chunks: list[bytes] = []
    # total에 숫자 등 고정된 값을 대입합니다.
    total = 0
    # truncated을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
    truncated = False
    # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
    while True:
        # response.read()의 반환값을 piece에 대입합니다.
        piece = response.read(65536)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not piece.
        if not piece:
            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
            break
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        total += len(piece)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: total > max_bytes.
        if total > max_bytes:
            # 오른쪽 식을 계산한 값을 allowed에 대입합니다.
            allowed = max_bytes - (total - len(piece))
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: allowed > 0.
            if allowed > 0:
                # 리스트 끝에 항목 하나를 추가합니다.
                chunks.append(piece[:allowed])
            # truncated을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
            truncated = True
            # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
            break
        # 리스트 끝에 항목 하나를 추가합니다.
        chunks.append(piece)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return b"".join(chunks), truncated


# _open(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: url, timeout, connect_ip.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: http.client.HTTPResponse.
def _open(url: str, *, timeout: float, connect_ip: str) -> http.client.HTTPResponse:
    # urlparse()의 반환값을 parsed에 대입합니다.
    parsed = urlparse(url)
    # parsed.scheme.lower()의 반환값을 scheme에 대입합니다.
    scheme = parsed.scheme.lower()
    # 오른쪽 식을 계산한 값을 host에 대입합니다.
    host = parsed.hostname
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: host is None.
    if host is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise PolicyDenied("URL 호스트가 없습니다.")
    # host.encode('idna').decode()의 반환값을 ascii_host에 대입합니다.
    ascii_host = host.encode("idna").decode("ascii")
    # 오른쪽 식을 계산한 값을 port에 대입합니다.
    port = parsed.port or (443 if scheme == "https" else 80)
    # 오른쪽 식을 계산한 값을 default_port에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    default_port = 443 if scheme == "https" else 80
    # 오른쪽 식을 계산한 값을 host_header에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    host_header = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: port != default_port.
    if port != default_port:
        # 오른쪽 식을 계산한 값을 host_header에 대입합니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        host_header = f"{host_header}:{port}"
    # quote()의 반환값을 path에 대입합니다.
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: parsed.query.
    if parsed.query:
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        path += "?" + quote(parsed.query, safe="=&%:@!$'()*+,;/?-._~")

    # connection: http.client.HTTPConnection 타입을 기대하는 필드입니다. 이 줄만으로 값이
    # 대입되지는 않습니다.
    connection: http.client.HTTPConnection
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: scheme == 'https'.
    if scheme == "https":
        # _PinnedHTTPSConnection()의 반환값을 connection에 대입합니다.
        connection = _PinnedHTTPSConnection(
            ascii_host,
            port,
            connect_ip=connect_ip,
            timeout=timeout,
        )
    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
    else:
        # _PinnedHTTPConnection()의 반환값을 connection에 대입합니다.
        connection = _PinnedHTTPConnection(
            ascii_host,
            port,
            connect_ip=connect_ip,
            timeout=timeout,
        )
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # connection.request()을 호출해 작업을 수행합니다.
        connection.request(
            "GET",
            path,
            headers={"Host": host_header, "User-Agent": "Jarvis/0.0"},
        )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return connection.getresponse()
    # (OSError, http.client.HTTPException, ssl.SSLError)를 잡아 처리합니다. as 뒤의 이름에는
    # 발생한 예외 객체가 담깁니다.
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        # 사용하던 연결이나 자원을 닫습니다.
        connection.close()
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise FetchFailed("URL을 열 수 없습니다.", {"url": url}) from error


# _PinnedHTTPConnection: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: http.client.HTTPConnection.
class _PinnedHTTPConnection(http.client.HTTPConnection):
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: host, port, connect_ip, timeout.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_ip: str,
        timeout: float,
    ) -> None:
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__(host, port, timeout=timeout)
        # 오른쪽 식을 계산한 값을 self._connect_ip에 대입합니다.
        self._connect_ip = connect_ip

    # connect(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def connect(self) -> None:
        # socket.create_connection()의 반환값을 self.sock에 대입합니다.
        self.sock = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
        )


# _PinnedHTTPSConnection: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: http.client.HTTPSConnection.
class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: host, port, connect_ip, timeout.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_ip: str,
        timeout: float,
    ) -> None:
        # ssl.create_default_context()의 반환값을 context에 대입합니다.
        context = ssl.create_default_context()
        # super().__init__()을 호출해 작업을 수행합니다.
        super().__init__(host, port, timeout=timeout, context=context)
        # 오른쪽 식을 계산한 값을 self._connect_ip에 대입합니다.
        self._connect_ip = connect_ip
        # 오른쪽 식을 계산한 값을 self._ssl_context에 대입합니다.
        self._ssl_context = context

    # connect(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def connect(self) -> None:
        # socket.create_connection()의 반환값을 self.sock에 대입합니다.
        self.sock = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
        )
        # self._ssl_context.wrap_socket()의 반환값을 self.sock에 대입합니다.
        self.sock = self._ssl_context.wrap_socket(self.sock, server_hostname=self.host)


# _extract_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: body, content_type.
# 반환 타입 힌트: tuple[str, str].
def _extract_text(body: bytes, content_type: str) -> tuple[str, str]:
    # body.decode()의 반환값을 text에 대입합니다.
    text = body.decode("utf-8", errors="replace")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: content_type == 'text/html'.
    if content_type == "text/html":
        # _TITLE_RE.search()의 반환값을 title_match에 대입합니다.
        title_match = _TITLE_RE.search(text)
        # 오른쪽 식을 계산한 값을 title에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        title = html.unescape(title_match.group(1).strip()) if title_match else ""
        # _SCRIPT_RE.sub()의 반환값을 cleaned에 대입합니다.
        cleaned = _SCRIPT_RE.sub(" ", text)
        # _STYLE_RE.sub()의 반환값을 cleaned에 대입합니다.
        cleaned = _STYLE_RE.sub(" ", cleaned)
        # _FORM_RE.sub()의 반환값을 cleaned에 대입합니다.
        cleaned = _FORM_RE.sub(" ", cleaned)
        # _TAG_RE.sub()의 반환값을 cleaned에 대입합니다.
        cleaned = _TAG_RE.sub(" ", cleaned)
        # 아래 함수()의 반환값을 cleaned에 대입합니다.
        cleaned = html.unescape(re.sub(r"\s+", " ", cleaned)).strip()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return title, cleaned
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if content_type in {"text/plain", "text/markdown", "application/json"}:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return "", text.strip()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return "", text.strip()


# _has_mixed_script(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: host.
# 반환 타입 힌트: 참/거짓(bool).
def _has_mixed_script(host: str) -> bool:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # host.encode('ascii').decode()의 반환값을 decoded에 대입합니다.
        decoded = host.encode("ascii").decode("idna")
    # UnicodeError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except UnicodeError:
        # 오른쪽 식을 계산한 값을 decoded에 대입합니다.
        decoded = host
    # set()의 반환값을 scripts에 대입합니다.
    scripts: set[str] = set()
    # for 반복문: 대상의 항목을 하나씩 char에 대입하며 아래 블록을 실행합니다.
    for char in decoded:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not char.isalpha().
        if not char.isalpha():
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # unicodedata.name()의 반환값을 name에 대입합니다.
        name = unicodedata.name(char, "")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'LATIN' in name.
        if "LATIN" in name:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            scripts.add("LATIN")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'CYRILLIC' in name.
        elif "CYRILLIC" in name:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            scripts.add("CYRILLIC")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: 'GREEK' in name.
        elif "GREEK" in name:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            scripts.add("GREEK")
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # add 메서드를 호출해 항목이나 기록을 추가합니다.
            scripts.add(name.split()[0] if name else "OTHER")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return len(scripts) > 1 and "LATIN" in scripts
