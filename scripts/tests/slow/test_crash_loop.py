# 파이썬 공부 | scripts/tests/slow/test_crash_loop.py
# crash_loop 관련 시간이 걸리는 복구·반복 실행을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Abrupt child-process exits must never lose the flushed user input."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.bootstrap import create_tree

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase1, pytest.mark.slow, pytest.mark.timeout(900)]
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


# _prepare_config(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: root.
# 반환 타입 힌트: Path.
def _prepare_config(root: Path) -> Path:
    # 오른쪽 식을 계산한 값을 config_dir에 대입합니다.
    config_dir = root / "config-source"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    config_dir.mkdir(parents=True)
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("settings", "tools", "privacy"):
        # shutil.copyfile()을 호출해 작업을 수행합니다.
        shutil.copyfile(
            REPOSITORY_ROOT / "config" / f"{name}.example.yaml",
            config_dir / f"{name}.yaml",
        )
    # 오른쪽 식을 계산한 값을 data_root에 대입합니다.
    data_root = root / "Jarvis"
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(data_root)
    # 오른쪽 식을 계산한 값을 settings_path에 대입합니다.
    settings_path = config_dir / "settings.yaml"
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document: dict[str, Any] = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    # document['dev_mode']을 True(으)로 설정해 참/거짓 상태를 나타냅니다.
    document["dev_mode"] = True
    # str()의 반환값을 document['paths']['data_root']에 대입합니다.
    document["paths"]["data_root"] = str(data_root)
    # document['memory']['checkpoint_every_turns']에 숫자 등 고정된 값을 대입합니다.
    document["memory"]["checkpoint_every_turns"] = 1
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return config_dir


# pytest가 test_no_input_loss_on_kill()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: tmp_path, kill_after.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    "kill_after",
    ["user.input", "llm.request", "llm.response", "memory.write", "session.checkpoint"],
)
def test_no_input_loss_on_kill(tmp_path: Path, kill_after: str) -> None:
    # for 반복문: 대상의 항목을 하나씩 iteration에 대입하며 아래 블록을 실행합니다.
    for iteration in range(4):
        # 오른쪽 식을 계산한 값을 run_root에 대입합니다.
        run_root = tmp_path / f"{kill_after.replace('.', '-')}-{iteration}"
        # _prepare_config()의 반환값을 config_dir에 대입합니다.
        config_dir = _prepare_config(run_root)
        # 오른쪽 식을 계산한 값을 text에 대입합니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        text = f"질문-{kill_after}-{iteration}"
        # os.environ.copy()의 반환값을 environment에 대입합니다.
        environment = os.environ.copy()
        # environment.update()을 호출해 작업을 수행합니다.
        environment.update(
            {
                "JARVIS_TEST_KILL_AFTER": kill_after,
                "JARVIS_LLM": "fake",
            }
        )

        # subprocess.run()의 반환값을 result에 대입합니다.
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app",
                "--config-dir",
                str(config_dir),
                "--once",
                text,
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert result.returncode == 97, result.stderr
        # list()의 반환값을 raw_files에 대입합니다.
        raw_files = list((run_root / "Jarvis" / "memory" / "raw").glob("*.jsonl"))
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert len(raw_files) == 1
        # 오른쪽 식을 계산한 값을 records에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        records = [
            json.loads(line)
            for line in raw_files[0].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert any(record["role"] == "user" and record["content"] == text for record in records)
