# L4 — 손 있는 비서

이전: [L3](./L3-research.md) · 다음: [L5](./L5-agent.md)  
구현: [phase-04-tools](../phase-04-tools/README.md) · 큰 흐름: [FLOW](../FLOW.md)

## 이 단계에서 얻는 것

화이트리스트·승인·경로 검증 아래에서 PC 도구를 실행한다. “앱·폴더를 대신 열어 준다.”

## 진입

- Phase 3(MVP) 게이트 통과
- tools default deny, forbidden 목록 고정

## 핵심 산출

- Safety Gate + Secure Runner (`shell=False`, canonical path)
- 승인 ticket (인자 hash 바인딩)
- 감사 로그 flush

## 넘어가는 조건

Phase 4 게이트 0. 승인 없이 High 부작용 0, traversal/reparse 우회 0.

## 구현 시 볼 작업

P4-01~P4-07 — 레지스트리·스키마·게이트·러너·승인·감사·게이트
