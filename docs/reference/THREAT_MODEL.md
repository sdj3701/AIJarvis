# Jarvis 위협 모델

이 문서는 Phase 6에서 실제 코드·테스트 상태로 갱신한다. 현재 표의 `planned`는 문서와 테스트 계획만 존재하고 구현 검증 전이라는 의미다.

## 1. 보호 자산

- API·검색·백업 암호화 키
- 사용자 대화·기억·문서·연락처 정보
- 운영 설정과 허용 도구 정책
- 사용자 파일과 Windows 환경
- 승인 의사와 ticket
- 감사·이벤트 로그의 무결성
- 비용 예산과 API 계정

## 2. 신뢰 경계

```text
사용자/마이크
    ↓
로컬 입력·UI ── 승인 경계
    ↓
Orchestrator ── LLM 출력 경계 ── 외부 LLM API
    │
    ├── Privacy Gate ── 외부 전송 경계 ── 검색 API/Web
    ├── Memory/Docs ── 로컬 민감 데이터 경계
    └── Safety Gate/Runner ── OS 부작용 경계
```

웹, 문서, LLM, 도구 출력은 모두 권한 없는 입력이다. 사용자의 명시적 승인만 부작용 권한을 부여하며, 승인도 정확한 정규 인자 한 건에만 유효하다.

## 3. 공격자와 실패 가정

- 악성 웹페이지·문서 작성자
- 악성 또는 손상된 외부 API 응답
- 로컬에서 조작된 설정·skill 파일
- 실수로 위험한 요청을 한 정상 사용자
- 앱 크래시·전원 차단·디스크 부분 쓰기
- 취약하거나 변조된 Python 의존성
- 같은 Windows 계정에 접근한 로컬 사용자

v1은 관리자 권한 공격자나 이미 완전히 장악된 OS로부터 데이터를 보호하는 제품이 아니다. 이 잔여 위험을 숨기지 않는다.

## 4. 위협 목록

| ID | 위협 | 예방 통제 | 탐지·복구 | 검증 | 상태 |
|----|------|-----------|-----------|------|------|
| T01 | 웹/문서 prompt injection | untrusted 봉투, 사용자 의도 재검증 | tool intent 감사 | prompt injection corpus | planned |
| T02 | LLM이 임의 명령·경로 생성 | schema, root enum, Safety Gate | policy.deny | 악성 tool call 테스트 | planned |
| T03 | path traversal/reparse 우회 | canonical path, 중간 reparse 검사 | deny 이유 기록 | traversal/junction corpus | planned |
| T04 | 위험 URL/SSRF | scheme·DNS·IP·redirect 검증 | fetch 오류 이벤트 | URL corpus | planned |
| T05 | 승인 후 인자 바꿔치기 | args hash, 재평가, 1회 ticket | approval.mismatch | binding 테스트 | planned |
| T06 | 음성 승인 위조 | voice high 금지, 화면 typed confirm | approval 이벤트 | voice parity 테스트 | planned |
| T07 | 시크릿 API 전송 | Privacy Gate block | privacy.block | leak matrix | planned |
| T08 | 로그·TTS·기억 시크릿 노출 | 채널별 필터 | redact 이벤트 | secret leakage 테스트 | planned |
| T09 | 크래시 입력 유실 | append+flush+fsync | recovery event | 20회 kill 테스트 | planned |
| T10 | 크래시 후 부작용 중복 | task step, idempotency, running 보류 | 복구 UI | duplicate write 테스트 | planned |
| T11 | 감사 로그 변조 | hash chain, seq | verify-audit | tamper 테스트 | planned |
| T12 | DB 손상 | WAL/FULL, 단일 인스턴스 | integrity+backup restore | crash/restore 테스트 | planned |
| T13 | 악성 skill | disabled, hash, manifest, high 승인 | intent/result audit | hash mismatch 테스트 | planned |
| T14 | 의존성 공급망 | hash lockfile, 최소 의존성 | 정기 검토 | clean install | planned |
| T15 | 예산 폭주 | 사전 BudgetGuard, retry 한도 | 80/100% 이벤트 | budget/retry 테스트 | planned |
| T16 | 설정 완화·오타 | extra forbid, default deny 강제 | config hash | config loader 테스트 | planned |
| T17 | 백업 유출 | 암호화, 별도 target, keyring | manifest/hash | restore 테스트 | planned |
| T18 | 동시 인스턴스 데이터 손상 | OS file lock | second instance 오류 | lock 테스트 | planned |
| T19 | UI 상태 혼동으로 잘못 승인 | 단일 상태 머신, 정책 display | UI event log | state/approval UI 테스트 | planned |
| T20 | 로컬 계정 침해 | OS 계정·디스크 보안 의존 | 제한적 | 수동 검토 | accepted residual |

## 5. Phase 6 갱신 규칙

각 `planned` 행을 다음 중 하나로 바꾼다.

- `verified`: 코드와 테스트가 존재하고 통과
- `accepted residual`: 완화 후 남은 위험을 사용자가 명시적으로 수용
- `blocked`: 검증 실패로 릴리스 차단

Critical/High 위험을 `accepted residual`로 처리하려면 이유·영향·대체 통제·재검토 날짜를 별도 기록한다.

