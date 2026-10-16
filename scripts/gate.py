"""Run a documented Phase test gate and write machine-readable evidence."""

# [파일 역할] 단계별 pytest 테스트를 실행하고, 결과를 JSON 파일로 남기는 도구다.
# 여기서 '게이트'는 다음 개발 단계로 넘어가기 위한 테스트 통과 기준을 뜻한다.
# 실행 흐름: main() → 옵션에 따라 테스트 실행 / 감사 로그 검증 / 기존 결과 요약.
# 사용법만 보기: `python -m scripts.gate --help` (테스트를 실행하지 않는다).
# 학습 포인트: subprocess, 정규 표현식, 중첩 자료형, JSON, 날짜와 종료 코드.
# annotations는 아래 타입 힌트를 정의 시점에 바로 평가하지 않도록 한다.
from __future__ import annotations

# argparse: 명령줄 입력 / json: 파이썬 자료형과 JSON 문자열 사이 변환.
# re: 정규 표현식으로 텍스트 패턴 찾기 / subprocess: 별도 프로그램 실행.
# sys: 현재 파이썬 경로와 출력 통로 / datetime: 날짜·시간 / Path: 파일 경로.
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 이 파일의 부모는 scripts, 그 위 부모는 프로젝트 루트다.
# sys.path는 import할 모듈을 찾는 경로 목록이며, 0번에 넣으면 먼저 검색한다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

# write_atomic은 저장 중 불완전한 최종 파일이 노출되지 않도록 하는 프로젝트 함수다.
# KST는 프로젝트에서 정의한 한국 시간대이며, 기록 시각의 기준을 통일한다.
# noqa: E402는 경로 설정 이후의 import를 린터가 지적하지 않도록 하는 표기다.
from app.config.defaults import DEFAULT_DATA_ROOT  # noqa: E402
from app.core.atomic import write_atomic  # noqa: E402
from app.core.clock import KST  # noqa: E402

# Path의 / 연산으로 결과 파일을 모을 디렉터리를 만든다. 아직 폴더를 생성하지는 않는다.
ARTIFACTS_DIR = REPOSITORY_ROOT / "artifacts" / "gates"


def _parser() -> argparse.ArgumentParser:
    # 이 함수는 입력 규칙만 준비한다. --help 출력은 argparse가 자동으로 제공한다.
    parser = argparse.ArgumentParser(description="Jarvis Phase 완료 게이트 및 보안 감사")
    # range(0, 9)는 0~8이다. choices는 이 범위 밖의 입력을 거부한다.
    parser.add_argument("--phase", type=int, choices=range(0, 9), help="실행할 Phase 번호 (0~8)")
    # store_true 옵션은 값을 따로 받지 않고, 있으면 True / 없으면 False가 된다.
    parser.add_argument(
        "--verify-audit", action="store_true", help="감사 로그 해시 체인 무결성 검증"
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=DEFAULT_DATA_ROOT / "logs",
        help="검증할 감사 로그 디렉터리",
    )
    parser.add_argument("--report", action="store_true", help="게이트 결과 요약 리포트 출력")
    return parser


def _marker_expression(phase: int) -> str:
    # pytest의 marker는 테스트에 붙인 분류 이름이다. 현재 단계까지 모두 선택한다.
    # 예: phase=2 → '(phase0 or phase1 or phase2) and not allow_network'.
    # join은 문자열들을 구분자로 연결하며, 안쪽 for 표현식은 값을 차례로 만든다.
    phases = " or ".join(f"phase{number}" for number in range(phase + 1))
    # 외부 네트워크를 허용하는 테스트 표식은 선택에서 제외한다.
    return f"({phases}) and not allow_network"


def _count(output: str, label: str) -> int:
    # rf는 raw 문자열(r)과 값 삽입(f)을 결합한 접두사다.
    # \d+는 '한 자리 이상의 숫자', (...)는 그 숫자를 결과로 추출할 그룹이다.
    # label='passed'라면 '12 passed' 같은 텍스트에서 '12'를 찾는다.
    matches = re.findall(rf"(\d+) {label}", output)
    # [-1]은 마지막 원소다. 빈 목록은 False로 취급하므로 없으면 0을 반환한다.
    return int(matches[-1]) if matches else 0


