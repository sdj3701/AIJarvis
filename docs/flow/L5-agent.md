# L5 — 일 시키는 에이전트

이전: [L4](./L4-tools.md) · 다음: [G6](./G6-security.md)  
구현: [phase-05-agent](../phase-05-agent/README.md) · 큰 흐름: [FLOW](../FLOW.md)

## 이 단계에서 얻는 것

검색→요약→저장→폴더 열기처럼 여러 도구를 순서대로 수행한다. “찾아 → 정리 → 저장을 한 번에 한다.”

## 진입

- Phase 4 보안 테스트 녹색
- 단일 도구 승인·감사가 안정적

## 핵심 산출

- TaskStore·step idempotency
- Decide→Act→Observe, 승인 중단·재개
- running step은 자동 재실행하지 않음

## 넘어가는 조건

Phase 5 게이트 0. 중복 부작용 0, 복합 태스크 데모 가능.

## 구현 시 볼 작업

P5-01~P5-07 — TaskStore·루프·승인 재개·재시도·복구·복합 태스크·run_skill 골격
