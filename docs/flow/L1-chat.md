# L1 — 말하는 챗봇

이전: [L0](./L0-foundation.md) · 다음: [L2](./L2-memory.md)  
구현: [phase-01-chat](../phase-01-chat/README.md) · 큰 흐름: [FLOW](../FLOW.md)

## 이 단계에서 얻는 것

로컬 LLM과 멀티턴 대화하고, 사용자 입력·응답을 raw에 남긴다. 사용자는 “챗봇처럼 되고 기록이 파일로 남는다”고 느낀다.

## 진입

- Phase 0 게이트 통과
- D005 decided (현재 Ollama + `qwen3.5:9b`)

## 핵심 산출

- Orchestrator 대화 루프, 예산·재시도
- raw append+flush, 크래시 시 입력 유실 방지
- `/help` `/clear` `/budget` `/bye`

## 넘어가는 조건

Phase 1 게이트 0. loopback 외 HTTP 0건, crash 입력 유실 0.

## 구현 시 볼 작업

P1-01~P1-07 — LLM 클라이언트·프롬프트·대화 저장·재시도·컨텍스트·CLI·게이트
