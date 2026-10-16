# 파이썬 공부 | scripts/tests/unit/test_config_loader.py
# config_loader 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Tests for strict loading of the three Jarvis configuration files."""

from __future__ import annotations

import inspect
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config.defaults import DEFAULT_CONFIG_DIR
from app.config.loader import load_config, load_policies, load_settings
from app.core.errors import ConfigError

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0

# 오른쪽 식을 계산한 값을 REPO_ROOT에 대입합니다.
REPO_ROOT = Path(__file__).resolve().parents[3]


# config_dir(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
# @pytest.fixture: 테스트가 같은 이름의 인자를 요청하면 pytest가 준비한 값을 넣어 줍니다.
@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Copy the examples and point them at a writable temporary data root."""
    # 오른쪽 식을 계산한 값을 destination에 대입합니다.
    destination = tmp_path / "config"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    destination.mkdir()
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in ("settings", "tools", "privacy"):
        # shutil.copyfile()을 호출해 작업을 수행합니다.
        shutil.copyfile(
            REPO_ROOT / "config" / f"{name}.example.yaml",
            destination / f"{name}.yaml",
        )

    # 오른쪽 식을 계산한 값을 data_root에 대입합니다.
    data_root = tmp_path / "JarvisTest"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    data_root.mkdir()
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        destination / "settings.yaml",
        lambda document: document["paths"].__setitem__("data_root", str(data_root)),
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return destination


# _load_yaml(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: dict[str, Any].
def _load_yaml(path: Path) -> dict[str, Any]:
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with path.open("r", encoding="utf-8") as stream:
        # yaml.safe_load()의 반환값을 document에 대입합니다.
        document = yaml.safe_load(stream)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert isinstance(document, dict)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return document


# _mutate_yaml(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path, mutation.
# 반환 타입 힌트: 별도 결과 없음(None).
def _mutate_yaml(path: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
    # _load_yaml()의 반환값을 document에 대입합니다.
    document = _load_yaml(path)
    # mutation()을 호출해 작업을 수행합니다.
    mutation(document)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        # yaml.safe_dump()을 호출해 작업을 수행합니다.
        yaml.safe_dump(document, stream, allow_unicode=True, sort_keys=False)


# _tool_definition(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: document, name.
# 반환 타입 힌트: dict[str, Any].
def _tool_definition(document: dict[str, Any], name: str) -> dict[str, Any]:
    # for 반복문: 대상의 항목을 하나씩 tool에 대입하며 아래 블록을 실행합니다.
    for tool in document["tools"]:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: tool['name'] == name.
        if tool["name"] == name:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return tool
    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
    raise AssertionError(f"missing tool fixture: {name}")


# pytest가 test_example_yaml_files_load()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_example_yaml_files_load(config_dir: Path) -> None:
    # load_config()의 반환값을 loaded에 대입합니다.
    loaded = load_config(config_dir)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert loaded.settings.schema_version == 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert loaded.policies.tools.default == "deny"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert loaded.policies.privacy.api_transmission.default == "deny"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(loaded.config_hash) == 64
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert set(loaded.config_hash) <= set("0123456789abcdef")


# pytest가 test_loader_defaults_to_v2_dev_config_dir()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_loader_defaults_to_project_data_config_dir() -> None:
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert inspect.signature(load_config).parameters["config_dir"].default == DEFAULT_CONFIG_DIR
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert Path(r"D:\Ai\Jarvis\data") / "config" == DEFAULT_CONFIG_DIR


# pytest가 test_missing_config_directory_reports_bootstrap()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_missing_config_directory_reports_bootstrap(config_dir: Path) -> None:
    # 오른쪽 식을 계산한 값을 missing에 대입합니다.
    missing = config_dir.parent / "missing"

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError, match="bootstrap") as error:
        # load_config()을 호출해 작업을 수행합니다.
        load_config(missing)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "bootstrap" in error.value.user_message


# pytest가 test_data_root_must_exist()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_data_root_must_exist(config_dir: Path) -> None:
    # 오른쪽 식을 계산한 값을 missing에 대입합니다.
    missing = config_dir.parent / "missing-data-root"
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["paths"].__setitem__("data_root", str(missing)),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_settings_path_cannot_escape_data_root()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_settings_path_cannot_escape_data_root(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["paths"].__setitem__("docs_dir", "..\\outside"),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_unknown_key_rejected()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_unknown_key_rejected(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["llm"]["context"].__setitem__("typo_share", 0.1),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_newer_schema_version_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir, filename.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("filename", ["settings.yaml", "tools.yaml", "privacy.yaml"])
def test_newer_schema_version_rejected(config_dir: Path, filename: str) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / filename,
        lambda document: document.__setitem__("schema_version", 2),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_cannot_disable_default_deny()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir, filename, mutation.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    ("filename", "mutation"),
    [
        ("tools.yaml", lambda document: document.__setitem__("default", "allow")),
        (
            "privacy.yaml",
            lambda document: document["api_transmission"].__setitem__("default", "allow"),
        ),
    ],
)
def test_cannot_disable_default_deny(
    config_dir: Path,
    filename: str,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(config_dir / filename, mutation)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_write_root_outside_data_root_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_write_root_outside_data_root_rejected(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "tools.yaml",
        lambda document: document["sandbox"].__setitem__("write_roots", ["..\\outside"]),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_absolute_sandbox_root_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_absolute_sandbox_root_rejected(config_dir: Path) -> None:
    # 오른쪽 식을 계산한 값을 absolute에 대입합니다.
    absolute = config_dir.parent / "absolute"
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "tools.yaml",
        lambda document: document["sandbox"].__setitem__("read_roots", [str(absolute)]),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_context_share_sum_over_one_rejected()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_context_share_sum_over_one_rejected(config_dir: Path) -> None:
    # make_invalid(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: document.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def make_invalid(document: dict[str, Any]) -> None:
        # document['llm']['context']['memory_share']에 숫자 등 고정된 값을 대입합니다.
        document["llm"]["context"]["memory_share"] = 0.6
        # document['llm']['context']['history_share']에 숫자 등 고정된 값을 대입합니다.
        document["llm"]["context"]["history_share"] = 0.5

    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(config_dir / "settings.yaml", make_invalid)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_cannot_weaken_budget_on_exceed()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_cannot_weaken_budget_on_exceed(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["budget"].__setitem__("on_exceed", "warn_only"),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_budget_limit_is_required()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_budget_limit_is_required(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["budget"].pop("daily_limit"),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_pricing_must_contain_selected_model()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_pricing_must_contain_selected_model(config_dir: Path) -> None:
    # remove_selected_model(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: document.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def remove_selected_model(document: dict[str, Any]) -> None:
        # 오른쪽 식을 계산한 값을 model에 대입합니다.
        model = document["llm"]["model"]
        # document['llm']['pricing'].pop()을 호출해 작업을 수행합니다.
        document["llm"]["pricing"].pop(model)

    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(config_dir / "settings.yaml", remove_selected_model)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_local_ollama_decision_cannot_be_weakened()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir, field, value.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "openai"),
        ("base_url", "http://localhost:11434"),
        ("local_only", False),
        ("model", "qwen2.5:7b-instruct"),
        ("model_digest", "0" * 64),
        ("runtime_context_tokens", 32768),
        ("think", True),
    ],
)
def test_local_ollama_decision_cannot_be_weakened(
    config_dir: Path,
    field: str,
    value: Any,
) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["llm"].__setitem__(field, value),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_ollama_context_limits_must_fit_runtime_window()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_ollama_context_limits_must_fit_runtime_window(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["llm"]["context"].__setitem__(
            "max_input_tokens", 15000
        ),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_pdf_cannot_be_enabled_without_parser()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_pdf_can_be_enabled_with_local_parser(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["rag"]["supported_extensions"].append(".pdf"),
    )

    assert ".pdf" in load_config(config_dir).settings.rag.supported_extensions


# pytest가 test_sandbox_root_mapping_must_match_settings()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_sandbox_root_mapping_must_match_settings(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "tools.yaml",
        lambda document: document["sandbox"]["roots"].__setitem__("notes", "docs\\other"),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_tool_risk_and_execution_mode_are_required()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir, field.
# 반환 타입 힌트: 별도 결과 없음(None).
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("field", ["risk", "execution_mode"])
def test_tool_risk_and_execution_mode_are_required(config_dir: Path, field: str) -> None:
    # remove_field(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: document.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def remove_field(document: dict[str, Any]) -> None:
        # _tool_definition(document, 'web_search').pop()을 호출해 작업을 수행합니다.
        _tool_definition(document, "web_search").pop(field)

    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(config_dir / "tools.yaml", remove_field)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_run_skill_must_be_managed()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_run_skill_must_be_managed(config_dir: Path) -> None:
    # weaken_execution_mode(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: document.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def weaken_execution_mode(document: dict[str, Any]) -> None:
        # 아래 대상에 문자열을 대입합니다.
        _tool_definition(document, "run_skill")["execution_mode"] = "in_process"

    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(config_dir / "tools.yaml", weaken_execution_mode)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_open_app_must_be_detached_allowlisted()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_open_app_must_be_detached_allowlisted(config_dir: Path) -> None:
    # weaken_execution_mode(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: document.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def weaken_execution_mode(document: dict[str, Any]) -> None:
        # 아래 대상에 문자열을 대입합니다.
        _tool_definition(document, "open_app")["execution_mode"] = "managed_process"

    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(config_dir / "tools.yaml", weaken_execution_mode)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_open_app_executable_must_exist()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_open_app_executable_must_exist(config_dir: Path) -> None:
    # set_missing_executable(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: document.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def set_missing_executable(document: dict[str, Any]) -> None:
        # 아래 대상에 딕셔너리(키와 값의 쌍)을 대입합니다.
        _tool_definition(document, "open_app")["app_map"] = {
            "missing": str(config_dir.parent / "missing.exe")
        }

    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(config_dir / "tools.yaml", set_missing_executable)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_privacy_requires_secret_detector()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_privacy_requires_secret_detector(config_dir: Path) -> None:
    # remove_secret_detectors(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # 입력: document.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def remove_secret_detectors(document: dict[str, Any]) -> None:
        # 오른쪽 식을 계산한 값을 document['detectors']에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        document["detectors"] = [
            detector for detector in document["detectors"] if detector["kind"] != "secret"
        ]

    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(config_dir / "privacy.yaml", remove_secret_detectors)

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_memory_write_refusal_cannot_be_empty()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_memory_write_refusal_cannot_be_empty(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "privacy.yaml",
        lambda document: document["outputs"]["memory_write"].__setitem__("refuse_kinds", []),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_external_service_configuration_is_required()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_external_service_configuration_is_required(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "privacy.yaml",
        lambda document: document["api_transmission"]["services"].pop("llm"),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_online_tts_requires_transmission_permission()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_online_tts_requires_transmission_permission(config_dir: Path) -> None:
    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["voice"]["tts"].__setitem__("engine", "edge-tts"),
    )

    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir)


# pytest가 test_registered_tools_must_match_enabled_policy()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_registered_tools_must_match_enabled_policy(config_dir: Path) -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_config()을 호출해 작업을 수행합니다.
        load_config(config_dir, registered_tools=set())


# pytest가 test_documented_settings_overrides()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_documented_settings_overrides(config_dir: Path) -> None:
    # load_settings()의 반환값을 settings에 대입합니다.
    settings = load_settings(
        config_dir / "settings.yaml",
        overrides={
            "dev_mode": True,
            "llm.temperature": 0.1,
        },
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert settings.dev_mode is True
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert settings.llm.temperature == 0.1


# pytest가 test_documented_app_map_override()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_documented_app_map_override(config_dir: Path) -> None:
    # 오른쪽 식을 계산한 값을 fake_executable에 대입합니다.
    fake_executable = config_dir.parent / "fake.exe"
    # fake_executable.touch()을 호출해 작업을 수행합니다.
    fake_executable.touch()
    # load_settings()의 반환값을 settings에 대입합니다.
    settings = load_settings(config_dir / "settings.yaml")

    # load_policies()의 반환값을 policies에 대입합니다.
    policies = load_policies(
        config_dir / "tools.yaml",
        config_dir / "privacy.yaml",
        settings=settings,
        overrides={"tools.app_map": {"fake": str(fake_executable)}},
    )

    # next()의 반환값을 open_app에 대입합니다.
    open_app = next(tool for tool in policies.tools.tools if tool.name == "open_app")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert open_app.app_map == {"fake": fake_executable}


# pytest가 test_config_hash_is_stable_and_tracks_changes()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: config_dir.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_config_hash_is_stable_and_tracks_changes(config_dir: Path) -> None:
    # load_config()의 반환값을 first에 대입합니다.
    first = load_config(config_dir)
    # load_config()의 반환값을 second에 대입합니다.
    second = load_config(config_dir)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.config_hash == second.config_hash

    # _mutate_yaml()을 호출해 작업을 수행합니다.
    _mutate_yaml(
        config_dir / "settings.yaml",
        lambda document: document["metrics"].__setitem__("p95_window", 201),
    )
    # load_config()의 반환값을 changed에 대입합니다.
    changed = load_config(config_dir)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert changed.config_hash != first.config_hash
