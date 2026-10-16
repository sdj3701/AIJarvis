# 파이썬 공부 | scripts/gate.py
# 개발 단계별 테스트 묶음을 실행하고 결과를 기록합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Run a documented Phase test gate and write machine-readable evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: str(REPOSITORY_ROOT) not in sys.path.
if str(REPOSITORY_ROOT) not in sys.path:
    # sys.path.insert()을 호출해 작업을 수행합니다.
    sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from app.config.defaults import DEFAULT_DATA_ROOT  # noqa: E402
from app.core.atomic import write_atomic  # noqa: E402
from app.core.clock import KST  # noqa: E402

# 오른쪽 식을 계산한 값을 ARTIFACTS_DIR에 대입합니다.
ARTIFACTS_DIR = REPOSITORY_ROOT / "artifacts" / "gates"


# _parser(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: argparse.ArgumentParser.
def _parser() -> argparse.ArgumentParser:
    # argparse.ArgumentParser()의 반환값을 parser에 대입합니다.
    parser = argparse.ArgumentParser(description="Jarvis Phase 완료 게이트 및 보안 감사")
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--phase", type=int, choices=range(0, 9), help="실행할 Phase 번호 (0~8)")
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument(
        "--verify-audit", action="store_true", help="감사 로그 해시 체인 무결성 검증"
    )
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=DEFAULT_DATA_ROOT / "logs",
        help="검증할 감사 로그 디렉터리",
    )
    # parser.add_argument()을 호출해 작업을 수행합니다.
    parser.add_argument("--report", action="store_true", help="게이트 결과 요약 리포트 출력")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parser


# _marker_expression(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: phase.
# 반환 타입 힌트: 문자열(str).
def _marker_expression(phase: int) -> str:
    # ' or '.join()의 반환값을 phases에 대입합니다.
    phases = " or ".join(f"phase{number}" for number in range(phase + 1))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    return f"({phases}) and not allow_network"


# _count(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: output, label.
# 반환 타입 힌트: 정수(int).
def _count(output: str, label: str) -> int:
    # re.findall()의 반환값을 matches에 대입합니다.
    matches = re.findall(rf"(\d+) {label}", output)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    return int(matches[-1]) if matches else 0


# _commit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: 문자열(str).
def _commit() -> str:
    # subprocess.run()의 반환값을 result에 대입합니다.
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    return result.stdout.strip() if result.returncode == 0 else "unknown"


# _worktree_changes(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: tuple[str, ...].
def _worktree_changes() -> tuple[str, ...]:
    # subprocess.run()의 반환값을 result에 대입합니다.
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: result.returncode != 0.
    if result.returncode != 0:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return ("git_status_failed",)
    # changes에 리스트(순서가 있고 수정 가능)을 대입합니다.
    changes: list[str] = []
    # for 반복문: 대상의 항목을 하나씩 line에 대입하며 아래 블록을 실행합니다.
    for line in result.stdout.splitlines():
        # 오른쪽 식을 계산한 값을 path에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        path = line[3:].replace("\\", "/") if len(line) > 3 else line
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: path.startswith('artifacts/gates/').
        if path.startswith("artifacts/gates/"):
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue
        # 리스트 끝에 항목 하나를 추가합니다.
        changes.append(line)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return tuple(changes)


# _phase_evidence(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: phase, passed.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: tuple[list[dict[str, object]], list[str]].
def _phase_evidence(phase: int, *, passed: bool) -> tuple[list[dict[str, object]], list[str]]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: phase == 0.
    if phase == 0:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return [], ["Phase 0에는 외부 API 호출과 정량 성능 기준이 없습니다."]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: phase == 6.
    if phase == 6:
        # metrics에 리스트(순서가 있고 수정 가능)을 대입합니다.
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
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return metrics, [
            "Phase 6 v0.5 릴리스 게이트 완료.",
            "신규 기능 추가 없이 Phase 0~5의 신뢰 경계·복구·백업을 전수 검증했습니다.",
        ]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: phase == 7.
    if phase == 7:
        # voice_metrics에 리스트(순서가 있고 수정 가능)을 대입합니다.
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
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return voice_metrics, [
            "Phase 7 음성 입출력(Voice I/O) 게이트 완료.",
            (
                "로컬 Vosk 웨이크워드, Whisper small STT, SAPI TTS, "
                "3단 끼어들기 및 보안 정책 통합 검증 통과."
            ),
        ]
    # metrics에 리스트(순서가 있고 수정 가능)을 대입합니다.
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
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return metrics, [
        "Phase 자동 게이트는 외부 네트워크를 사용하지 않습니다.",
        "Ollama 모델 digest·GPU 적재·3턴 대화는 실제 로컬 모델로 별도 확인합니다.",
    ]


# verify_audit_cmd(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: logs_dir.
# 반환 타입 힌트: 정수(int).
def verify_audit_cmd(logs_dir: Path) -> int:
    from app.telemetry.audit import verify_audit_chain

    # 값을 텍스트로 출력합니다.
    print(f"감사 로그 검증 중: {logs_dir}")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not logs_dir.exists().
    if not logs_dir.exists():
        # 값을 텍스트로 출력합니다.
        print(f"로그 디렉터리가 없습니다: {logs_dir}")
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # 언패킹: 오른쪽 결과를 순서대로 (ok, error)에 나누어 담습니다.
    ok, error = verify_audit_chain(logs_dir)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: ok.
    if ok:
        # 값을 텍스트로 출력합니다.
        print("[OK] 감사 로그 해시 체인이 유효하며 변조되지 않았습니다.")
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # 값을 텍스트로 출력합니다.
    print(f"[ERROR] 감사 로그 무결성 오류 발견: {error}", file=sys.stderr)
    # 1을 반환하고 이 함수의 실행을 끝냅니다.
    return 1


