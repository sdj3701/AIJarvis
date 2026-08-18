# Jarvis 개발 문서 지도

이 디렉터리는 실제 구현 순서대로 정렬된 실행 문서다. 루트의 [README.md](../README.md)가 전체 진입점이고, 이 파일은 세부 탐색용 색인이다.

현재 상태와 다음 작업은 [PROGRESS.md](./PROGRESS.md)에서 관리한다. `rebuild/v2`의 다음 작업은 [Phase 0](./phase-00-foundation/README.md)이다.

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
| [00-start-here](./00-start-here/README.md) | 미결정 사항·환경·착수 순서 확정 | 착수 준비 |
| [phase-00-foundation](./phase-00-foundation/README.md) | 프로젝트 골격·설정·로그·저장 기반 | — |
| [phase-01-chat](./phase-01-chat/README.md) | LLM 대화와 raw 저장 | — |
| [phase-02-memory](./phase-02-memory/README.md) | 장기 기억과 세션 요약 | — |
| [phase-03-research](./phase-03-research/README.md) | 웹/문서 RAG와 근거 응답 | MVP |
| [phase-04-tools](./phase-04-tools/README.md) | 승인 기반 PC 도구 | — |
| [phase-05-agent](./phase-05-agent/README.md) | 멀티스텝 에이전트와 재개 | — |
| [phase-06-security](./phase-06-security/README.md) | 보안·백업·감사 릴리스 게이트 | v0.5 |
| [phase-07-voice](./phase-07-voice/README.md) | PTT, STT, TTS | — |
| [phase-08-resident-ui](./phase-08-resident-ui/README.md) | 트레이·단축키·패키징 | v1 후보 |
| [operations](./operations/README.md) | 운영·복원·장애 대응·안정화 | v1 |
| [post-v1](./post-v1/README.md) | Phase 9 선택 기능을 개별 제안으로 분리 | v1 이후 |
| [reference](./reference/README.md) | 추적표·문서 규칙·용어와 기준 링크 | 전 Phase |

## 기준 문서 바로가기

- [제품 계획](../PLAN.md)
- [아키텍처와 인터페이스](../DESIGN.md)
- [데이터 스키마](../SCHEMAS.md)
- [테스트 규약](../TESTING.md)
- [설정 템플릿](../config)

Phase 문서는 기준 문서 내용을 복제하지 않고, 해당 작업에 필요한 절과 파일을 연결한다. 인터페이스나 데이터 구조가 바뀌면 먼저 기준 문서를 변경한다.
