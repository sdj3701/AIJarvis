# 개발 진행 현황

이 파일은 현재 상태만 기록하는 운영형 문서다. 상세 요구나 설계를 복사하지 않고 Phase 문서의 작업 ID와 검증 증거만 연결한다.

> 마지막 문서 정리: 2026-08-18 (v2 재구축 현황 리셋)
> 현재 상태: 착수 완료, `rebuild/v2` Phase 0 재구축 미착수
> 현재 Phase: Phase 0
> 착수 전 환경 조건: Python 3.13.15 설치 및 실행 확인. Phase 0 진입 조건을 충족한다.
> 브랜치: `rebuild/v2`. 프로토타입 게이트 기록은 비교용이며 v2 완료가 아니다.

## 1. 상태 값

- `not_started`: 미착수
- `in_progress`: 작업 중
- `blocked`: 외부 결정·환경·결함 때문에 진행 불가
- `gate_failed`: 구현됐지만 Phase 게이트 실패
- `completed`: 게이트 종료 코드 0과 증거 기록 완료

## 2. Phase 대시보드

아래 상태는 `rebuild/v2` 기준이다. 프로토타입 `main`의 완료 기록은 5장에만 남긴다.

| Phase | 상태 | 구현 문서 | 게이트 증거 | 비고 |
|-------|------|-----------|-------------|------|
| 0 기반 | not_started | [Phase 0](./phase-00-foundation/README.md) | — | 착수·경로 분리 완료. P0-01부터 재구축 |
| 1 대화 | not_started | [Phase 1](./phase-01-chat/README.md) | — | D005 decided |
| 2 기억 | not_started | [Phase 2](./phase-02-memory/README.md) | — | |
| 3 검색/RAG | not_started | [Phase 3](./phase-03-research/README.md) | — | D006 decided, D012 pending |
| 4 PC 도구 | not_started | [Phase 4](./phase-04-tools/README.md) | — | |
| 5 에이전트 | not_started | [Phase 5](./phase-05-agent/README.md) | — | |
| 6 보안 게이트 | not_started | [Phase 6](./phase-06-security/README.md) | — | D007~D008 필요 |
| 7 음성 | not_started | [Phase 7](./phase-07-voice/README.md) | — | D009·D010·D016~D018 decided |
| 8 상주 UI | not_started | [Phase 8](./phase-08-resident-ui/README.md) | — | D013~D015 필요 |
| v1 안정화 | not_started | [운영](./operations/README.md) | — | 7일 기록 필요 |

## 3. 현재 작업 큐

Phase 0 문서의 작업 ID와 동일하게 유지한다.

| 작업 | 상태 | 담당 | 시작 | 완료 | 증거/메모 |
|------|------|------|------|------|-----------|
| P0-01 프로젝트와 품질 도구 | not_started | — | — | — | |
| P0-02 설정 모델과 로더 | not_started | — | — | — | |
| P0-03 시크릿 로더 | not_started | — | — | — | |
| P0-04 공통 타입 | not_started | — | — | — | |
| P0-05 데이터 트리와 SQLite | not_started | — | — | — | |
| P0-06 이벤트·마스킹 | not_started | — | — | — | |
| P0-07 원자적 쓰기·복구·단일 인스턴스 | not_started | — | — | — | |
| P0-08 CLI와 조립 | not_started | — | — | — | |

Phase가 바뀌면 이 표를 새 Phase 작업 ID로 교체한다. 완료 이력은 아래 증거 로그에 남기므로 이전 작업 표를 계속 누적하지 않는다.

## 4. 현재 blocker

Phase 0을 막는 항목은 없다.

