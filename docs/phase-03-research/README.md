# Phase 3 — 문서 준비·검색·근거 기반 답변

2026-10-14: R3-01~07 구현 및 R3-08 자동 평가·운영 문서 적용. 실장치 인수와 정식 릴리스는 별도다.
2026-10-15: 문서/질문 경로 계약을 명시하고 문서 분할을 `recursive-context-v4`로 교체했다.
텍스트 PDF 직접 추출·여백 제거·법령 구조 보존도 적용했다. [PDF 적용 보고](../rag/RAG_PDF_INGESTION.md).
변경 이유와 앞선 검증은 [재귀 청크 적용 보고](../rag/RAG_RECURSIVE_CHUNKING.md)를 따른다.
기준: [PLAN](../PLAN.md) · [DESIGN 16장](../DESIGN.md#16-rag검색-계약) ·
[SCHEMAS 13장](../SCHEMAS.md) · [TESTING 13장](../TESTING.md)
설명: [DETAIL](DETAIL.md) · [변경 이유·결과](../rag/RAG_R3_IMPLEMENTATION.md) · [진행 현황](../PROGRESS.md)
이전: [Phase 2](../phase-02-memory/README.md) · 다음: [Phase 4](../phase-04-tools/README.md)

## 1. 네 단계

1. 문서 준비: PDF 텍스트 추출·여백 제거·구조화(또는 md/txt 읽기) → 절 구분 → 토큰 제한을 지키는 재귀적 청크 → 문서 임베딩 → 새 색인 세대 게시.
2. 질문 준비: 검색 경로·사용자 발화 문맥으로 QueryPlan → 질문 전체 임베딩(문서 청크 호출 없음).
3. 문서 탐색: FTS5 + 벡터 거리 → RRF → 재정렬 → 이웃 원문 선택·예산 검사.
4. 답변: 원문으로 Qwen 생성 → 인용·계산·주장 검사 → 근거/일반/보류 표시.

토큰화는 ID 변환이고 위치 정보·어텐션·feed-forward는 모델 내부다. 문서 DB 검색과는 책임이 다르다.
Ollama는 임베딩과 생성 모델을 실행한다. RAG가 추가하는 것은 모델 사이의 자료 처리·검색·검증 연결이다.

## 2. 범위와 파일

개발 소스 `D:\Ai\Jarvis`, 개발 설정 `D:\Ai\Jarvis\data\config`를 사용한다.
UTF-8 md/txt와 텍스트 PDF를 지원한다. Office/OCR, 복잡한 PDF 레이아웃, ANN, 모델 학습은 별도다.
질문: query_plan.py / loop.py / research.py. 색인: document_parser.py / chunker.py / generations.py / indexer.py.
모델: local_embedder.py / reranker.py. 검사: grounding.py. 화면·음성: response_presenter.py.
평가: benchmark/answers.py / redesign.py. 정확한 계약·기본값은 DESIGN·SCHEMAS를 따른다.

## 3. 기존 기반 P3-01~P3-08

| ID | 유지하는 책임 |
|---|---|
| P3-01 | Privacy Gate, 목적별 마스킹·전송 정책 |
| P3-02 | 허용 도구 레지스트리·인자 검사 |
| P3-03 | 루트 경계·확장자·크기·문서 인덱싱 |
| P3-04 | FTS5·벡터 거리·RRF 검색 |
| P3-05 | Privacy Gate 뒤 웹 검색; title/snippet 근거 |
| P3-06 | 안전한 fetcher; 답변 본문 fetch 확대는 별도 |
| P3-07 | 신뢰하지 않는 자료 봉투와 명령 분리 |
| P3-08 | 생성·근거 검사·대화 verified=false |

## 4. R3 구현 순서와 결과

| ID | 바꾼 부분 | 바꾼 이유 | 검증 |
|---|---|---|---|
| R3-01 | QueryPlan·사용자 발화 문맥 연결·모호하면 확인 | 표현 차이와 후속 질문 때문에 검색이 빠지는 문제 | test_query_plan, test_grounded_research |
| R3-02 | query/document 접두사·모델 identity 분리 | 질문과 문서의 역할을 검색 모델에 명확히 전달 | test_local_embedder, test_semantic_memory, 실제 raw/role 비교 |
| R3-03 | 절/문단 보존·재귀적 분할·실제 임베딩 토큰 상한 | 들어가는 다음 문단을 앞 청크의 빈자리에 맞춰 쪼개지 않기 | test_contextual_chunks, 긴 문서 실제 평가 |
| R3-04 | fingerprint·prepared/active 세대·사본 복구 | 설정 변경 누락, 새 원문과 옛 벡터 혼합 방지 | test_index_generations, stale-source 통합 회귀 |
| R3-05 | 구간별 재정렬·인접 원문·중복 제거·예산 | 뒤쪽 정답과 여러 조항이 누락되는 문제 | test_rag_context, 입력 예산 통합 회귀 |
| R3-06 | grounded/general/abstained·출력/저장 모드 | 일반 지식 답변과 내부 사실 추측 구분 | test_rag_answer_modes, 화면/음성 presenter 회귀 |
| R3-07 | 인용된 피연산자·허용 계산 재검산 | 올바른 합계를 새 숫자라고 거부하던 문제 | test_calculation_evidence, 실제 합계 답변 |
| R3-08 | 합성 자료 확장·검색/답변 독립 보고·운영 기록 | 기능 구현과 품질/인수를 별도로 확인 | TESTING RG-08, artifacts/evaluations/rag-r3-20261014 |

수치는 D024의 개발 기본값이다. 작은 합성 평가에서 통과했다고 실무 최적값·정확도 보장을 선언하지 않는다.
정식 완료 상태와 남은 인수는 PROGRESS에서 관리한다.

## 5. 적용·확인

앱을 재시작하면 수정 소스를 읽는다. 기존 YAML에 새 키가 없으면 기본값을 사용한다.
최초 색인은 새 역할 입력/청크 정책으로 준비하므로 기존보다 시간이 들 수 있다.
`recursive-context-v4` 적용 후 첫 sync에서는 내용이 같은 파일도 재색인한다. 질문 자체는 색인하지 않는다.

```text
/index
/search 우리 회사 연차 신청은 며칠 전에 해야 하나요?
그럼 어디에서 신청해?
광합성의 원리를 설명해줘
```

파일 수정·삭제는 다음 검색의 주기 검사 또는 `/index`로 반영된다. 상시 파일 watcher는 없다.
설정 파일을 바꿨다면 재시작 후 `/index`한다. 설정만 바뀌어도 새 fingerprint로 재청킹한다.
실패한 새 세대는 게시하지 않으며 원문이 바뀐 상태에서 옛 색인을 현재 근거로 쓰지 않는다.
평가에는 임시 합성 DB를 사용한다. 2026-10-15 별도 적용 단계에서 개발 DB를 백업하고 기존 20문서를
새 청크 정책으로 재색인했다. 상세 결과와 백업 위치는 [적용 보고](../rag/RAG_RECURSIVE_CHUNKING.md)를 따른다.
백업/복구와 사본 marker는 [운영 설명](../post-v1/LOCAL_SEMANTIC_MEMORY.md)을 따른다.

## 6. 검증·인수

자동 회귀·실제 모델 명령은 [TESTING](../TESTING.md), 결과는 [구현 보고](../rag/RAG_R3_IMPLEMENTATION.md).
`python scripts/gate.py --phase 3`은 깨끗한 작업 트리를 요구한다. 현재 기존 미커밋 변경 때문에 실행을 거부한다.
동일 Phase marker 직접 실행 결과와 정식 게이트를 혼동하지 않는다.
물리 마이크·스피커, GUI 시각 인수, 깨끗한 설치 환경, 7일 안정화는 별도 확인 대상이다.


## 2026-10-15 인용·복합 질문 보완

짧은 조문은 같은 장 안에서 최대 4개 묶고, 긴 조문은 재귀로 나눈다. 뒤쪽 조각이 검색되면
같은 조문의 앞부분도 가져와 전제 조건을 확인한다. 모델이 선택한 원문 ID를 앱이 인용문과
조항·페이지로 바꾸므로 출처를 다시 쓰다가 생기던 오류를 줄인다. 여러 질문은 항목별 검색과
검증으로 나눠 한 질문의 숫자가 다른 질문으로 옮겨가는 것을 막는다.
세부 계약·테스트·비교 그래프는 [인용 개선 보고](../rag/RAG_CITATION_FIXES.md)를 따른다.

### RG-PDF-MD: 변환 Markdown 파일 저장

PDF 색인 게시 → DB Markdown에서 `.md` 사본 생성 → 반복 sync에서 갱신/누락 복구/삭제 정리.
전용 출력 폴더를 스캔에서 제외하고 DB/벡터/페이지 출처는 유지한다. 구현은 `markdown_exports.py`,
계약은 DESIGN 16.6·SCHEMAS 13.2~4, 검증은 TESTING RG-PDF-MD·`test_markdown_exports.py`.
저장 경로·변경 이유·제공 PDF 시험은 [PDF 적용 보고 7절](../rag/RAG_PDF_INGESTION.md)을 따른다.

### RG-ANSWER-QUALITY: 검색 이후 답변 품질 개선

재귀 청크·임베딩을 유지한다. 원문 선택/검증 오판 → 질문별 생성과 누락 검사 →
문서 구조 조회/계수 → 같은 조문·참조 문맥 보강 → 주체·의무 검증 → 동일 100문항 재평가 순서다.
구현은 document_context/structured_answers/grounding/passages/research/loop/query_plan/
web_search/models다. 검증은 test_answer_quality, test_grounded_research와 기존 Phase 회귀다.
기존 v4 색인의 재청킹을 요구하지 않으며 앱 재시작 후 적용된다.
[답변 품질 보고](../rag/RAG_ANSWER_QUALITY.md), [DESIGN](../DESIGN.md), [SCHEMAS](../SCHEMAS.md)를 따른다.
