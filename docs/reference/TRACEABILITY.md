# 요구사항 추적표

제품 요구가 설계·데이터·구현 Phase·테스트로 이어지는지 확인하는 표다. 링크 대상이 바뀌면 이 표도 같은 변경에서 수정한다.

## 핵심 요구사항

| ID | 요구 | 기준 설계/스키마 | 구현 문서 | 검증 |
|----|------|------------------|-----------|------|
| R01 | API 멀티턴 대화 | DESIGN 5.1·7장 | [Phase 1](../phase-01-chat/README.md) | `test_chat_turn` |
| R02 | API 전 사용자 입력 저장 | SCHEMAS 2·4장 | [Phase 1](../phase-01-chat/README.md) | crash loop 20회 |
| R03 | timeout/rate limit 제한 | DESIGN 5.1 | [Phase 1](../phase-01-chat/README.md) | `test_retry_gives_up_after_max` |
| R04 | 일/월 비용 한도 | DESIGN 12장, settings budget | [Phase 1](../phase-01-chat/README.md) | `test_budget_guard` |
| R05 | candidate 기억 | DESIGN 5.2·8.4, SCHEMAS 6.2 | [Phase 2](../phase-02-memory/README.md) | `test_candidate_not_asserted_as_fact` |
| R06 | correction 동일 key 우선 | DESIGN 8.3, SCHEMAS records | [Phase 2](../phase-02-memory/README.md) | `test_correction_supersedes_same_key_only` |
| R07 | 기억 삭제·인덱스 제거 | SCHEMAS 5.1·6.2 | [Phase 2](../phase-02-memory/README.md) | `test_forget_removes_from_fts_and_embeddings` |
| R08 | 세션 체크포인트·복구 | DESIGN 13장 | [Phase 2](../phase-02-memory/README.md) | `test_recovery` |
| R09 | 웹 요약과 URL·날짜 | PLAN 10장, SCHEMAS 9장 | [Phase 3](../phase-03-research/README.md) | `test_search_answer_format` |
| R10 | 로컬 문서 RAG | SCHEMAS documents/doc_chunks | [Phase 3](../phase-03-research/README.md) | `test_local_doc_answer_cites_filename` |
| R11 | local_only 외부 전송 차단 | DESIGN 5.3, privacy config | [Phase 3](../phase-03-research/README.md) | `test_local_only_doc_not_sent_to_api` |
| R12 | prompt injection 격리 | DESIGN 7.3, SCHEMAS 9장 | [Phase 3](../phase-03-research/README.md) | injection corpus |
| R13 | 화이트리스트 PC 도구 | DESIGN 5.5·5.6, tools config | [Phase 4](../phase-04-tools/README.md) | `test_tool_execution` |
| R14 | sandbox 경로 우회 차단 | DESIGN 11.4 | [Phase 4](../phase-04-tools/README.md) | traversal/reparse corpus |
| R15 | 승인과 정확한 인자 결합 | DESIGN 10장 | [Phase 4](../phase-04-tools/README.md) | `test_args_change_invalidates_ticket` |
| R16 | 금지 작업 0건 | PLAN 11.3, tools forbidden | [Phase 4](../phase-04-tools/README.md) | `test_forbidden_actions` |
| R17 | 멀티스텝과 max_steps | DESIGN 5.7·13장 | [Phase 5](../phase-05-agent/README.md) | `test_agent_multistep` |
| R18 | 재시작 후 중복 부작용 0건 | SCHEMAS task_steps | [Phase 5](../phase-05-agent/README.md) | `test_no_duplicate_write_on_resume` |
| R19 | 암호화 백업·복원 | privacy backup config | [Phase 6](../phase-06-security/README.md) | `test_backup_restore` |
| R20 | 감사 로그 무결성 | SCHEMAS 3.2 | [Phase 6](../phase-06-security/README.md) | `test_audit_chain` |
| R20b | 거부된 도구 요청도 감사 기록 | DESIGN 5.6, SCHEMAS 3.1 `denied` | [Phase 4](../phase-04-tools/README.md) | `test_denied_call_is_audited` |
| R21 | 음성 text parity | DESIGN 음성 계약 | [Phase 7](../phase-07-voice/README.md) | `test_voice_matches_text_result` |
| R22 | 음성 High 승인 금지 | RequestContext channel, tools config | [Phase 7](../phase-07-voice/README.md) | `test_voice_cannot_approve_high_risk` |
| R23 | 마이크 상태 표시 | DESIGN UI 상태 | [Phase 7](../phase-07-voice/README.md) | 수동+UI state 테스트 |
| R24 | 트레이·단축키·단일 인스턴스 | DESIGN UI 계약 | [Phase 8](../phase-08-resident-ui/README.md) | `test_ui_state`, `test_single_instance` |
| R25 | 패키징·migration | DESIGN 9.3·Phase 8 | [Phase 8](../phase-08-resident-ui/README.md) | packaged bootstrap 테스트 |
| R26 | 7일 데이터 손상 0건 | TESTING 11.5 | [운영](../operations/README.md) | 매일 `--integrity` 기록 |

## 추적 규칙

- 요구가 추가되면 최소 한 개 설계/스키마 항목, 한 Phase, 한 테스트를 연결한다.
- 테스트가 아직 없으면 검증 열에 `MISSING`을 적고 해당 Phase 게이트를 통과시키지 않는다.

### 영구 명령 기억

사용자 명령 학습 요청 → D022 → docs/post-v1/COMMAND_MEMORY.md →
command_memory.py 및 loop.py → scripts/tests/integration/test_command_memory.py.
실환경 벡터 영구 저장·유사 검색은 확인했고 실제 앱 실행과 전체 자연어 평가셋은 별도 검증한다.

