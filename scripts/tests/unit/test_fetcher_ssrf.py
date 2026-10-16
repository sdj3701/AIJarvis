# 파이썬 공부 | scripts/tests/unit/test_fetcher_ssrf.py
# fetcher_ssrf 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase3, pytest.mark.security]
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


# fetcher(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: UrlFetcher.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def fetcher(tmp_path: Path) -> UrlFetcher:
    # 오른쪽 식을 계산한 값을 config_dir에 대입합니다.
    config_dir = tmp_path / "config"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    config_dir.mkdir()
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("settings", "tools", "privacy"):
        # shutil.copyfile()을 호출해 작업을 수행합니다.
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    # load_settings()의 반환값을 settings에 대입합니다.
    settings = load_settings(config_dir / "settings.yaml")
    # load_policies()의 반환값을 policies에 대입합니다.
    policies = load_policies(
        config_dir / "tools.yaml",
        config_dir / "privacy.yaml",
        settings=settings,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return UrlFetcher(
        fetch_settings=settings.rag.fetch,
        network=policies.tools.network,
    )


# pytest가 test_blocked_urls()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: fetcher, url.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
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
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PolicyDenied):
        # fetcher.validate_url()으로 입력 형식과 허용 조건을 검사합니다.
        fetcher.validate_url(url)


# FakeResponse: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class FakeResponse:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: status, headers, body.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        status: int,
        *,
        headers: dict[str, str],
        body: bytes = b"",
    ) -> None:
        # 오른쪽 식을 계산한 값을 self.status에 대입합니다.
        self.status = status
        # 오른쪽 식을 계산한 값을 self.headers에 대입합니다.
        self.headers = headers
        # 오른쪽 식을 계산한 값을 self._body에 대입합니다.
        self._body = body
        # self.closed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = False

    # read(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: size.
    # 반환 타입 힌트: 바이트 데이터(bytes).
    def read(self, size: int = -1) -> bytes:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del size
        # 언패킹: 오른쪽 결과를 순서대로 (body, self._body)에 나누어 담습니다.
        body, self._body = self._body, b""
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return body

    # close(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def close(self) -> None:
        # self.closed을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
        self.closed = True


# pytest가 test_validated_dns_address_is_pinned_to_connection()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: fetcher, monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_validated_dns_address_is_pinned_to_connection(
    fetcher: UrlFetcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(
        fetcher_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    # captured에 리스트(순서가 있고 수정 가능)을 대입합니다.
    captured: list[tuple[str, str]] = []

    # fake_open(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: url, timeout, connect_ip.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def fake_open(url: str, *, timeout: float, connect_ip: str) -> Any:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert timeout > 0
        # 리스트 끝에 항목 하나를 추가합니다.
        captured.append((url, connect_ip))
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return FakeResponse(200, headers={"Content-Type": "text/plain"}, body=b"ok")

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(fetcher_module, "_open", fake_open)
    # fetcher.fetch()의 반환값을 document에 대입합니다.
    document = fetcher.fetch("http://example.com/")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert document.content == "ok"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert captured == [("http://example.com/", "93.184.216.34")]


# pytest가 test_redirect_to_private_address_is_rejected_before_second_connection()을 실행해 아래
# 상황이
# 기대대로 동작하는지 확인합니다.
# 입력: fetcher, monkeypatch.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_redirect_to_private_address_is_rejected_before_second_connection(
    fetcher: UrlFetcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(
        fetcher_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    # calls에 숫자 등 고정된 값을 대입합니다.
    calls = 0

    # fake_open(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: url, timeout, connect_ip.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def fake_open(url: str, *, timeout: float, connect_ip: str) -> Any:
        # 바로 바깥쪽 함수 범위에 있는 변수를 이 함수에서 다시 대입할 수 있게 합니다.
        nonlocal calls
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del url, timeout, connect_ip
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        calls += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return FakeResponse(302, headers={"Location": "http://127.0.0.1/admin"})

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr(fetcher_module, "_open", fake_open)
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(PolicyDenied):
        # fetcher.fetch()을 호출해 작업을 수행합니다.
        fetcher.fetch("http://example.com/start")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert calls == 1