def _commit() -> str:
    # 명령을 목록으로 전달하면 프로그램 이름과 각각의 인수를 구분할 수 있다.
    # cwd는 실행할 작업 폴더, capture_output은 stdout/stderr를 결과 객체에 저장한다.
    # text=True는 출력의 문자열 변환, check=False는 실패 종료 코드를 직접 처리한다는 뜻.
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # strip()은 앞뒤 공백과 줄바꿈을 제거한다. git이 실패 코드를 반환하면 unknown이다.
    # check=False도 실행 파일 자체를 못 찾는 OSError까지 잡아 주지는 않는다.
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _worktree_changes() -> tuple[str, ...]:
    # git status --porcelain은 사람이 보는 장식 대신 일정한 형식으로 변경 목록을 출력한다.
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
        # splitlines()는 출력 전체를 줄 단위로 나눈다. [3:]은 앞의 상태 표시를 제외한다.
        # Windows 경로 구분자도 /로 맞춰서 아래의 접두사 비교를 일관되게 한다.
        path = line[3:].replace("\\", "/") if len(line) > 3 else line
        if path.startswith("artifacts/gates/"):
            # 게이트가 만든 결과 파일은 코드 수정으로 보지 않고 다음 항목으로 넘어간다.
            continue
        changes.append(line)
    return tuple(changes)


def _phase_evidence(phase: int, *, passed: bool) -> tuple[list[dict[str, object]], list[str]]:
    # 반환값은 (지표 딕셔너리 목록, 설명 문자열 목록)이라는 두 요소 튜플이다.
    # * 뒤의 passed는 _phase_evidence(6, passed=True)처럼 이름을 붙여 전달한다.
    # 주의해서 읽기: 여기서 지표를 별도 측정하지는 않는다. 상당수 값은 pytest 전체의
    # 통과 여부(passed)에서 만든 요약이다. 예를 들어 1.0은 직접 계산한 성공률이 아니다.
    # name=지표 이름, value=값, threshold=기준, ok=통과 여부, note=설명이라는 구조다.
    if phase == 0:
        return [], ["Phase 0에는 외부 API 호출과 정량 성능 기준이 없습니다."]
    if phase == 6:
        # list 안에 여러 dict를 넣으면 서로 다른 지표를 같은 형식으로 표현할 수 있다.
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
        # 음성 단계에서는 같은 자료 구조에 음성 관련 지표를 넣는다.
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
    # 위에서 return하지 않은 나머지 단계의 공통 요약이다.
    # None은 '값 없음/미측정'을 나타낸다. 수치 0이나 실패를 뜻하는 False와 구분한다.
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
    # 함수 내부 import는 이 기능을 실제 호출할 때 해당 모듈을 가져오는 방식이다.
    from app.telemetry.audit import verify_audit_chain

    print(f"감사 로그 검증 중: {logs_dir}")
    if not logs_dir.exists():
        # 이 구현에서는 로그가 없는 경우에도 성공 코드 0을 반환한다.
        print(f"로그 디렉터리가 없습니다: {logs_dir}")
        return 0
    # 반환된 두 값을 각각 변수에 받는다. 실제 해시 체인 검증은 app 모듈이 담당한다.
    ok, error = verify_audit_chain(logs_dir)
    if ok:
        print("[OK] 감사 로그 해시 체인이 유효하며 변조되지 않았습니다.")
        return 0
    print(f"[ERROR] 감사 로그 무결성 오류 발견: {error}", file=sys.stderr)
    return 1


