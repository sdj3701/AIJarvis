# 파이썬 공부 | scripts/tests/unit/test_wiring.py
# wiring 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.budget import BudgetGuard
from app.core.errors import ExitCode
from app.llm.fake import FakeLLMClient
from app.llm.ollama_client import OllamaClient
from app.memory.store import SQLiteSessionStore
from app.ui.single_instance import SingleInstanceLock
from app.wiring import build, run_application
from scripts.bootstrap import create_tree

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


# runtime_config(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def runtime_config(tmp_path: Path) -> Path:
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
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # create_tree()을 호출해 작업을 수행합니다.
    create_tree(root)
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: (
            document["paths"].__setitem__("data_root", str(root)),
            document["memory"].__setitem__("summarize_on_exit", False),
        ),
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return config_dir


# _mutate_yaml(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, mutation.
# 반환 타입 힌트: 별도 결과 없음(None).
def _mutate_yaml(path: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(document, dict)
    # mutation()을 호출해 작업을 수행합니다.
    mutation(document)
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")


# _events(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: config_dir.
# 반환 타입 힌트: list[dict[str, Any]].
def _events(config_dir: Path) -> list[dict[str, Any]]:
    # yaml.safe_load()의 반환값을 settings에 대입합니다.
    settings = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    # Path()의 반환값을 root에 대입합니다.
    root = Path(settings["paths"]["data_root"])
    # records에 리스트(순서가 있고 수정 가능)을 대입합니다.
    records: list[dict[str, Any]] = []
    # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
    for path in sorted((root / "logs").glob("events-*.jsonl")):
        # 반복 가능한 값의 항목들을 리스트 끝에 차례로 추가합니다.
        records.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return records


# pytest가 test_build_assembles_config_clock_ids_events_and_secrets()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: runtime_config.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_build_assembles_config_clock_ids_events_and_secrets(runtime_config: Path) -> None:
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(runtime_config)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.config.settings.schema_version == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.clock.now().tzinfo is not None
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.ids.new("req").startswith("req_")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.memory_db.name == "jarvis.sqlite3"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert runtime.lock.acquired is False
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(runtime.llm, OllamaClient)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(runtime.sessions, SQLiteSessionStore)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(runtime.budget, BudgetGuard)


# pytest가 test_application_runs_recovery_cli_and_normal_cleanup()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: runtime_config.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_application_runs_recovery_cli_and_normal_cleanup(runtime_config: Path) -> None:
    # StringIO()의 반환값을 output에 대입합니다.
    output = StringIO()
    # StringIO()의 반환값을 errors에 대입합니다.
    errors = StringIO()

    # run_application()의 반환값을 exit_code에 대입합니다.
    exit_code = run_application(
        config_dir=runtime_config,
        input_stream=StringIO("확인\n/bye\n"),
        output_stream=output,
        error_stream=errors,
        llm=FakeLLMClient().reply("확인 응답"),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "확인 응답" in output.getvalue()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert errors.getvalue() == ""
    # 오른쪽 식을 계산한 값을 event_types에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    event_types = [record["event_type"] for record in _events(runtime_config)]
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert event_types == [
        "app.start",
        "recovery.start",
        "recovery.result",
        "recovery.start",
        "recovery.result",
        "recovery.result",
        "rag.index",
        "session.start",
        "user.input",
        "memory.search",
        "rag.semantic_unavailable",
        "response.presentation",
        "session.end",
        "app.stop",
    ]
    # build()의 반환값을 runtime에 대입합니다.
    runtime = build(runtime_config)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with runtime.lock:
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert runtime.lock.acquired


# pytest가 test_python_module_entrypoint_runs_once()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: runtime_config.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_python_module_entrypoint_runs_once(runtime_config: Path) -> None:
    # subprocess.run()의 반환값을 result에 대입합니다.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app",
            "--config-dir",
            str(runtime_config),
            "--once",
            "/help",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.returncode == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "사용 가능한 명령" in result.stdout
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.stderr == ""
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert _events(runtime_config)[-1]["event_type"] == "app.stop"


# pytest가 test_application_ctrl_c_still_emits_stop_with_130()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: runtime_config.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_application_ctrl_c_still_emits_stop_with_130(runtime_config: Path) -> None:
    from tests.unit.test_cli import InterruptingInput

    # run_application()의 반환값을 exit_code에 대입합니다.
    exit_code = run_application(
        config_dir=runtime_config,
        input_stream=InterruptingInput(),
        output_stream=StringIO(),
        error_stream=StringIO(),
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == ExitCode.INTERRUPTED
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert _events(runtime_config)[-1]["payload"]["exit_code"] == 130


# pytest가 test_second_application_instance_returns_one()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: runtime_config.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_second_application_instance_returns_one(runtime_config: Path) -> None:
    # yaml.safe_load()의 반환값을 settings에 대입합니다.
    settings = yaml.safe_load((runtime_config / "settings.yaml").read_text(encoding="utf-8"))
    # 오른쪽 식을 계산한 값을 lock_path에 대입합니다.
    lock_path = Path(settings["paths"]["data_root"]) / "state" / "jarvis.lock"
    # StringIO()의 반환값을 errors에 대입합니다.
    errors = StringIO()

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with SingleInstanceLock(lock_path):
        # run_application()의 반환값을 exit_code에 대입합니다.
        exit_code = run_application(
            config_dir=runtime_config,
            input_stream=StringIO(),
            output_stream=StringIO(),
            error_stream=errors,
        )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "이미 실행 중" in errors.getvalue()


# pytest가 test_stack_trace_is_visible_only_in_dev_mode()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: runtime_config, monkeypatch, dev_mode.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("dev_mode", [False, True])
def test_stack_trace_is_visible_only_in_dev_mode(
    runtime_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    dev_mode: bool,
) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        runtime_config / "settings.yaml",
        lambda document: document.__setitem__("dev_mode", dev_mode),
    )

    # fail_recovery(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: data_root, events.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def fail_recovery(data_root: Path, events: object) -> None:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del data_root, events
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise RuntimeError("internal diagnostic")

    # 대상의 속성을 바꿉니다. monkeypatch이면 테스트 후 원래 상태로 복원됩니다.
    monkeypatch.setattr("app.wiring.recover_startup", fail_recovery)
    # StringIO()의 반환값을 errors에 대입합니다.
    errors = StringIO()

    # run_application()의 반환값을 exit_code에 대입합니다.
    exit_code = run_application(
        config_dir=runtime_config,
        input_stream=StringIO(),
        output_stream=StringIO(),
        error_stream=errors,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert ("Traceback" in errors.getvalue()) is dev_mode
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "internal diagnostic" not in errors.getvalue() or dev_mode
