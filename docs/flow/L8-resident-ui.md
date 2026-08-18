# L8 — 상주형 비서

이전: [L7](./L7-voice.md) · 다음: [Ops](./Ops-operations.md)  
구현: [phase-08-resident-ui](../phase-08-resident-ui/README.md) · 큰 흐름: [FLOW](../FLOW.md)

## 이 단계에서 얻는 것

트레이·전역 단축키·알림으로 상주 호출한다. v1 후보다.

## 진입

- Phase 7 게이트 통과
- D013~D015 decided (패키징·트레이/단축키·autostart)
- D011 decided (autostart 기본 false)

## 핵심 산출

- 트레이 UI, 승인·완료 알림
- 재시작 후 설정·기억·복구 유지
- 재현 가능한 패키징

## 넘어가는 조건

Phase 8 게이트 0 후 [Ops](./Ops-operations.md) 안정화로 이동.

## 구현 시 볼 작업

D013~D015가 pending이면 패키징·전역 단축키·자동 시작 구현을 시작하지 않는다.
