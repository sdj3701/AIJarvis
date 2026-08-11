from __future__ import annotations

from app.config.models import DetectorPolicy, MaskPolicy
from app.telemetry.masking import LogMasker


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
