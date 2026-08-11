# Phase 3 — 웹 검색과 로컬 문서 RAG

## 1. 목표

모델의 기억만으로 답하지 않고 웹·로컬 문서에서 근거를 찾는다. 외부 텍스트는 항상 신뢰할 수 없는 데이터로 취급하고, 핵심 주장에 출처와 확인 날짜를 연결한다. 이 Phase 완료가 MVP 경계다.

이전: [Phase 2](../phase-02-memory/README.md) · 다음: [Phase 4](../phase-04-tools/README.md)

## 2. 진입 조건

- Phase 2 게이트 종료 코드 0, 기억 정확도 90% 이상
- [D006 검색 제공자](../00-start-here/DECISIONS.md)가 웹 검색 구현 전에 `decided`
- `privacy.yaml`의 문서 전송 등급을 검토함
- PDF를 활성화하려면 D012가 `decided`; 미결정이면 `.md`, `.txt`만 지원

## 3. 만들 파일

```text
app/privacy/{detectors.py,gate.py}
app/rag/{fetcher.py,chunker.py,indexer.py}
app/tools/{base.py,registry.py}
app/tools/impl/{web_search.py,doc_search.py}
app/orchestrator/prompts/system_tools.md
tests/fakes/search.py
tests/unit/test_{envelope,tool_schema_validation}.py
tests/integration/test_search_answer_format.py
tests/security/test_{prompt_injection,secret_leakage,url_schemes}.py
tests/data/{docs,web,malicious/injection.jsonl}
```

## 4. 구현 순서

### P3-01 Privacy Gate 완성

1. `privacy.example.yaml` 탐지기를 컴파일하고 시작 시 잘못된 정규식을 거부한다.
2. `for_api`, `for_log`, `for_tts`, `for_memory_write`를 독립 경로로 구현한다.
3. Finding에는 원문을 저장하지 않는다.
4. API 전송 차단 시 `ask_user`, `deny`, `local_only` 중 정책대로 처리한다.
5. `secret`은 사용자가 승인해도 외부 전송하지 않는다.

계약: [DESIGN 5.3](../../DESIGN.md), [privacy.example.yaml](../../config/privacy.example.yaml)

### P3-02 도구 공통 계약과 레지스트리

1. `ToolSpec`, `ToolResult`, `Tool`을 구현한다.
2. `tools.yaml`에서 현재 Phase 이하이면서 enabled인 도구만 등록한다.
3. JSON Schema의 `additionalProperties=false`, required, 길이 제한을 검사한다.
4. LLM에는 이름·설명·인자 스키마만 노출한다. risk·capability·실제 경로는 숨긴다.
5. 검색 도구 결과는 항상 `untrusted=true`다.

이 Phase에서는 Secure Tool Runner를 만들지 않는다. 검색 도구는 부작용 없는 전용 실행 경로로만 호출한다.

### P3-03 로컬 문서 인덱싱

1. `docs_dir`를 순회하되 허용 확장자와 최대 파일 크기를 적용한다.
2. 파일의 canonical path가 docs root 아래인지 확인한다.
3. `content_hash`가 바뀐 문서만 다시 인덱싱한다.
4. 문자를 기준으로 chunk와 overlap을 만들고 `start_char`, `end_char`, ordinal을 기록한다.
5. documents/doc_chunks와 FTS를 하나의 트랜잭션으로 갱신한다.
6. 삭제된 원본의 문서·chunk·FTS·embedding을 함께 제거한다.
7. 문서 경로 규칙으로 `local_only`/`api_allowed`를 결정한다.
8. `IndexReport` 결과를 `rag.index` 이벤트로 남긴다.

PDF parser가 정해지기 전에는 설정의 `.pdf`를 제거하고 명확한 “지원하지 않는 형식” 메시지를 낸다. 조용히 빈 문서로 인덱싱하지 않는다.

### P3-04 문서 검색

1. 질의로 FTS 상위 후보를 가져온다.
2. 같은 문서에서 지나치게 겹치는 chunk를 합친다.
3. 최대 chunk 수와 토큰 예산을 적용한다.
4. 각 결과에 파일명, 상대 경로, chunk ID, 문자 범위, transfer class를 포함한다.
5. `local_only` 본문은 외부 LLM 프롬프트에 넣지 않는다. 이 경우 로컬 검색 결과의 존재만 알리고 정책에 따라 사용자에게 선택지를 준다.

### P3-05 웹 검색 제공자