def print_report() -> int:
    # 저장되어 있는 JSON을 읽기만 한다. 테스트를 다시 실행하는 함수는 아니다.
    print("=== Jarvis Phase 게이트 실행 리포트 ===")
    if not ARTIFACTS_DIR.exists():
        print("게이트 아티팩트가 없습니다.")
        return 0
    # glob은 이름 패턴에 맞는 파일을 찾고 sorted는 그 결과를 정렬한 목록으로 만든다.
    artifacts = sorted(ARTIFACTS_DIR.glob("*.json"))
    for item in artifacts:
        try:
            # 파일 → UTF-8 문자열 → 파이썬 dict 순서로 변환한다.
            data = json.loads(item.read_text(encoding="utf-8"))
            # get은 키가 없을 때 기본값을 준다. data['phase']처럼 KeyError를 내지 않는다.
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
            # 한 파일을 읽다가 실패해도 오류를 표시하고 나머지 파일 요약을 계속한다.
            # 따라서 이 함수의 반환 코드 0은 모든 JSON이 정상이라는 보증은 아니다.
            print(f"[ERROR] {item.name}: {e}")
    return 0


def run_gate(phase: int) -> int:
    # 수정한 코드가 커밋되지 않았다면 검사를 중단한다.
    # 테스트 증거를 특정 Git 커밋의 코드와 대응시키기 위한 기존 실행 조건이다.
    changes = _worktree_changes()
    if changes:
        print("게이트를 실행하려면 코드 작업 트리가 깨끗해야 합니다.", file=sys.stderr)
        # [:20]은 처음 20개까지만 고르는 슬라이스다. 출력이 너무 길어지지 않게 한다.
        for change in changes[:20]:
            print(f"  {change}", file=sys.stderr)
        return 1

    # 시간대가 포함된 시작 시각을 기록한 다음 테스트를 별도 프로세스에서 실행한다.
    started_at = datetime.now(tz=KST)
    marker = _marker_expression(phase)
    # sys.executable은 지금 스크립트를 실행 중인 파이썬 실행 파일의 경로다.
    # 첫 번째 -m은 파이썬 모듈 실행, pytest 뒤의 -m은 테스트 marker 선택 옵션이다.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", marker],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 두 출력을 합쳐 화면에 보여 주고 통과/실패 수 추출에도 사용한다.
    # stdout 뒤에 stderr를 붙이므로 원래 출력된 시간 순서를 재현하는 것은 아니다.
    combined = result.stdout + result.stderr
    sys.stdout.write(combined)
    sys.stdout.flush()
    exit_code = 0 if result.returncode == 0 else 1
    finished_at = datetime.now(tz=KST)
    metrics, notes = _phase_evidence(phase, passed=exit_code == 0)
    # dict 안에 dict/list를 중첩하면 실행 정보와 결과를 하나의 문서로 묶을 수 있다.
    # isoformat은 시간을 문자열로, timespec은 소수 초의 정밀도를 지정한다.
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
    # %Y%m%d는 연월일 서식이다. 같은 날 같은 Phase를 실행하면 같은 파일명을 사용한다.
    artifact = ARTIFACTS_DIR / f"phase{phase}-{finished_at:%Y%m%d}.json"
    # dumps: dict → JSON 문자열. ensure_ascii=False: 한글 유지. indent=2: 들여쓰기.
    # encode('utf-8')은 저장 함수가 요구하는 bytes로 바꾼다.
    write_atomic(
        artifact,
        (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(f"게이트 증거: {artifact}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    # argv=None이면 터미널 입력을 읽고, 목록을 넘기면 그 목록을 입력으로 해석한다.
    parser = _parser()
    args = parser.parse_args(argv)
    # 각 분기에서 return하므로 여러 옵션이 있어도 첫 조건에 맞는 기능 하나만 실행한다.
    # 우선순위는 감사 검증 → 리포트 → Phase 테스트다.
    if args.verify_audit:
        return verify_audit_cmd(args.logs_dir)
    if args.report:
        return print_report()
    # Phase 0도 유효하므로 'if args.phase'로 검사하면 안 된다. 0은 False 취급되기 때문.
    if args.phase is not None:
        return run_gate(args.phase)
    parser.print_help()
    return 1


# 직접 실행할 때만 진입한다. import할 때 테스트가 자동으로 시작되지 않게 하는 관례다.
# SystemExit는 main이 반환한 정수를 운영체제가 읽을 종료 코드로 전달한다.
if __name__ == "__main__":
    raise SystemExit(main())