### 영구 응답 룰북

요구: PROPOSAL_PERSISTENT_RESPONSE_RULEBOOK. 결정: D021. 구현: rulebook.py,
prompt.py, response_presenter.py, loop.py, voice/controller.py 및 GUI/CLI.
검증: test_rulebook, test_response_presenter, test_rulebook_parity 및 기존 승인/음성 회귀.
실장치 낭독 시간 비교는 MISSING이며 운영 성능 게이트를 통과한 것으로 표시하지 않는다.

### 앱 탐색·최초 승인 저장

요구사항은 `PROPOSAL_APP_DISCOVERY_AND_SAVED_APPROVAL.md`, 설계는 DESIGN 11.6,
저장 계약은 SCHEMAS 8.1, 자동 검증은 `scripts/tests/integration/test_app_saved_approval.py`에 연결한다.
GUI/CLI/음성 공통 실행은 SafetyGate → 승인 티켓 → OpenAppTool 경로를 사용한다.
실환경 재부팅·GUI 시각·실제 음성 승인 검증 증거는 아직 없으며 TESTING의 수동 항목이다.
- 수동 검증만 있는 항목은 자동화할 수 없는 이유와 증거 저장 위치를 운영 문서에 기록한다.



## RAG 재설계 추적 (2026-10-14)

| 작업 | 설계/계약 | 구현 | 검증 연결 | 상태 |
|---|---|---|---|---|
| R3-01 | DESIGN 16.4, SCHEMAS 13.1 | query_plan.py | RG-01; test_query_plan, test_grounded_research, test_agent_multistep | 자동·실제 평가 확인 |
| R3-02 | DESIGN 16.5, SCHEMAS 13.2 | local_embedder.py, semantic.py | RG-02; test_local_embedder, test_semantic_memory, redesign | 자동·실제 비교 확인 |
| R3-03 | DESIGN 16.6, SCHEMAS 13.1 | chunker.py, generations.py | RG-03; test_contextual_chunks, test_index_generations, test_local_embedder | 재귀 청크/질문 경로 검증은 2026-10-15 적용 보고 |
| R3-04 | DESIGN 16.6, SCHEMAS 13.2~3 | generations.py, indexer.py | RG-04; test_index_generations, test_rag_answer_modes | 합성 DB 전환/복구 확인 |
| R3-05 | DESIGN 16.7, SCHEMAS 13.4 | reranker.py, research.py, loop.py | RG-05; test_rag_context, test_rag_answer_modes, test_prompt_budget | 자동·실제 평가 확인 |
| R3-06 | DESIGN 16.8, SCHEMAS 13.1 | loop.py, response_presenter.py | RG-06; test_rag_answer_modes, test_voice_parity, test_rulebook_parity | 코드 출력 계약 확인 |
| R3-07 | DESIGN 16.9, SCHEMAS 13.1 | grounding.py | RG-07; test_calculation_evidence, test_grounding, derived_leave_sum | 자동·실제 평가 확인 |
| R3-08 | TESTING 13, D024 | benchmark/answers.py, redesign.py | RG-08; 488 Phase 회귀, 17답변·11검색 질의 | 자동 평가·문서 완료; 실장치/릴리스 인수 남음 |

실행 결과·한계는 [구현 보고](../rag/RAG_R3_IMPLEMENTATION.md), 요구별 설명은 [Phase 3](../phase-03-research/README.md)를 따른다.
2026-10-15의 문서/질문 경로·재귀 청크 변경은 [새 적용 보고](../rag/RAG_RECURSIVE_CHUNKING.md)에 별도로 기록한다.


### PDF 후속 구현 (2026-10-15)

| 요구 | 계약 | 구현 | 검증 |
|---|---|---|---|
| 직접 PDF 추출·여백 제거·장/조/항/호·페이지 | DESIGN 16.6, D012 | document_parser.py | test_document_parser; 실제 PDF 6쪽 |
| 제목만 있는 청크 제거·토큰 상한 | DESIGN 16.6 | chunker.py | test_contextual_chunks; 실제 PDF 34청크 |
| Markdown/출처 저장·캐시·실패/삭제 | SCHEMAS 13.2~4 | generations.py, indexer.py | test_index_generations |
| 검색/생성으로 위치 정보 전달·인용 본문 분리 | DESIGN 16.7 | models.py, web_search.py, research.py, grounding.py | test_index_generations, test_rag_context; 실제 답변 17개 |

[전체 결과·재현](../rag/RAG_PDF_INGESTION.md). 스캔 OCR·실장치 인수는 이번 완료 범위에 포함하지 않는다.

RG-CITE: DESIGN 16.7·SCHEMAS 13.5 → passages/grounding/research/loop → test_citation_passages, test_legal_chunk_context, test_grounded_research 및 실제 PDF/TC 1·2. [증거](../rag/RAG_CITATION_FIXES.md).

RG-PDF-MD: DESIGN 16.6·SCHEMAS 13.2~4 → markdown_exports/generations/indexer →
test_markdown_exports(동일성·복원·충돌·원자 교체·삭제 재시도·중복 색인), 실제 PDF/개발 DB 파일 생성.
[검증 증거](../rag/RAG_PDF_INGESTION.md).

RG-ANSWER-QUALITY: DESIGN 답변 품질 후속 설계·SCHEMAS 13.5~6 → document_context/
structured_answers/grounding/passages/research/loop/query_plan/web_search →
test_answer_quality(참조 번호·의무 주체·목록/구조 계수·주기/여백 추출·문서 전용 경로),
test_grounded_research(인용 검증·보류·재시도), 기존 Phase 회귀 및 동일 PDF 100문항 수동 대조.
[검증 증거](../rag/RAG_ANSWER_QUALITY.md).
