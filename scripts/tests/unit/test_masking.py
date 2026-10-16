# 파이썬 공부 | scripts/tests/unit/test_masking.py
# masking 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config.models import DetectorPolicy, MaskPolicy, PrivacyPolicy
from app.telemetry.masking import LogMasker

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0
# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


# _masker(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: LogMasker.
def _masker() -> LogMasker:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return LogMasker(
        [
            DetectorPolicy(
                id="openai_api_key",
                label="OpenAI API 키",
                pattern=r"sk-[A-Za-z0-9_\-]{20,}",
                action="block",
                kind="secret",
            ),
            DetectorPolicy(
                id="bearer",
                label="Bearer 토큰",
                pattern=r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}",
                action="block",
                kind="secret",
            ),
            DetectorPolicy(
                id="private_key",
                label="개인키",
                pattern=r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                action="block",
                kind="secret",
            ),
            DetectorPolicy(
                id="rrn",
                label="주민등록번호",
                pattern=r"\b\d{6}[-\s]?[1-4]\d{6}\b",
                action="block",
                kind="pii_high",
            ),
        ],
        MaskPolicy(replacement="[{label}]", keep_tail={}),
    )


# pytest가 test_sensitive_patterns_and_registered_secret_never_remain()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_sensitive_patterns_and_registered_secret_never_remain() -> None:
    # _masker()의 반환값을 masker에 대입합니다.
    masker = _masker()
    # exact에 문자열을 대입합니다.
    exact = "runtime-super-secret"
    # masker.register_secret()을 호출해 작업을 수행합니다.
    masker.register_secret(exact)
    # sensitive_values에 리스트(순서가 있고 수정 가능)을 대입합니다.
    sensitive_values = [
        "sk-abcdefghijklmnopqrstuvwxyz",
        "Bearer abcdefghijklmnopqrstuvwxyz",
        "-----BEGIN RSA PRIVATE KEY-----",
        "900101-1234567",
        exact,
    ]
    # ' / '.join()의 반환값을 text에 대입합니다.
    text = " / ".join(sensitive_values)

    # 언패킹: 오른쪽 결과를 순서대로 (masked, findings)에 나누어 담습니다.
    masked, findings = masker.mask_text(text)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all(value not in masked for value in sensitive_values)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(findings) == 5
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert {finding.detector_id for finding in findings} == {
        "openai_api_key",
        "bearer",
        "private_key",
        "rrn",
        "registered_secret",
    }
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all(value not in repr(findings) for value in sensitive_values)


# pytest가 test_korean_suffix_after_phone_number_is_still_masked()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_korean_suffix_after_phone_number_is_still_masked() -> None:
    # yaml.safe_load()의 반환값을 document에 대입합니다.
    document = yaml.safe_load(
        (REPOSITORY_ROOT / "config" / "privacy.example.yaml").read_text(encoding="utf-8")
    )
    # LogMasker.from_policy()의 반환값을 masker에 대입합니다.
    masker = LogMasker.from_policy(PrivacyPolicy.model_validate(document))

    # 언패킹: 오른쪽 결과를 순서대로 (masked, findings)에 나누어 담습니다.
    masked, findings = masker.mask_text("연락처는 010-1234-5678입니다")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "010-1234-5678" not in masked
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [finding.detector_id for finding in findings] == ["kr_phone"]


# pytest가 test_longest_overlapping_detector_wins()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_longest_overlapping_detector_wins() -> None:
    # LogMasker()의 반환값을 masker에 대입합니다.
    masker = LogMasker(
        [
            DetectorPolicy(id="short", label="짧음", pattern="abc", action="mask", kind="pii"),
            DetectorPolicy(id="long", label="김", pattern="abcdef", action="mask", kind="pii"),
        ],
        MaskPolicy(replacement="[{label}]", keep_tail={}),
    )

    # 언패킹: 오른쪽 결과를 순서대로 (masked, findings)에 나누어 담습니다.
    masked, findings = masker.mask_text("abcdef")

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert masked == "[김]"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert [finding.detector_id for finding in findings] == ["long"]


# pytest가 test_structured_values_mask_keys_and_nested_values()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_structured_values_mask_keys_and_nested_values() -> None:
    # _masker()의 반환값을 masker에 대입합니다.
    masker = _masker()
    # secret에 문자열을 대입합니다.
    secret = "sk-abcdefghijklmnopqrstuvwxyz"

    # 언패킹: 오른쪽 결과를 순서대로 (sanitized, findings)에 나누어 담습니다.
    sanitized, findings = masker.sanitize_value({f"key-{secret}": [secret, {"v": secret}]})

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert secret not in repr(sanitized)
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert len(findings) == 3
