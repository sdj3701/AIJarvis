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
- 수동 검증만 있는 항목은 자동화할 수 없는 이유와 증거 저장 위치를 운영 문서에 기록한다.

