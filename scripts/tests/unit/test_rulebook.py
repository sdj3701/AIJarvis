# 파이썬 공부 | scripts/tests/unit/test_rulebook.py
# rulebook 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.

"""The response policy is durable, validated and mandatory."""
import re
from pathlib import Path

import pytest

from app.core.errors import ConfigError
from app.orchestrator.rulebook import DEFAULT_RULEBOOK, load_rulebook


# pytest가 test_invalid_rulebook_fails_closed()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path, change.
# @pytest.mark.parametrize: 여러 입력·예상값 조합으로 같은 테스트를 반복합니다.
@pytest.mark.parametrize("change", [
    lambda s: s.replace("schema_version: 1", "schema_version: 2"),
    lambda s: s.replace("max_chars: 100", "max_chars: 0"),
    lambda s: s.replace("safety_exceptions: true", "safety_exceptions: false"),
    lambda s: s.replace("max_chars: 100", "max_chars: 100\nmax_chars: 80"),
    lambda s: s.replace("max_chars: 100", "unexpected: true"),
    lambda s: re.sub(r"rulebook_version: \d+", "rulebook_version: true", s),
    lambda s: "x" * 16385,
    lambda s: s.replace("language: ko", "language: !!python/object:bad {}"),
])
def test_invalid_rulebook_fails_closed(tmp_path, change):
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "rules.md"
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    path.write_text(change(DEFAULT_RULEBOOK.read_text(encoding="utf-8")), encoding="utf-8")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_rulebook()을 호출해 작업을 수행합니다.
        load_rulebook(path)


# pytest가 test_missing_and_invalid_utf8()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: tmp_path.
def test_missing_and_invalid_utf8(tmp_path):
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_rulebook()을 호출해 작업을 수행합니다.
        load_rulebook(tmp_path / "missing.md")
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "rules.md"
    # 바이트 데이터를 파일에 기록합니다.
    path.write_bytes(b"\xff")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError):
        # load_rulebook()을 호출해 작업을 수행합니다.
        load_rulebook(path)


# pytest가 test_snapshot_changes_only_when_reloaded()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
def test_snapshot_changes_only_when_reloaded(tmp_path: Path):
    # 오른쪽 식을 계산한 값을 path에 대입합니다.
    path = tmp_path / "rules.md"
    # DEFAULT_RULEBOOK.read_text()의 반환값을 text에 대입합니다.
    text = DEFAULT_RULEBOOK.read_text(encoding="utf-8")
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    path.write_text(text, encoding="utf-8")
    # load_rulebook()의 반환값을 snapshot에 대입합니다.
    snapshot = load_rulebook(path)
    # 오른쪽 식을 계산한 값을 old_version에 대입합니다.
    old_version = snapshot.version
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    path.write_text(re.sub(r"rulebook_version: \d+", f"rulebook_version: {old_version + 1}", text),
                    encoding="utf-8")
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert snapshot.version == old_version
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert load_rulebook(path).version == old_version + 1
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert load_rulebook(path).sha256 != snapshot.sha256
