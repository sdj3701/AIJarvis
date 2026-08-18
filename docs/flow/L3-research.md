# L3 — 찾아주는 비서 (MVP)

이전: [L2](./L2-memory.md) · 다음: [L4](./L4-tools.md)  
구현: [phase-03-research](../phase-03-research/README.md) · 큰 흐름: [FLOW](../FLOW.md)

## 이 단계에서 얻는 것

웹·로컬 문서를 찾아 출처와 함께 요약한다. MVP 경계다. “검색해서 링크와 함께 정리해 준다.”

## 진입

- Phase 2 게이트 통과
- D006 decided (DuckDuckGo). D012 pending이면 PDF 비활성

## 핵심 산출

- 웹 검색·문서 RAG, untrusted 봉투
- 근거·확인 날짜·확실/상충/근거 부족 포맷
- SSRF·local_only 전송 통제

## 넘어가는 조건

Phase 3 게이트 0. injection이 도구 호출로 이어지지 않고, local_only 원문이 외부 API에 안 간다.

## 구현 시 볼 작업

P3-01~P3-08 — 검색·페치·청킹·인용·신뢰 경계·프라이버시·평가·게이트
