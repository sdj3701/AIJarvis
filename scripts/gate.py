"""Run a documented Phase test gate and write machine-readable evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.core.atomic import write_atomic  # noqa: E402
from app.core.clock import KST  # noqa: E402

ARTIFACTS_DIR = REPOSITORY_ROOT / "artifacts" / "gates"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis Phase 완료 게이트")
    parser.add_argument("--phase", type=int, choices=range(0, 9), required=True)
    return parser


def _marker_expression(phase: int) -> str:
    phases = " or ".join(f"phase{number}" for number in range(phase + 1))
    return f"({phases}) and not allow_network"


def _count(output: str, label: str) -> int:
    matches = re.findall(rf"(\d+) {label}", output)
    return int(matches[-1]) if matches else 0


def _commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _phase_evidence(phase: int, *, passed: bool) -> tuple[list[dict[str, object]], list[str]]:
    if phase == 0:
        return [], ["Phase 0에는 외부 API 호출과 정량 성능 기준이 없습니다."]
    metrics: list[dict[str, object]] = [
        {
            "name": "recovery.input_loss",
            "value": 0 if passed else None,
            "threshold": 0,
            "ok": passed,
            "note": "5개 종료 지점마다 4회씩, 총 20회 별도 프로세스 강제 종료",
        },
        {
            "name": "turn.latency.p95_ms",
            "value": None,
            "threshold": 15000,
            "ok": None,
            "note": "자동 테스트는 가짜 LLM을 사용하므로 실제 모델 수동 측정 대상",
        },
    ]
    return metrics, [
        "Phase 1 자동 게이트는 외부 네트워크를 사용하지 않습니다.",
        "Ollama 모델 digest·GPU 적재·3턴 대화는 실제 로컬 모델로 별도 확인합니다.",
    ]


def run_gate(phase: int) -> int:
    started_at = datetime.now(tz=KST)
    marker = _marker_expression(phase)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", marker],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    sys.stdout.write(combined)
    sys.stdout.flush()
    exit_code = 0 if result.returncode == 0 else 1
    finished_at = datetime.now(tz=KST)
    metrics, notes = _phase_evidence(phase, passed=exit_code == 0)
    evidence = {
        "schema_version": 1,
        "phase": phase,
        "started_at": started_at.isoformat(timespec="milliseconds"),
        "finished_at": finished_at.isoformat(timespec="milliseconds"),
        "exit_code": exit_code,
        "commit": _commit(),
        "marker_expr": marker,
        "tests": {
            "passed": _count(combined, "passed"),
            "failed": _count(combined, "failed"),
            "skipped": _count(combined, "skipped"),
            "skipped_reasons": [],
        },
        "metrics": metrics,
        "unmet": [] if exit_code == 0 else ["pytest gate failed"],
        "notes": notes,
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact = ARTIFACTS_DIR / f"phase{phase}-{finished_at:%Y%m%d}.json"
    write_atomic(
        artifact,
        (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(f"게이트 증거: {artifact}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run_gate(args.phase)


if __name__ == "__main__":
    raise SystemExit(main())
