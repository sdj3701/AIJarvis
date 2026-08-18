# 개발 진행 현황

이 파일은 현재 상태만 기록하는 운영형 문서다. 상세 요구나 설계를 복사하지 않고 Phase 문서의 작업 ID와 검증 증거만 연결한다.

> 마지막 문서 정리: 2026-08-12 (FLOW + flow/ 세분화, Phase 6 착수)
> 현재 상태: Phase 5 완료 → G6 보안 게이트 진행 중
> 현재 Phase: Phase 6 (P6-01~P6-04·P6-07 우선, D007~D008은 백업 완료에 필요)
> 큰 흐름: [FLOW.md](./FLOW.md) · 세분화: [flow/G6-security.md](./flow/G6-security.md)
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
| 0 기반 | completed | [Phase 0](./phase-00-foundation/README.md) | [phase0-20260811.json](../artifacts/gates/phase0-20260811.json) | P0-01~P0-08 완료, 137 passed |
| 1 대화 | completed | [Phase 1](./phase-01-chat/README.md) | [phase1-20260811.json](../artifacts/gates/phase1-20260811.json) | P1-01~P1-07 완료, 283 passed |
| 2 기억 | completed | [Phase 2](./phase-02-memory/README.md) | [phase2-20260811.json](../artifacts/gates/phase2-20260811.json) | P2-01~P2-07 완료, 300 passed |
| 3 검색/RAG | completed | [Phase 3](./phase-03-research/README.md) | [phase3-20260811.json](../artifacts/gates/phase3-20260811.json) | P3-01~P3-08 완료, 337 passed |
| 4 PC 도구 | completed | [Phase 4](./phase-04-tools/README.md) | [phase4-20260811.json](../artifacts/gates/phase4-20260811.json) | P4-01~P4-07 완료, 379 passed |
| 5 에이전트 | completed | [Phase 5](./phase-05-agent/README.md) | [phase5-20260811.json](../artifacts/gates/phase5-20260811.json) | TaskStore·멀티스텝·복구, 393 passed |
| 6 보안 게이트 | in_progress | [Phase 6](./phase-06-security/README.md) · [G6](./flow/G6-security.md) | — | P6-01~04 우선, D007~D008은 백업 |
| 7 음성 | not_started | [Phase 7](./phase-07-voice/README.md) | — | 하이브리드 STT·적응형 VAD 끼어들기·1.55배 TTS 선행 구현, 사람 발화 스모크와 정식 게이트는 별도 |
| 8 상주 UI | not_started | [Phase 8](./phase-08-resident-ui/README.md) | — | D013~D015 필요 |
| v1 안정화 | not_started | [운영](./operations/README.md) | — | 7일 기록 필요 |

## 3. 현재 작업 큐

Phase 6 문서·[G6 세분화](./flow/G6-security.md)의 작업 ID와 동일하게 유지한다.

| 작업 | 상태 | 담당 | 시작 | 완료 | 증거/메모 |
|------|------|------|------|------|-----------|
| P6-01 위협 모델 검토 | completed | Cursor | 2026-08-12 | 2026-08-12 | THREAT_MODEL T01~T20 연결 |
| P6-02 보안 코퍼스 완성 | in_progress | Cursor | 2026-08-12 | — | tool_name 변경 케이스 추가, 나머지 확장 예정 |
| P6-03 시크릿 유출 매트릭스 | completed | Cursor | 2026-08-12 | 2026-08-12 | LLM/로그/raw/기억/TTS, user_explicit 우회 제거 |
| P6-04 감사 로그 검증기 | completed | Cursor | 2026-08-12 | 2026-08-12 | gate --verify-audit/--integrity/--report |
| P6-05 백업 | blocked | — | — | — | D007·D008 필요 |
| P6-06 복원 | blocked | — | — | — | D007·D008 필요 |
| P6-07 공급망·설정 검토 | not_started | — | — | — | lockfile·dev_mode |
| P6-08 정량 게이트 | blocked | — | — | — | 복원·95% 태스크 포함 |

