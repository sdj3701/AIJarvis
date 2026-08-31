# Phase 2 — 장기 기억과 세션 복구

## 1. 목표

명시적 기억과 교정, 세션 요약 후보를 SQLite에 저장하고 다음 세션에서 관련 기억을 검색한다. 사용자가 나눈 질의응답 및 정리된 지식을 보관하여 Phase 3의 RAG 선조회 캐시와 연동한다. 사용자가 기억의 생성 이유를 확인하고 수정·삭제·내보낼 수 있어야 한다.

이전: [Phase 1](../phase-01-chat/README.md) · 다음: [Phase 3](../phase-03-research/README.md)

## 2. 진입 조건

- Phase 1 게이트 종료 코드 0
- raw 로그에서 세션을 재구성할 수 있음
- SQLite `integrity_check`가 통과함
- `FakeLLMClient`로 요약 응답을 스크립트할 수 있음

## 3. 만들 파일

```text
app/memory/{models.py,store.py,retrieval.py,summarizer.py,commands.py,migrations.py}
app/orchestrator/recovery.py
tests/unit/test_{memory_store,retrieval_ranking}.py
tests/integration/test_{session_summary,memory_across_sessions,recovery}.py
tests/data/memory_eval.jsonl
```

## 4. 기억 lifecycle

```text
Summarizer → candidate → 사용자 confirm → confirmed
candidate → reject → deleted
confirmed → correction → superseded + 새 confirmed correction
confirmed/candidate → /forget → deleted
```

자동 confidence는 정렬·표시용이며 절대로 확정 조건으로 사용하지 않는다.

## 5. 구현 순서

### P2-01 모델과 DB 저장소

1. [DESIGN 5.2](../../DESIGN.md)의 모델과 `MemoryStore` 계약을 구현한다.
2. [SCHEMAS 5장](../../SCHEMAS.md)의 DDL과 실제 `schema.sql`을 동일하게 유지한다.
3. SQLite에 WAL, synchronous FULL, foreign keys, busy timeout을 설정한다.
4. `put_record`를 ID 기준 멱등으로 만든다.
5. 상태 전이는 [SCHEMAS 6.2](../../SCHEMAS.md)에 허용된 경우만 수행한다.
6. 같은 key의 confirmed 레코드 하나 제약을 트랜잭션과 DB 인덱스로 함께 보장한다.

### P2-02 FTS와 검색 랭킹

1. 앱 시작 시 SQLite 버전과 FTS5 trigram 지원을 검사한다.
2. key exact, FTS 후보를 수집한다. 임베딩은 아직 비활성이다.
3. [DESIGN 8장](../../DESIGN.md)의 가중치·반감기·tie-break를 순수 함수로 구현한다.
4. 같은 key 안에서 최신 confirmed correction/fact 하나만 남긴다.
5. deleted·superseded 레코드는 검색에서 제외한다.
6. candidate는 별도 리스트로 최대 설정 개수만 반환한다.

### P2-03 명시적 기억과 교정

명령 처리:

| 명령 | 결과 |
|------|------|
| `기억해: ...` | key 추출/확인 후 `user_explicit`, `confirmed` 생성 |
| `틀림: A → B` | 대상 key 확인, 이전 confirmed를 superseded, correction confirmed 생성 |
| `/memory list` | 상태·kind 필터와 페이지 조회 |
| `/memory confirm <id>` | candidate를 confirmed로 전이 |
| `/memory edit <id>` | 기존 것을 superseded하고 새 레코드 생성 |
| `/forget <id>` | soft delete + FTS/embedding 제거 |
| `/memory export` | [SCHEMAS 6장](../../SCHEMAS.md) JSON으로 원자적 내보내기 |

key를 확실히 찾을 수 없으면 저장하지 말고 사용자에게 되묻는다.

### P2-04 세션 요약

1. `/bye`에서 raw 유효 줄을 읽는다.
2. Privacy Gate를 거친 내용만 Summarizer에 보낸다.
3. [SCHEMAS 7장](../../SCHEMAS.md)의 구조화 응답을 검증한다.
4. summary는 레코드로 저장하고 fact는 모두 candidate로 저장한다.
5. 각 candidate에 `evidence_turn_ids`를 요구한다.
6. 구조 위반 시 세션 종료 자체를 실패시키지 말고 `session.summary_failed` 이벤트를 남긴다.

### P2-05 프롬프트 기억 주입

1. 현재 질문으로 confirmed 기억을 검색한다.
2. candidate는 별도 블록에 넣고 미확정임을 시스템 지시로 명시한다.
3. 기억 블록이 예산을 넘으면 점수가 낮은 항목부터 제외한다.
4. 주입한 record ID를 `llm.request.memory_record_ids`에 기록한다.
5. secret/sensitive 레코드는 privacy 정책상 허용될 때만 API로 보낸다.

### P2-06 체크포인트와 시작 복구

1. 설정된 N턴마다 `session_checkpoints`를 커밋한다.
2. 시작 시 tmp/quarantine → DB integrity → 미완료 세션 → running task 순으로 검사한다.
3. `prompt`, `auto`, `discard` 정책을 구현한다.
4. 비정상 종료 세션을 요약할 때도 candidate 규칙을 유지한다.
5. 복구한 턴 수와 선택한 행동을 `recovery.result`에 기록한다.

### P2-07 삭제·인덱스 일관성

`/forget`은 하나의 트랜잭션에서 다음을 수행한다.

1. 상태를 `deleted`로 변경하고 tombstone 기록
2. FTS에서 제거
3. 존재하면 임베딩 제거
4. `memory.delete` 이벤트 기록

실패하면 전체 rollback한다. deleted 본문은 일반 조회·검색·API 전송에서 보이지 않아야 한다.

## 6. 필수 테스트

- 같은 key confirmed 두 개 생성 거부
- correction이 다른 key 순위에 영향 없음
- candidate를 사실로 단정하지 않음
- `/forget` 후 본문·FTS·embedding 검색 제외
- 세션 재시작 후 선호 반영
- evidence turn 없는 candidate 거부
- 같은 ID `put_record` 두 번 호출 시 중복 없음
- 미완료 세션 복구 이벤트 확인
- `memory_eval.jsonl` 정확도 MVP 90% 이상

## 7. 완료 게이트

```powershell
python scripts\gate.py --phase 2
python scripts\gate.py --report
```

- [x] Phase 2 게이트 종료 코드 0
- [x] 기억 질의 정확도 90% 이상 (`memory_eval.jsonl`)
- [x] candidate/confirmed/superseded/deleted 전이 테스트 통과
- [x] correction 동일 key 제한 통과
- [x] `/forget` 인덱스 일관성 통과
- [x] 크래시 세션 복구 후 candidate 생성 가능

증거: [phase2-20260811.json](../../artifacts/gates/phase2-20260811.json)

## 8. 이 Phase에서 하지 않는 것

- 웹·문서 RAG
- 임베딩 검색 활성화
- 자동 fact 확정
- 여러 사용자 프로필