| 결정/문제 | 영향 | 상태 | 해결 문서 |
|-----------|------|------|-----------|
| D005 LLM 런타임·모델 | Phase 1 | decided | [DECISIONS](./00-start-here/DECISIONS.md) |
| D006 검색 API | Phase 3 웹 검색 | decided (duckduckgo) | [DECISIONS](./00-start-here/DECISIONS.md) |
| D012 PDF parser | Phase 3 PDF | pending, `.pdf` 비활성 | [DECISIONS](./00-start-here/DECISIONS.md) |
| D007~D008 백업 | Phase 6 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |
| D009 TTS·D010 호출·D016 STT | Phase 7 | decided | [DECISIONS](./00-start-here/DECISIONS.md) |
| D017 끼어들기 게이트 | Phase 7 | decided | [VOICE_BARGE_IN_GATE](./reference/VOICE_BARGE_IN_GATE.md) |
| D018 호출·한 문장 명령 | Phase 7 | decided | [VOICE_WAKE_COMMAND_UX](./reference/VOICE_WAKE_COMMAND_UX.md) |
| D013~D015 패키징/UI | Phase 8 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |

D005~D018은 Phase 0 진입을 막지 않는다. 해당 Phase에 들어가기 전에 다시 확인한다.

## 5. Phase 게이트 증거 로그

Phase를 완료할 때 행을 추가한다. 프로토타입 행은 비교용이며 `rebuild/v2` 완료로 쓰지 않는다.

| 날짜 | Phase | commit/build | 명령 | 종료 코드 | 핵심 지표 | 증거 경로 |
|------|-------|--------------|------|-----------|-----------|-----------|
| 2026-08-11 | Phase 0 (prototype-v1) | 298f093 | `python scripts\gate.py --phase 0` | 0 | 137 passed, failed 0, skipped 0 | [phase0-20260811.json](../artifacts/gates/phase0-20260811.json) |
| 2026-08-11 | Phase 1 (prototype-v1) | 368e8e4 | `python scripts\gate.py --phase 1` | 0 | 283 passed, failed 0, skipped 0, crash 20/20 입력 유실 0 | [phase1-20260811.json](../artifacts/gates/phase1-20260811.json) |
| 2026-08-11 | Phase 2 (prototype-v1) | 40ba9cc | `python scripts\gate.py --phase 2` | 0 | 300 passed, failed 0, skipped 0, memory_eval ≥90% | [phase2-20260811.json](../artifacts/gates/phase2-20260811.json) |
| 2026-08-11 | Phase 3 (prototype-v1) | 40ba9cc | `python scripts\gate.py --phase 3` | 0 | 337 passed, failed 0, skipped 0, security·phase3 green | [phase3-20260811.json](../artifacts/gates/phase3-20260811.json) |
| 2026-08-11 | Phase 4 (prototype-v1) | 40ba9cc | `python scripts\gate.py --phase 4` | 0 | 379 passed, failed 0, skipped 0, phase4·security green | [phase4-20260811.json](../artifacts/gates/phase4-20260811.json) |
| 2026-08-11 | Phase 5 (prototype-v1) | 40ba9cc | `python scripts\gate.py --phase 5` | 0 | 393 passed, failed 0, skipped 0, phase5·security green | [phase5-20260811.json](../artifacts/gates/phase5-20260811.json) |
| 2026-08-18 | Phase 0 (경로 정리, 재구축 완료 아님) | 4ed1eaf | `python scripts\gate.py --phase 0` | 0 | 148 passed, failed 0, skipped 0 | [phase0-20260818.json](../artifacts/gates/phase0-20260818.json) |

기록 예:

```text
2026-08-20 | Phase 1 | abc1234 | python scripts\gate.py --phase 1
0 | crash 20/20, retry 통과 | artifacts/gates/phase1-20260820.json
```

## 6. 업데이트 규칙

1. 작업 시작 전에 현재 작업 행을 `in_progress`로 바꾼다.
2. 테스트 실패만으로 `blocked`를 쓰지 않는다. 구현 문제는 `in_progress` 또는 `gate_failed`다.
3. 외부 결정이 없으면 안전하게 진행할 수 없는 경우만 `blocked`다.
4. Phase 완료는 사람이 판단하지 않고 gate 종료 코드 0으로만 기록한다.
5. 코드·스키마·정책이 바뀌면 관련 기준 문서를 먼저 수정한다.
6. 실패 로그에 시크릿·대화 원문을 붙이지 않는다.
7. `rebuild/v2` 완료 행은 해당 브랜치에서 게이트를 통과한 뒤에만 추가한다.
