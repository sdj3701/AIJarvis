# L2 — 기억하는 챗봇

이전: [L1](./L1-chat.md) · 다음: [L3](./L3-research.md)  
구현: [phase-02-memory](../phase-02-memory/README.md) · 큰 흐름: [FLOW](../FLOW.md)

## 이 단계에서 얻는 것

세션 요약·facts·corrections가 SQLite에 남아 다음 실행에 반영된다. “저번에 말한 선호를 다음에도 안다.”

## 진입

- Phase 1 게이트 통과
- 기억 lifecycle·민감정보 저장 금지 규칙 이해

## 핵심 산출

- summarizer → candidate facts
- `기억해:` / `틀림:` / `/memory` / `/forget`
- FTS 검색 후 컨텍스트 주입

## 넘어가는 조건

Phase 2 게이트 0. candidate는 승인 전 확정처럼 쓰지 않고, forget 후 검색에서 제외된다.

## 구현 시 볼 작업

P2-01~P2-07 — 스키마·요약·확정/교정·검색 주입·명령·복구·게이트
