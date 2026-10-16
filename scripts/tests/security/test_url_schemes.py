# 파이썬 공부 | scripts/tests/security/test_url_schemes.py
# url_schemes 관련 보안 경계을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""URL scheme blocking for fetch_url validation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config.loader import load_policies, load_settings
from app.core.errors import PolicyDenied
from app.rag.fetcher import UrlFetcher

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase3, pytest.mark.security]
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

# 오른쪽 식을 계산한 값을 SCHEME_CORPUS에 대입합니다.
SCHEME_CORPUS = Path(__file__).resolve().parents[1] / "data" / "web" / "scheme_corpus.txt"


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


# pytest가 test_scheme_corpus_blocked()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: fetcher.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_scheme_corpus_blocked(fetcher: UrlFetcher) -> None:
    # 아래 함수()의 반환값을 urls에 대입합니다.
    urls = SCHEME_CORPUS.read_text(encoding="utf-8").splitlines()
    # for 반복문: 대상의 항목을 하나씩 url에 대입하며 아래 블록을 실행합니다.
    for url in urls:
        # url.strip()의 반환값을 url에 대입합니다.
        url = url.strip()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not url or url.startswith('#').
        if not url or url.startswith("#"):
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
        with pytest.raises(PolicyDenied):
            # fetcher.validate_url()으로 입력 형식과 허용 조건을 검사합니다.
            fetcher.validate_url(url)
