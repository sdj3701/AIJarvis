# 개발 진행 현황

이 파일은 현재 상태만 기록하는 운영형 문서다. 상세 요구나 설계를 복사하지 않고 Phase 문서의 작업 ID와 검증 증거만 연결한다.

> 마지막 문서 정리: 2026-08-10 (기준 문서 v0.3 정합성 검토 반영)  
> 현재 상태: Phase 0 기반 구현 진행 중  
> 현재 Phase: Phase 0  
> 착수 전 환경 조건: Python 3.13.15 설치 및 실행 확인. Phase 0 진입 조건을 충족한다.

## 1. 상태 값

- `not_started`: 미착수
- `in_progress`: 작업 중
- `blocked`: 외부 결정·환경·결함 때문에 진행 불가
- `gate_failed`: 구현됐지만 Phase 게이트 실패
- `completed`: 게이트 종료 코드 0과 증거 기록 완료

## 2. Phase 대시보드

| Phase | 상태 | 구현 문서 | 게이트 증거 | 비고 |
|-------|------|-----------|-------------|------|
| 0 기반 | in_progress | [Phase 0](./phase-00-foundation/README.md) | — | P0-01~P0-02 완료, P0-03 대기 |
| 1 대화 | not_started | [Phase 1](./phase-01-chat/README.md) | — | D005 필요 |
| 2 기억 | not_started | [Phase 2](./phase-02-memory/README.md) | — | — |
| 3 검색/RAG | not_started | [Phase 3](./phase-03-research/README.md) | — | D006, PDF는 D012 |
| 4 PC 도구 | not_started | [Phase 4](./phase-04-tools/README.md) | — | — |
| 5 에이전트 | not_started | [Phase 5](./phase-05-agent/README.md) | — | — |
| 6 보안 게이트 | not_started | [Phase 6](./phase-06-security/README.md) | — | D007~D008 필요 |
| 7 음성 | not_started | [Phase 7](./phase-07-voice/README.md) | — | D009 필요 |
| 8 상주 UI | not_started | [Phase 8](./phase-08-resident-ui/README.md) | — | D013~D015 필요 |
| v1 안정화 | not_started | [운영](./operations/README.md) | — | 7일 기록 필요 |

## 3. 현재 작업 큐

Phase 0 문서의 작업 ID와 동일하게 유지한다.

| 작업 | 상태 | 담당 | 시작 | 완료 | 증거/메모 |
|------|------|------|------|------|-----------|
| P0-01 프로젝트·품질 도구 | completed | Codex | 2026-08-10 | 2026-08-10 | pytest collect·Ruff·mypy·pip check 통과, phase0 smoke 1 passed |
| P0-02 설정 모델·로더 | completed | Codex | 2026-08-10 | 2026-08-10 | 설정 테스트 31 passed, 전체 32 passed, 설정 코드 커버리지 95% |
| P0-03 시크릿 로더 | not_started | — | — | — | — |
| P0-04 공통 타입 | not_started | — | — | — | — |
| P0-05 데이터 트리·SQLite | not_started | — | — | — | — |
| P0-06 이벤트·마스킹 | not_started | — | — | — | — |
| P0-07 원자적 쓰기·복구·락 | not_started | — | — | — | — |
| P0-08 CLI·조립 | not_started | — | — | — | — |

Phase가 바뀌면 이 표를 새 Phase 작업 ID로 교체한다. 완료 이력은 아래 증거 로그에 남기므로 이전 작업 표를 계속 누적하지 않는다.

## 4. 현재 blocker

| 결정/문제 | 영향 | 상태 | 해결 문서 |
|-----------|------|------|-----------|
| D005 LLM 제공자·모델 | Phase 1 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |
| D006 검색 API | Phase 3 웹 검색 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |
| D012 PDF parser | Phase 3 PDF | pending, `.pdf` 비활성 | [DECISIONS](./00-start-here/DECISIONS.md) |
| D007~D008 백업 | Phase 6 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |
| D009 TTS | Phase 7 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |
| D013~D015 패키징/UI | Phase 8 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |
D005~D015는 Phase 0 착수를 막지 않는다. 현재 Phase 0 진입을 막는 환경 조건은 없다.

## 5. Phase 게이트 증거 로그

Phase를 완료할 때 행을 추가한다.

| 날짜 | Phase | commit/build | 명령 | 종료 코드 | 핵심 지표 | 증거 경로 |
|------|-------|--------------|------|-----------|-----------|-----------|
| — | — | — | — | — | — | — |

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
