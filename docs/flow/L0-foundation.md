# L0 — 빈 골격

이전: [착수](../00-start-here/README.md) · 다음: [L1 말하는 챗봇](./L1-chat.md)  
구현: [phase-00-foundation](../phase-00-foundation/README.md) · 큰 흐름: [FLOW](../FLOW.md)

## 이 단계에서 얻는 것

외부 API·PC 도구 없이, 설정·로그·락·SQLite 골격을 갖춘 CLI를 안전하게 켜고 끈다.

## 진입

- 착수 체크리스트 완료
- D001~D004 decided (소스/운영 경로, 저장, 패키지)

## 핵심 산출

- bootstrap으로 `D:\Jarvis` 트리 준비
- 설정 검증·단일 인스턴스·이벤트 로그·원자적 쓰기
- `python -m app` 에코 CLI (LLM 없음)

## 넘어가는 조건

Phase 0 게이트 종료 코드 0. 시크릿 평문 로그·운영 경로 테스트 오염이 없어야 한다.

## 구현 시 볼 작업

P0-01~P0-08 — 프로젝트·설정·시크릿·코어·텔레메트리·메모리 스키마·CLI·게이트
