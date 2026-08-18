# Jarvis 개발 큰 흐름

이 문서는 **제품이 시간에 따라 어떻게 성숙하는지**만 한눈에 보는 진입점이다.  
세분화된 단계 설명은 [`flow/`](./flow/README.md)에 있고, 실제 구현 체크리스트는 [`phase-*`](./README.md)에 있다.  
현재 진행 숫자·게이트 증거는 [`PROGRESS.md`](./PROGRESS.md)만 본다.

## 1. 한 줄로 보는 성숙 경로

```text
빈 골격 → 말하는 챗봇 → 기억하는 챗봇 → 찾아주는 비서
    → 손 있는 비서 → 일 시키는 에이전트 → (보안 게이트)
    → 말하는 자비스 → 상주형 비서 → 운영 안정화
```

| 성숙 단계 | 사용자가 느끼는 변화 | Phase | 세분화 문서 | 구현 문서 | 상태 |
|-----------|----------------------|-------|-------------|-----------|------|
| L0 빈 골격 | 안전하게 켜고 끌 수 있다 | 0 | [L0](./flow/L0-foundation.md) | [phase-00](./phase-00-foundation/README.md) | completed |
| L1 말하는 챗봇 | 대화되고 기록이 남는다 | 1 | [L1](./flow/L1-chat.md) | [phase-01](./phase-01-chat/README.md) | completed |
| L2 기억하는 챗봇 | 선호·교정이 다음에도 남는다 | 2 | [L2](./flow/L2-memory.md) | [phase-02](./phase-02-memory/README.md) | completed |
| L3 찾아주는 비서 | 웹/문서를 찾아 근거와 답한다 | 3 | [L3](./flow/L3-research.md) | [phase-03](./phase-03-research/README.md) | completed · MVP |
| L4 손 있는 비서 | 허용된 PC 도구를 대신 연다 | 4 | [L4](./flow/L4-tools.md) | [phase-04](./phase-04-tools/README.md) | completed |
| L5 일 시키는 에이전트 | 검색→정리→저장을 한 번에 한다 | 5 | [L5](./flow/L5-agent.md) | [phase-05](./phase-05-agent/README.md) | completed |
| G6 보안 게이트 | Critical/High 0·복원 가능 | 6 | [G6](./flow/G6-security.md) | [phase-06](./phase-06-security/README.md) | **현재 · not_started** |
| L7 말하는 자비스 | 말로 시켜도 된다 | 7 | [L7](./flow/L7-voice.md) | [phase-07](./phase-07-voice/README.md) | not_started |
| L8 상주형 비서 | 트레이·단축키로 부른다 | 8 | [L8](./flow/L8-resident-ui.md) | [phase-08](./phase-08-resident-ui/README.md) | not_started |
| Ops 운영 | 설치·백업·장애 대응이 문서화 | — | [Ops](./flow/Ops-operations.md) | [operations](./operations/README.md) | not_started |

릴리스 경계: **MVP = L0~L3**, **v0.5 = L4~G6**, **v1 = L7~L8 + Ops**.

## 2. 문서 역할 분리

| 문서 | 역할 | 복제하지 말 것 |
|------|------|----------------|
| 이 파일 (`FLOW.md`) | 성숙 경로·현재 위치·다음 한 단계 | 작업 ID·파일 목록·테스트 이름 |
| [`flow/`](./flow/README.md) | 단계별 목표·진입·산출·다음 연결 | PLAN/DESIGN 전문, 스키마 정의 |
| [`phase-*/README.md`](./README.md) | 구현 순서·파일·게이트 명령 | 제품 범위 재정의 |
| [`PROGRESS.md`](./PROGRESS.md) | 상태·작업 큐·게이트 증거 | 설계 설명 |
| [`PLAN.md`](../PLAN.md) 7장 | 제품 관점 성숙 서사 원본 | 구현 체크리스트 |

충돌 시: [문서 변경 규칙](./reference/DOCUMENTATION_RULES.md)을 따른다.

## 3. 지금 할 일

1. 현재 단계: **G6 보안 게이트** ([세분화](./flow/G6-security.md) · [구현](./phase-06-security/README.md))
2. 진입 전 결정: [D007·D008](./00-start-here/DECISIONS.md) (백업 대상·암호화 도구)
3. D007/D008이 없어도 진행 가능한 작업: P6-01~P6-04 (위협 모델·보안 코퍼스·시크릿 매트릭스·감사 검증기)
4. 백업·복원(P6-05~P6-06)과 정량 게이트(P6-08)는 D007/D008 `decided` 후에만 완료 판정

완료 판정은 사람 감이 아니라 `python scripts\gate.py --phase 6` 종료 코드 0이다.

## 4. 개발 진행 규칙

1. **수직 슬라이스:** 매 단계마다 데모 가능한 한 조각을 만든다.
2. **게이트:** Phase 게이트 실패면 다음 성숙 단계로 가지 않는다.
3. **기준 문서 우선:** 인터페이스·스키마가 바뀌면 PLAN/DESIGN/SCHEMAS를 먼저 고친다.
4. **미정 금지:** 제공자·경로·암호화는 DECISIONS에 남기고 임의 확정하지 않는다.
5. **상태 기록:** 작업 시작/완료는 PROGRESS의 현재 작업 큐만 갱신한다.

## 5. 바로가기

- [세분화 폴더](./flow/README.md)
- [개발 문서 지도](./README.md)
- [진행 현황](./PROGRESS.md)
- [착수·결정](./00-start-here/README.md)
- [제품 계획](../PLAN.md)
- [아키텍처](../DESIGN.md)
