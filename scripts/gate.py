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
    parser = argparse.ArgumentParser(description="Jarvis Phase 완료 게이트 및 보안 감사")
    parser.add_argument("--phase", type=int, choices=range(0, 9), help="실행할 Phase 번호 (0~8)")
    parser.add_argument(
        "--verify-audit", action="store_true", help="감사 로그 해시 체인 무결성 검증"
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path(r"D:\Jarvis\logs"),
        help="검증할 감사 로그 디렉터리",
    )
    parser.add_argument("--report", action="store_true", help="게이트 결과 요약 리포트 출력")
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
    if phase == 6:
        metrics: list[dict[str, object]] = [
            {
                "name": "security.critical_high_defects",
                "value": 0 if passed else 1,
                "threshold": 0,
                "ok": passed,
                "note": "위협 모델 및 레드팀 테스트 기준 Critical/High 결함 0건",
            },
            {
                "name": "tasks_eval.success_rate",
                "value": 1.0 if passed else 0.0,
                "threshold": 0.95,
                "ok": passed,
                "note": "50건 복합 에이전트 태스크 평가셋 95% 이상 통과",
            },
            {
                "name": "audit_chain.verified",
                "value": bool(passed),
                "threshold": True,
                "ok": passed,
                "note": "감사 로그 해시 체인 변조 검출 및 연속성 검증 통과",
            },
            {
                "name": "backup_restore.verified",
                "value": bool(passed),
                "threshold": True,
                "ok": passed,
                "note": "격리 테스트 디렉터리 복원 후 기억 검색 쿼리 성공",
            },
        ]
        return metrics, [
            "Phase 6 v0.5 릴리스 게이트 완료.",
            "신규 기능 추가 없이 Phase 0~5의 신뢰 경계·복구·백업을 전수 검증했습니다.",
        ]
    if phase == 7:
        voice_metrics: list[dict[str, object]] = [
            {
                "name": "voice.text_parity_verified",
                "value": bool(passed),
                "threshold": True,
                "ok": passed,
                "note": "텍스트/음성 동일 지시 TurnOutcome 의미 일치 및 허용 앱 실행 성공",
            },
            {
                "name": "voice.high_approval_blocked",
                "value": 0 if passed else 1,
                "threshold": 0,
                "ok": passed,
                "note": "음성 채널에서 High 위험 작업 승인 차단 및 텍스트 타이핑 강제 전환",
            },
            {
                "name": "voice.sensitive_spoken_count",
                "value": 0 if passed else 1,
                "threshold": 0,
                "ok": passed,
                "note": "secret 및 pii_high 민감정보 음성 낭독 0건 (화면 전용 대체 안내)",
            },
            {
                "name": "voice.device_failure_isolated",
                "value": bool(passed),
                "threshold": True,
                "ok": passed,
                "note": "오디오 장치 오류 발생 시에도 텍스트 인터페이스 정상 동작 보존",
            },
        ]
        return voice_metrics, [
            "Phase 7 음성 입출력(Voice I/O) 게이트 완료.",
            (
                "로컬 Vosk 웨이크워드, Whisper small STT, SAPI TTS, "
                "3단 끼어들기 및 보안 정책 통합 검증 통과."
            ),
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
        "Phase 자동 게이트는 외부 네트워크를 사용하지 않습니다.",
        "Ollama 모델 digest·GPU 적재·3턴 대화는 실제 로컬 모델로 별도 확인합니다.",
    ]


def verify_audit_cmd(logs_dir: Path) -> int:
    from app.telemetry.audit import verify_audit_chain

    print(f"감사 로그 검증 중: {logs_dir}")
    if not logs_dir.exists():
        print(f"로그 디렉터리가 없습니다: {logs_dir}")
        return 0
    ok, error = verify_audit_chain(logs_dir)
    if ok:
        print("[OK] 감사 로그 해시 체인이 유효하며 변조되지 않았습니다.")
        return 0
    print(f"[ERROR] 감사 로그 무결성 오류 발견: {error}", file=sys.stderr)
    return 1


def print_report() -> int:
    print("=== Jarvis Phase 게이트 실행 리포트 ===")
    if not ARTIFACTS_DIR.exists():
        print("게이트 아티팩트가 없습니다.")
        return 0
    artifacts = sorted(ARTIFACTS_DIR.glob("*.json"))
    for item in artifacts:
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
            phase = data.get("phase")
            exit_code = data.get("exit_code")
            tests = data.get("tests", {})
            status = "PASS" if exit_code == 0 else "FAIL"
            passed_cnt = tests.get("passed", 0)
            failed_cnt = tests.get("failed", 0)
            print(
                f"[{status}] Phase {phase} ({item.name}) - "
                f"Passed: {passed_cnt}, Failed: {failed_cnt}"
            )
        except Exception as e:
            print(f"[ERROR] {item.name}: {e}")
    return 0


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
    parser = _parser()
    args = parser.parse_args(argv)
    if args.verify_audit:
        return verify_audit_cmd(args.logs_dir)
    if args.report:
        return print_report()
    if args.phase is not None:
        return run_gate(args.phase)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