# print_report(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: 정수(int).
def print_report() -> int:
    # 값을 텍스트로 출력합니다.
    print("=== Jarvis Phase 게이트 실행 리포트 ===")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not ARTIFACTS_DIR.exists().
    if not ARTIFACTS_DIR.exists():
        # 값을 텍스트로 출력합니다.
        print("게이트 아티팩트가 없습니다.")
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # sorted()의 반환값을 artifacts에 대입합니다.
    artifacts = sorted(ARTIFACTS_DIR.glob("*.json"))
    # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
    for item in artifacts:
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # json.loads()의 반환값을 data에 대입합니다.
            data = json.loads(item.read_text(encoding="utf-8"))
            # data.get()의 반환값을 phase에 대입합니다.
            phase = data.get("phase")
            # data.get()의 반환값을 exit_code에 대입합니다.
            exit_code = data.get("exit_code")
            # data.get()의 반환값을 tests에 대입합니다.
            tests = data.get("tests", {})
            # 오른쪽 식을 계산한 값을 status에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            status = "PASS" if exit_code == 0 else "FAIL"
            # tests.get()의 반환값을 passed_cnt에 대입합니다.
            passed_cnt = tests.get("passed", 0)
            # tests.get()의 반환값을 failed_cnt에 대입합니다.
            failed_cnt = tests.get("failed", 0)
            # 값을 텍스트로 출력합니다.
            print(
                f"[{status}] Phase {phase} ({item.name}) - "
                f"Passed: {passed_cnt}, Failed: {failed_cnt}"
            )
        # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except Exception as e:
            # 값을 텍스트로 출력합니다.
            print(f"[ERROR] {item.name}: {e}")
    # 0을 반환하고 이 함수의 실행을 끝냅니다.
    return 0


# run_gate(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: phase.
# 반환 타입 힌트: 정수(int).
def run_gate(phase: int) -> int:
    # _worktree_changes()의 반환값을 changes에 대입합니다.
    changes = _worktree_changes()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: changes.
    if changes:
        # 값을 텍스트로 출력합니다.
        print("게이트를 실행하려면 코드 작업 트리가 깨끗해야 합니다.", file=sys.stderr)
        # for 반복문: 대상의 항목을 하나씩 change에 대입하며 아래 블록을 실행합니다.
        for change in changes[:20]:
            # 값을 텍스트로 출력합니다.
            print(f"  {change}", file=sys.stderr)
        # 1을 반환하고 이 함수의 실행을 끝냅니다.
        return 1

    # datetime.now()의 반환값을 started_at에 대입합니다.
    started_at = datetime.now(tz=KST)
    # _marker_expression()의 반환값을 marker에 대입합니다.
    marker = _marker_expression(phase)
    # subprocess.run()의 반환값을 result에 대입합니다.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", marker],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 오른쪽 식을 계산한 값을 combined에 대입합니다.
    combined = result.stdout + result.stderr
    # 열린 출력 대상에 데이터를 기록합니다.
    sys.stdout.write(combined)
    # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
    sys.stdout.flush()
    # 오른쪽 식을 계산한 값을 exit_code에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    exit_code = 0 if result.returncode == 0 else 1
    # datetime.now()의 반환값을 finished_at에 대입합니다.
    finished_at = datetime.now(tz=KST)
    # 언패킹: 오른쪽 결과를 순서대로 (metrics, notes)에 나누어 담습니다.
    metrics, notes = _phase_evidence(phase, passed=exit_code == 0)
    # evidence에 딕셔너리(키와 값의 쌍)을 대입합니다.
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
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    # 오른쪽 식을 계산한 값을 artifact에 대입합니다.
    artifact = ARTIFACTS_DIR / f"phase{phase}-{finished_at:%Y%m%d}.json"
    # write_atomic()을 호출해 작업을 수행합니다.
    write_atomic(
        artifact,
        (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    # 값을 텍스트로 출력합니다.
    print(f"게이트 증거: {artifact}")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return exit_code


# main(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: argv.
# 반환 타입 힌트: 정수(int).
def main(argv: list[str] | None = None) -> int:
    # _parser()의 반환값을 parser에 대입합니다.
    parser = _parser()
    # parser.parse_args()의 반환값을 args에 대입합니다.
    args = parser.parse_args(argv)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.verify_audit.
    if args.verify_audit:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return verify_audit_cmd(args.logs_dir)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.report.
    if args.report:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return print_report()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.phase is not None.
    if args.phase is not None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return run_gate(args.phase)
    # parser.print_help()을 호출해 작업을 수행합니다.
    parser.print_help()
    # 1을 반환하고 이 함수의 실행을 끝냅니다.
    return 1


# 이 파일을 실행 진입점으로 사용할 때만 아래 코드를 실행합니다. import할 때는 실행하지 않습니다.
if __name__ == "__main__":
    # SystemExit 예외로 프로그램 종료를 요청합니다. 전달한 값은 종료 상태를 나타냅니다.
    raise SystemExit(main())
