# Jarvis 개발 문서 지도

2026-10-16 폴더 구조와 실행 방법은 [저장소 구조](REPOSITORY_LAYOUT.md), RAG 개발은 [RAG 문서](rag/README.md), 평가 결과는 [평가 안내](evaluations/README.md)에 정리했다.

최신 변경: [PDF Markdown 파일 자동 저장·DB 보존·제공 PDF 검증](rag/RAG_PDF_INGESTION.md).

이 디렉터리는 실제 구현 순서대로 정렬된 실행 문서다. 루트의 [README.md](PROJECT.md)가 전체 진입점이고, 이 파일은 세부 탐색용 색인이다.

작업 ID 단위로 이어 붙인 전체 순서는 [개발 흐름](DEVELOPMENT_FLOW.md)에 있다. 어느 작업이 끝나면 무엇이 열리는지 한 문서에서 확인할 수 있다.

현재 상태와 다음 작업은 [PROGRESS.md](PROGRESS.md)에서 관리한다. `main`의 v2 구현에는
대화·문서 RAG·임베딩·재정렬과 [R3 개선](phase-03-research/README.md)의 코드·자동 평가가 적용되어 있다.
아래 Phase 순서는 전체 계획이며 현재 구현 완료나 릴리스 인증을 뜻하지 않는다.

RAG 문서 개정: [구조와 개발 순서](phase-03-research/README.md) ·
[개념 설명](phase-03-research/DETAIL.md) · [변경 사항](rag/RAG_REDESIGN_CHANGELOG.md).
최신 문서/질문 분기와 재귀 청크: [2026-10-15 적용 보고](rag/RAG_RECURSIVE_CHUNKING.md).

## 개발 순서

```text
00-start-here
  ↓
phase-00-foundation → phase-01-chat → phase-02-memory → phase-03-research
  ↓
phase-04-tools → phase-05-agent → phase-06-security
  ↓
phase-07-voice → phase-08-resident-ui → operations
                                      → post-v1 (v1 안정화 후)
```

| 폴더 | 목적 | 릴리스 경계 |
|------|------|-------------|
| [00-start-here](00-start-here/README.md) | 미결정 사항·환경·착수 순서 확정 | 착수 준비 |
| [phase-00-foundation](phase-00-foundation/README.md) | 프로젝트 골격·설정·로그·저장 기반 | — |
| [phase-01-chat](phase-01-chat/README.md) | LLM 대화와 raw 저장 | — |
| [phase-02-memory](phase-02-memory/README.md) | 장기 기억과 세션 요약 | — |
| [phase-03-research](phase-03-research/README.md) | 웹/문서 RAG와 근거 응답 | MVP |
| [phase-04-tools](phase-04-tools/README.md) | 승인 기반 PC 도구 | — |
| [phase-05-agent](phase-05-agent/README.md) | 멀티스텝 에이전트와 재개 | — |
| [phase-06-security](phase-06-security/README.md) | 보안·백업·감사 릴리스 게이트 | v0.5 |
| [phase-07-voice](phase-07-voice/README.md) | PTT, STT, TTS | — |
| [phase-08-resident-ui](phase-08-resident-ui/README.md) | 트레이·단축키·패키징 | v1 후보 |
| [operations](operations/README.md) | 운영·복원·장애 대응·안정화 | v1 |
| [post-v1](post-v1/README.md) | 선택 기능 제안과 현재 구현의 운영 문서 | 문서별 상태 확인 |
| [reference](reference/README.md) | 추적표·문서 규칙·용어와 기준 링크 | 전 Phase |

## 세부 개발문서

각 폴더에는 같은 위치의 `README.md`를 배경·이유·주의점까지 풀어 쓴 `DETAIL.md`가 있다. 설명은
게임 개발 용어에 빗대어 쓴다. 전체 지도는 [docs/DETAIL.md](DETAIL.md)다.

세부 개발문서는 설명 전용이며 기준이 아니다. 인터페이스·설정 키·완료 기준은 항상 `README.md`와
기준 문서를 따른다. 원문이 바뀌면 같은 변경에서 세부 개발문서도 함께 수정한다.

| 문서 | 답하는 질문 |
|------|-------------|
| [DEVELOPMENT_FLOW.md](DEVELOPMENT_FLOW.md) | 단계가 어떤 순서로 이어지고 무엇이 무엇을 여는가 |
| `docs/*/README.md` | 지금 어떤 파일을 어떤 순서로 구현하는가 |
| `docs/*/DETAIL.md` | 그 규칙이 왜 필요한가 |

## 기준 문서 바로가기

- [제품 계획](PLAN.md)
- [아키텍처와 인터페이스](DESIGN.md)
- [데이터 스키마](SCHEMAS.md)
- [테스트 규약](TESTING.md)
- [설정 템플릿](../config)

Phase 문서는 기준 문서 내용을 복제하지 않고, 해당 작업에 필요한 절과 파일을 연결한다. 인터페이스나 데이터 구조가 바뀌면 먼저 기준 문서를 변경한다.

2026-10-15 RAG 후속 변경: [인용·조항/페이지·복합 질문 개발 문서](rag/RAG_CITATION_FIXES.md).
