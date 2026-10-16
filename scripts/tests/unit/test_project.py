# 파이썬 공부 | scripts/tests/unit/test_project.py
# project 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Smoke tests for the Phase 0 project skeleton and quality tools."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import app
from app.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_DATA_ROOT, PROTOTYPE_DATA_ROOT

# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
# frozenset()의 반환값을 PHASE0_RUNTIME에 대입합니다.
PHASE0_RUNTIME = frozenset(
    {"keyring", "pydantic", "python-ulid", "PyYAML", "sqlite-vec", "pdfplumber"}
)
# frozenset()의 반환값을 LATER_PHASE_LOCK_PACKAGES에 대입합니다.
LATER_PHASE_LOCK_PACKAGES = frozenset(
    {
        "faster-whisper",
        "vosk",
        "sounddevice",
        "webrtcvad-wheels",
        "ddgs",
    }
)
# REQUIRED_PYTEST_MARKERS에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
REQUIRED_PYTEST_MARKERS = (
    "phase0",
    "phase1",
    "phase2",
    "phase3",
    "phase4",
    "phase5",
    "phase6",
    "phase7",
    "phase8",
    "security",
    "slow",
    "needs_admin",
    "needs_gpu",
    "allow_network",
)


# _requirement_name(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: spec.
# 반환 타입 힌트: 문자열(str).
def _requirement_name(spec: str) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return re.split(r"[<>=\[]", spec, maxsplit=1)[0].strip()


# _lock_packages(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: dict[str, int].
def _lock_packages(text: str) -> dict[str, int]:
    # packages에 딕셔너리(키와 값의 쌍)을 대입합니다.
    packages: dict[str, int] = {}
    # current을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    current: str | None = None
    # hashes에 숫자 등 고정된 값을 대입합니다.
    hashes = 0
    # for 반복문: 대상의 항목을 하나씩 raw에 대입하며 아래 블록을 실행합니다.
    for raw in text.splitlines():
        # raw.strip()의 반환값을 line에 대입합니다.
        line = raw.strip()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not line or line.startswith('#').
        if not line or line.startswith("#"):
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: line.startswith('--hash=').
        if line.startswith("--hash="):
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            hashes += 1
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # re.match()의 반환값을 match에 대입합니다.
        match = re.match(r"^([A-Za-z0-9_.-]+)==", line)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
        if match is None:
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current is not None.
        if current is not None:
            # 오른쪽 식을 계산한 값을 packages[current]에 대입합니다.
            packages[current] = hashes
        # match.group(1).lower()의 반환값을 current에 대입합니다.
        current = match.group(1).lower()
        # hashes에 숫자 등 고정된 값을 대입합니다.
        hashes = 0
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: current is not None.
    if current is not None:
        # 오른쪽 식을 계산한 값을 packages[current]에 대입합니다.
        packages[current] = hashes
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return packages


# pytest가 test_package_is_importable()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.phase0
def test_package_is_importable() -> None:
    """The source package is available to the test runner."""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert app.__version__ == "0.0.0"


# pytest가 test_rebuild_data_is_isolated_from_prototype()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.phase0
def test_rebuild_data_is_isolated_from_prototype() -> None:
    """The rebuild must never use the prototype's operational root by default."""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert Path(r"D:\Jarvis") == PROTOTYPE_DATA_ROOT
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert Path(r"D:\Jarvis-v2-dev") == DEFAULT_DATA_ROOT
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert DEFAULT_DATA_ROOT != PROTOTYPE_DATA_ROOT
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert DEFAULT_CONFIG_DIR == DEFAULT_DATA_ROOT / "config"


# pytest가 test_pyproject_declares_phase0_quality_tools()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.phase0
def test_pyproject_declares_phase0_quality_tools() -> None:
    """Phase 0 pins the interpreter floor, runtime deps, and quality-tool config."""
    # tomllib.loads()의 반환값을 document에 대입합니다.
    document = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert document["project"]["requires-python"] == ">=3.11"
    # 오른쪽 식을 계산한 값을 runtime에 대입합니다.
    # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
    runtime = {_requirement_name(item) for item in document["project"]["dependencies"]}
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime == PHASE0_RUNTIME
    # '\n'.join()의 반환값을 markers에 대입합니다.
    markers = "\n".join(document["tool"]["pytest"]["ini_options"]["markers"])
    # for 반복문: 대상의 항목을 하나씩 marker에 대입하며 아래 블록을 실행합니다.
    for marker in REQUIRED_PYTEST_MARKERS:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert f"{marker}:" in markers
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert document["tool"]["ruff"]["target-version"] == "py311"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert document["tool"]["mypy"]["python_version"] == "3.11"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert document["tool"]["mypy"]["strict"] is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert document["tool"]["mypy"]["files"] == ["scripts/app"]


# pytest가 test_lockfile_pins_hashed_phase0_packages()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.phase0
def test_lockfile_pins_hashed_phase0_packages() -> None:
    """The lockfile is the install pin: exact versions, hashes, no later-phase extras."""
    # _lock_packages()의 반환값을 packages에 대입합니다.
    packages = _lock_packages((REPOSITORY_ROOT / "requirements.lock").read_text(encoding="utf-8"))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert packages, "requirements.lock must pin at least one package"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all(count >= 1 for count in packages.values())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert LATER_PHASE_LOCK_PACKAGES.isdisjoint(packages)
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("pydantic", "pyyaml", "keyring", "python-ulid", "pytest", "ruff", "mypy"):
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert name in packages


# pytest가 test_gitignore_hides_secrets_and_keeps_gate_evidence()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
# 이 pytest 마커는 테스트 분류 또는 실행 조건을 지정합니다.
@pytest.mark.phase0
def test_gitignore_hides_secrets_and_keeps_gate_evidence() -> None:
    """Local env, secrets, caches, and data copies stay private; gate JSON stays tracked."""
    # (REPOSITORY_ROOT / '.gitignore').read_text()의 반환값을 text에 대입합니다.
    text = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    # 오른쪽 식을 계산한 값을 patterns에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    patterns = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    # for 반복문: 대상의 항목을 하나씩 required에 대입하며 아래 블록을 실행합니다.
    for required in (".venv/", ".env", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/"):
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert required in patterns
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "/Jarvis-v2-dev/" in patterns
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert not any(
        pattern.rstrip("/") in {"artifacts", "artifacts/gates"}
        or pattern in {"/artifacts/", "/artifacts/gates/", "artifacts/", "artifacts/gates/"}
        for pattern in patterns
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "artifacts/gates" in text