Phase가 바뀌면 이 표를 새 Phase 작업 ID로 교체한다. 완료 이력은 아래 증거 로그에 남기므로 이전 작업 표를 계속 누적하지 않는다.

## 4. 현재 blocker

| 결정/문제 | 영향 | 상태 | 해결 문서 |
|-----------|------|------|-----------|
| D005 LLM 런타임·모델 | Phase 1 | decided | [DECISIONS](./00-start-here/DECISIONS.md) |
| D006 검색 API | Phase 3 웹 검색 | decided (duckduckgo) | [DECISIONS](./00-start-here/DECISIONS.md) |
| D017 끼어들기 게이트 | Speaking 중 적응형 게이트·VAD | decided, S1 구현 | [VOICE_BARGE_IN_GATE](./reference/VOICE_BARGE_IN_GATE.md) |
| D018 호출·한 문장 명령 | 오호출·한 문장·핫키 중단 | decided, 구현 | [VOICE_WAKE_COMMAND_UX](./reference/VOICE_WAKE_COMMAND_UX.md) |
| D012 PDF parser | Phase 3 PDF | pending, `.pdf` 비활성 | [DECISIONS](./00-start-here/DECISIONS.md) |
| D007~D008 백업 | Phase 6 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |
| D009 TTS·D016 STT | Phase 7 | decided | [DECISIONS](./00-start-here/DECISIONS.md) |
| D013~D015 패키징/UI | Phase 8 | pending | [DECISIONS](./00-start-here/DECISIONS.md) |
D006~D018은 완료된 Phase 0~1에 영향을 주지 않는다. D005는 Ollama + `qwen3.5:9b`,
D009는 Windows SAPI 로컬 한국어 TTS, D016은 Vosk 호출어 + faster-whisper small 질문
인식으로 해소되었다. D017은 Gate A+B+WebRTC VAD S1 구현으로 해소되었고 스피커
실장치 S2 검증은 남아 있다. D018은 `[unk]`·한 문장 명령·답변 중단 핫키로 해소되었고
실장치 체감 확인이 남아 있다.

## 5. Phase 게이트 증거 로그

Phase를 완료할 때 행을 추가한다.

| 날짜 | Phase | commit/build | 명령 | 종료 코드 | 핵심 지표 | 증거 경로 |
|------|-------|--------------|------|-----------|-----------|-----------|
| 2026-08-11 | Phase 0 | 298f093 | `python scripts\gate.py --phase 0` | 0 | 137 passed, failed 0, skipped 0 | [phase0-20260811.json](../artifacts/gates/phase0-20260811.json) |
| 2026-08-11 | Phase 1 | 368e8e4 | `python scripts\gate.py --phase 1` | 0 | 283 passed, failed 0, skipped 0, crash 20/20 입력 유실 0 | [phase1-20260811.json](../artifacts/gates/phase1-20260811.json) |
| 2026-08-11 | Phase 2 | 40ba9cc | `python scripts\gate.py --phase 2` | 0 | 300 passed, failed 0, skipped 0, memory_eval ≥90% | [phase2-20260811.json](../artifacts/gates/phase2-20260811.json) |
| 2026-08-11 | Phase 3 | 40ba9cc | `python scripts\gate.py --phase 3` | 0 | 337 passed, failed 0, skipped 0, security·phase3 green | [phase3-20260811.json](../artifacts/gates/phase3-20260811.json) |
| 2026-08-11 | Phase 4 | 40ba9cc | `python scripts\gate.py --phase 4` | 0 | 379 passed, failed 0, skipped 0, phase4·security green | [phase4-20260811.json](../artifacts/gates/phase4-20260811.json) |
| 2026-08-11 | Phase 5 | 40ba9cc | `python scripts\gate.py --phase 5` | 0 | 393 passed, failed 0, skipped 0, phase5·security green | [phase5-20260811.json](../artifacts/gates/phase5-20260811.json) |

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
