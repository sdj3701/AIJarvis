from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config.models import DetectorPolicy, MaskPolicy, PrivacyPolicy
from app.telemetry.masking import LogMasker

pytestmark = pytest.mark.phase0
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _masker() -> LogMasker:
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


def test_sensitive_patterns_and_registered_secret_never_remain() -> None:
    masker = _masker()
    exact = "runtime-super-secret"
    masker.register_secret(exact)
    sensitive_values = [
        "sk-abcdefghijklmnopqrstuvwxyz",
        "Bearer abcdefghijklmnopqrstuvwxyz",
        "-----BEGIN RSA PRIVATE KEY-----",
        "900101-1234567",
        exact,
    ]
    text = " / ".join(sensitive_values)

    masked, findings = masker.mask_text(text)

    assert all(value not in masked for value in sensitive_values)
    assert len(findings) == 5
    assert {finding.detector_id for finding in findings} == {
        "openai_api_key",
        "bearer",
        "private_key",
        "rrn",
        "registered_secret",
    }
    assert all(value not in repr(findings) for value in sensitive_values)


def test_korean_suffix_after_phone_number_is_still_masked() -> None:
    document = yaml.safe_load(
        (REPOSITORY_ROOT / "config" / "privacy.example.yaml").read_text(encoding="utf-8")
    )
    masker = LogMasker.from_policy(PrivacyPolicy.model_validate(document))

    masked, findings = masker.mask_text("연락처는 010-1234-5678입니다")

    assert "010-1234-5678" not in masked
    assert [finding.detector_id for finding in findings] == ["kr_phone"]


def test_longest_overlapping_detector_wins() -> None:
    masker = LogMasker(
        [
            DetectorPolicy(id="short", label="짧음", pattern="abc", action="mask", kind="pii"),
            DetectorPolicy(id="long", label="김", pattern="abcdef", action="mask", kind="pii"),
        ],
        MaskPolicy(replacement="[{label}]", keep_tail={}),
    )

    masked, findings = masker.mask_text("abcdef")

    assert masked == "[김]"
    assert [finding.detector_id for finding in findings] == ["long"]


def test_structured_values_mask_keys_and_nested_values() -> None:
    masker = _masker()
    secret = "sk-abcdefghijklmnopqrstuvwxyz"

    sanitized, findings = masker.sanitize_value({f"key-{secret}": [secret, {"v": secret}]})

    assert secret not in repr(sanitized)
    assert len(findings) == 3
