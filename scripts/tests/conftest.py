# 파이썬 공부 | scripts/tests/conftest.py
# pytest가 여러 테스트에 주입할 공통 준비 함수(fixture)를 정의합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Shared pytest fixtures for Jarvis tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.helpers.phase4_app import (
    REPOSITORY_ROOT,
    Phase4App,
    build_phase4_app,
    phase4_app,
)
from tests.helpers.phase5_app import Phase5App, build_phase5_app, phase5_app

# __all__에 리스트(순서가 있고 수정 가능)을 대입합니다.
__all__ = [
    "REPOSITORY_ROOT",
    "Phase4App",
    "Phase5App",
    "build_phase4_app",
    "build_phase5_app",
    "phase4_app",
    "phase5_app",
]


# config_dir(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Phase 3-style config directory with data_root outside AppData deny_paths."""
    # 오른쪽 식을 계산한 값을 destination에 대입합니다.
    destination = tmp_path / "config"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    destination.mkdir()
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("settings", "tools", "privacy"):
        # 오른쪽 식을 계산한 값을 source에 대입합니다.
        source = REPOSITORY_ROOT / "config" / f"{name}.example.yaml"
        # 오른쪽 식을 계산한 값을 dest에 대입합니다.
        dest = destination / f"{name}.yaml"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: name == 'tools'.
        if name == "tools":
            # yaml.safe_load()의 반환값을 document에 대입합니다.
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            # document['sandbox']['deny_paths']에 리스트(순서가 있고 수정 가능)을 대입합니다.
            document["sandbox"]["deny_paths"] = [
                "C:\\Windows",
                "C:\\Program Files",
                "C:\\Program Files (x86)",
            ]
            # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
            dest.write_text(
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
            dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    # 오른쪽 식을 계산한 값을 data_root에 대입합니다.
    data_root = tmp_path / "Jarvis"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    data_root.mkdir(parents=True, exist_ok=True)
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = destination / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # str()의 반환값을 document['paths']['data_root']에 대입합니다.
    document["paths"]["data_root"] = str(data_root)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return destination


@pytest.fixture(autouse=True)
def no_live_rag_embeddings(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Tests explicitly inject embeddings; never contact a developer's Ollama."""
    if request.node.get_closest_marker("allow_network"):
        return
    from app.rag.local_embedder import LocalOllamaEmbedder

    def offline(*args: object, **kwargs: object) -> object:
        raise OSError("Live embedding network disabled in tests")

    monkeypatch.setattr(LocalOllamaEmbedder, "_request", offline)

    from app.rag.reranker import LocalCrossEncoder

    def no_model_load(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("Live reranker disabled in unit tests")

    monkeypatch.setattr(LocalCrossEncoder, "_load", no_model_load)