1. query를 `PrivacyGate.for_external_text(..., purpose="search_query")`에 통과시킨 뒤 제공자에 전송한다.
2. 제공자 응답을 내부 `SearchHit` 목록으로 변환한다.
3. 각 hit는 title, URL, snippet, published_at, fetched_at을 갖는다.
4. 최대 결과 수와 timeout을 적용한다.
5. 요청 전 `BudgetGuard.check(service="search")`, 성공 후 설정 단가로 `record_charge`를 호출한다.
6. 검색 API 오류 시 빈 성공 결과로 위장하지 않고 검색 실패로 보고한다.
7. 자동 테스트는 `FakeSearchProvider`만 사용한다.

### P3-06 안전한 fetcher

요청마다 아래 순서를 지킨다.

1. URL 파싱과 http/https 스킴 확인
2. 자격증명 포함 URL, loopback, 사설·link-local IP, `.local`, 장치/파일 스킴 차단
3. DNS 해석 전·후 IP를 모두 검사해 DNS rebinding 완화
4. redirect마다 같은 검증 반복, 최대 3회
5. 응답 헤더와 스트리밍 누적 크기 모두 2MB 제한
6. 허용 Content-Type 확인
7. HTML에서 script/style/form 등 비본문 제거
8. 결과를 `untrusted_content` 봉투에 넣음

### P3-07 신뢰 경계와 프롬프트

1. 본문 안의 봉투 종료 태그를 이스케이프한다.
2. [SCHEMAS 9장](../../SCHEMAS.md)의 속성을 모두 채운다.
3. 외부 본문에서 나온 URL·경로·명령을 도구 인자로 자동 승격하지 않는다.
4. 현재 사용자 요청과 별개인 부작용 도구 call은 거부한다.
5. LLM이 악성 tool call을 반환하는 경우까지 정책 테스트한다.

### P3-08 근거 응답 조립

응답 최소 형식:

```text
핵심 요약
- 주장 A [1]
- 주장 B [2]

근거
[1] 제목 — URL 또는 파일명 (YYYY-MM-DD 확인)
[2] 제목 — URL 또는 파일명 (YYYY-MM-DD 확인)

상태: 확실 | 상충 | 근거 부족
```

- 핵심 주장마다 실제로 뒷받침하는 근거 ID가 있어야 한다.
- 독립 출처 2개 미만이면 설정에 따라 `근거 부족`으로 표시한다.
- 서로 다른 출처가 충돌하면 양쪽을 보이고 `상충`으로 표시한다.
- 검색 실패와 “결과 0건”을 구분한다.

## 5. 필수 테스트

- 악성 문서 코퍼스가 부작용 도구를 실행하지 않음
- 봉투 종료 태그 탈출 방지
- local_only 원문이 `llm.calls`에 없음
- 문서 삭제 후 FTS 결과에서 사라짐
- 같은 문서 재인덱싱 시 chunk 중복 없음
- redirect마다 SSRF 재검사
- 응답 크기·Content-Type 제한
- 검색 실패 시 솔직한 실패 응답
- 모든 검색형 핵심 주장에 출처와 확인 날짜 존재

## 6. 수동 스모크 테스트

실제 네트워크 테스트는 별도 마커와 명시적 비용 동의로 실행한다.

```powershell
pytest -m allow_network tests\smoke\test_live_search.py
```

확인 항목: 제공자 인증, 응답 매핑, 최신성 날짜, 비용, timeout. 실제 웹 본문을 테스트 스냅샷으로 무단 저장하지 않는다.

## 7. 완료 게이트

### 2026-08-11 보안 검토 반영

- HTTP 리다이렉트는 자동 추적하지 않고 매 단계의 스킴·DNS·IP를 다시 검사한다.
- DNS 검사에서 허용한 IP를 실제 소켓 연결에 고정해 DNS rebinding을 차단한다.
- 검색 신뢰도는 결과 청크 수가 아니라 정규화한 URL과 `doc_id`의 독립 개수로 계산한다.
- 독립 출처가 2개 미만이면 모델 응답의 `확실` 표기를 `근거 부족`으로 낮춘다.

```powershell
python scripts\gate.py --phase 3
```

- [x] Phase 3·security 테스트 통과
- [x] prompt injection 코퍼스 전부 차단
- [x] local_only 외부 전송 0건
- [x] 검색형 핵심 주장 근거 표기 (FakeLLM 포맷 검증)
- [x] 웹·문서 검색 실패 처리 구분
- [ ] MVP 데모 20회 연속 성공 (수동)

## 8. 이 Phase에서 하지 않는 것

- 앱·폴더·파일 쓰기 도구
- 검색 결과가 지시한 행동 자동 실행
- 임베딩을 필수 기능으로 만들기
- 미지원 파일 형식을 조용히 무시하기
