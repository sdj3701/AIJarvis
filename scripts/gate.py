"""Run a documented Phase test gate and write machine-readable evidence."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.config.loader import DEFAULT_CONFIG_DIR, load_settings  # noqa: E402
from app.core.atomic import write_atomic  # noqa: E402
from app.core.clock import KST  # noqa: E402
from app.telemetry.audit import verify_audit_chain_report  # noqa: E402

ARTIFACTS_DIR = REPOSITORY_ROOT / "artifacts" / "gates"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis Phase 완료 게이트 / 운영 검증")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--phase", type=int, choices=range(0, 9))
    mode.add_argument(
        "--verify-audit",
        action="store_true",
        help="운영 data_root/logs 감사 해시 체인 검증",
    )
    mode.add_argument(
        "--integrity",
        action="store_true",
        help="SQLite integrity + 감사 체인 요약 점검",
    )
    mode.add_argument(
        "--report",
        action="store_true",
        help="감사·무결성 요약 JSON을 stdout에 출력",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=DEFAULT_CONFIG_DIR,
        help="운영 설정 디렉터리 (기본 D:\\Jarvis\\config)",
    )
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


def _worktree_changes() -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ("git_status_failed",)
    changes: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].replace("\\", "/") if len(line) > 3 else line
        if path.startswith("artifacts/gates/"):
            continue
        changes.append(line)
    return tuple(changes)


def _phase_evidence(phase: int, *, passed: bool) -> tuple[list[dict[str, object]], list[str]]:
    if phase == 0:
        return [], ["Phase 0에는 외부 API 호출과 정량 성능 기준이 없습니다."]
    if phase >= 6:
        return [
            {
                "name": "security.critical_high",
                "value": 0 if passed else None,
                "threshold": 0,
                "ok": passed,
                "note": "Critical/High 0건 + 보안 마커 회귀",
            }
        ], [
            "Phase 6 자동 게이트는 백업 복원(D007/D008)을 포함하지 않는다.",
            "복원·정량 태스크 95%는 backup.py와 slow 테스트로 별도 확인한다.",
        ]
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


def _resolve_data_paths(config_dir: Path) -> tuple[Path, Path]:
    settings = load_settings(config_dir / "settings.yaml")
    data_root = settings.paths.data_root
    logs_dir = data_root / "logs"
    memory_db = settings.paths.memory_db
    if not memory_db.is_absolute():
        memory_db = data_root / memory_db
    return logs_dir, memory_db.resolve(strict=False)


def _sqlite_integrity(database_path: Path) -> list[str]:
    if not database_path.exists():
        return [f"missing database: {database_path}"]
    problems: list[str] = []
    with sqlite3.connect(database_path) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            problems.append(f"pragma integrity_check: {integrity}")
    return problems


def run_verify_audit(config_dir: Path) -> int:
    logs_dir, _memory_db = _resolve_data_paths(config_dir)
    report = verify_audit_chain_report(logs_dir)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def run_integrity(config_dir: Path) -> int:
    logs_dir, memory_db = _resolve_data_paths(config_dir)
    audit = verify_audit_chain_report(logs_dir)
    db_problems = _sqlite_integrity(memory_db)
    payload = {
        "audit": audit.as_dict(),
        "sqlite_integrity_ok": not db_problems,
        "sqlite_problems": db_problems,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if audit.ok and not db_problems else 1


def run_report(config_dir: Path) -> int:
    return run_integrity(config_dir)


def run_gate(phase: int) -> int:
    changes = _worktree_changes()
    if changes:
        print("게이트를 실행하려면 코드 작업 트리가 깨끗해야 합니다.", file=sys.stderr)
        for change in changes[:20]:
            print(f"  {change}", file=sys.stderr)
        return 1

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
        "worktree_clean": True,
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
    if args.verify_audit:
        return run_verify_audit(args.config_dir)
    if args.integrity:
        return run_integrity(args.config_dir)
    if args.report:
        return run_report(args.config_dir)
    assert args.phase is not None
    return run_gate(args.phase)


if __name__ == "__main__":
    raise SystemExit(main())
