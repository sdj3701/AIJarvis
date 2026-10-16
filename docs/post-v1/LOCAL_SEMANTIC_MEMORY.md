# 로컬 임베딩과 문서·대화 검색

## 구현

문서 검색은 FTS5/BM25 + Ollama `embeddinggemma` + RRF + 로컬 Cross-Encoder 재정렬이다.
특징 해싱은 실제 문서 검색과
벤치마크 경로에서 제거했다. 기존 `LocalEmbeddingEngine`은 과거 비교용 유틸리티와
단위 테스트에만 남아 있다. 모델 가중치를 학습하는 기능은 아니다.

임베딩은 `127.0.0.1:11434`의 로컬 모델만 사용한다. 환경 프록시·HTTP 리디렉션은
허용하지 않는다. 모델 digest와 검색 입력 버전(`search-v1`)을 저장해 서로 다른 모델의
벡터를 섞지 않는다. 설치된 embeddinggemma의 출력은 768차원이다.

문서의 활성 벡터는 주 `memory_db`의 generation 테이블에 저장한다. 대화·문서 사본은 옆의 `semantic.sqlite3`에 저장한다. sqlite-vec의
`vec_distance_cosine`으로 SQLite 내부에서 정확 코사인 검색을 수행한다.
ANN/HNSW가 아닌 전수 비교 방식이며 별도 서버는 필요 없다. 기존 문서·기억·세션
저장소는 유지하며 semantic DB에는 벡터와 검색용 텍스트·출처 메타데이터 사본을 함께 저장한다.
문서 검색의 commit 기준은 주 DB의 세대다. semantic DB의 사본은 generation marker로 복구한다.

## R3 적용과 남은 한계

문서/질문은 search-v1의 역할별 접두 형식으로 임베딩한다. 문맥/토큰 청크·이웃 문맥·일반 지식 분기를 적용했다.
설정 fingerprint가 달라져도 재청킹하며 시작·`/index`·검색 시 5초 간격 확인에서 갱신한다.
주 DB에 원문·FTS·세대 벡터를 원자 게시하고 semantic DB는 복구 가능한 문서 사본과 대화 기억을 보관한다.
실패 시 이전 완전한 세대를 유지하며 바뀐 파일의 옛 근거 답변은 보류한다.
일반 답변은 문서 출처를 만들지 않고 verified=false로 저장한다. 명령 기억의 별도 임베더는 유지한다.

규칙 기반 질문 계획, 문자/토큰 경계 parser의 한계, 벡터 전수 검색 비용은 남는다.
텍스트 PDF 직접 추출·구조/페이지 보존은 [PDF 적용 보고](../rag/RAG_PDF_INGESTION.md)를 따른다.
Office/OCR·복잡한 PDF 레이아웃·대규모 ANN·실장치 인수는 별도다. [R3 구현 보고](../rag/RAG_R3_IMPLEMENTATION.md)를 따른다.

## 설치와 사용

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,benchmark,rerank]"
ollama pull embeddinggemma
.\.venv\Scripts\python.exe scripts/setup_reranker.py --config-dir D:\Jarvis-v2-dev\config
.\.venv\Scripts\python.exe scripts/reindex_semantic.py --config-dir D:\Jarvis-v2-dev\config
```

기존 설정에 `rag.semantic`이 없으면 새 기본값을 사용한다. 기존 해싱 벡터를 새 모델의
벡터로 재해석하지 않고 문서 원문에서 다시 계산한다. 모델을 갱신했으면 Jarvis를
재시작하고 `/index`, `/recall reindex`를 실행한다.

Reranker 추가만으로 기존 벡터를 다시 만들 필요는 없다. 설정에 `rag.rerank`가
없으면 기본값을 사용하며, 실행 중인 Jarvis는 새 코드를 적용하기 위해 재시작한다.
소스 실행은 `.\.venv\Scripts\python.exe -m app`을 사용한다. 프로젝트 루트의
`Jarvis.exe`는 `.venv`의 Python으로 현재 소스를 실행하는 런처이므로 소스 변경 후
재시작하면 적용된다. 별도로 PyInstaller로 묶어 배포한 실행 파일은 재빌드가 필요하다.

## RRF 이후 재정렬

`FTS5 + embeddinggemma/sqlite-vec → RRF 후보 → Cross-Encoder → 최종 문서·대화`

사용 모델은 [mmarco-mMiniLMv2-L12-H384-v1](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1)의
공식 `onnx/model_quint8_avx2.onnx`다. 약 119MB의 INT8 ONNX와 약 17MB의 tokenizer를
`paths.models_dir/mmarco-minilm-reranker`에 저장한다. 설치 스크립트는 고정 revision
`1427fd652930e4ba29e8149678df786c240d8825`에서 내려받고 SHA-256을 검증한다.
추론도 최초 로딩 때 체크섬을 검증하며 모델 파일만 읽는다. 검색 시 자동 다운로드,
원격 추론, 원격 Python 코드 실행은 없다. ONNX Runtime CPU로 실행하므로 Ollama
답변 모델과 별개이고 GPU 메모리를 사용하지 않는다.

- 문서: RRF 상위 후보를 질문과 함께 평가하고 재정렬한 뒤 문서당 기본 6청크 제한과
  `max_chunks_per_answer`를 적용한다. 문서 경로·청크 ID·전송 등급은 유지한다.
- 대화: 질문/답변 검색 결과를 턴별로 중복 제거한 뒤 질문과 답변 발췌를 함께 평가한다.
  긴 답변은 검색에 걸린 답변 청크를 사용한다. 원본 질문·답변·출처는 수정하지 않는다.
  최종 결과 수는 `conversation_top_k`이며, 자동 프롬프트에도 해당 발췌를 전달한다.
- 기존 `score`는 RRF 점수다. 별도 `rerank_score`는 Cross-Encoder logit이며
  정답 확률이나 사실 검증 점수가 아니다. 동일 점수는 기존 RRF 순서를 유지한다.
  과거 답변의 `verified=false`와 신뢰하지 않는 입력 처리는 유지된다.
- 각 검색 경로는 기존 후보 수와 `candidate_count` 중 큰 수를 가져오고, 합친 RRF
  상위 `candidate_count`개만 재정렬한다. 그 밖의 후보는 뒤에 기존 순서로 남는다.
  후보에 들어오지 않은 자료는 reranker가 복원할 수 없다.
- 모델/패키지 누락, 체크섬 불일치, 추론 오류·시간 초과·유효하지 않은 점수는
  해당 후보의 RRF 순서 전체로 되돌린다. 30초 후 재시도하며 임베딩 상태와 분리된다.
  동시 호출 중이면 대기하지 않고 RRF로 반환한다.

`rag.rerank` 기본값은 `enabled=true`, `candidate_count=24`, `batch_size=4`,
`max_length=512`, `cpu_threads=2`, `timeout_s=10`이다. 토큰 길이는 질문·본문 합계이며
질문이 그중 1/4을 넘으면 RRF로 복귀한다. 긴 본문은 겹치는 구간으로 나눠 모두 평가한다.
후보당 32구간을 초과하면 RRF로 복귀하고 오류를 기록한다. 시간 제한은 모델 로딩 후
배치 전체 추론에 적용되고, 실행 중인 ONNX 연산은 RunOptions로 종료를 요청한다.
최초 파일 검증·모델 로딩 시간은 별도다. 끄려면 `rag.rerank.enabled: false`로 설정한다.

`/recall status`에서 `not_run`, `ready`, `rrf_fallback`, `disabled` 상태와 오류 종류를
확인할 수 있다. `rag.rerank` 이벤트는 모델·후보 수·처리 시간만 기록하고,
`rag.rerank_unavailable`은 오류 종류와 `fallback=rrf`를 기록한다. 본문은 기록하지 않는다.

| 명령 | 동작 |
|---|---|
| `/index` | 문서·벡터 동기화, 변경·삭제 반영 |
| `/recall status` | 대화 수, 문서 조각 수, 전체·대화 벡터 수, 벡터 생성 대기 수와 최근 오류 |
| `/recall 검색어` | 과거 질문·답변을 FTS5 + 벡터 + RRF로 검색 |
| `/recall reindex` | 현재 모델의 누락·구버전 벡터 재색인 |
| `/recall forget 턴ID` | 대화 쌍과 연결된 FTS·벡터를 검색 DB에서 삭제 |

`/clear`는 현재 문맥만 초기화한다. `/forget`은 기존 구조화 기억 명령이다.
`/recall forget`은 원본 JSONL 로그를 삭제하지 않는다. 삭제한 대화를 원본 로그에서
자동으로 다시 가져오지 않는다.

## 대화 기억

- 성공적으로 완료된 일반 대화와 `/search`의 질문·답변을 같은 턴 ID로 연결한다.
  실패·실행 승인 대기·의도 확인·관리 명령은 대화 색인에서 제외한다.
- 원문 쌍을 저장하고 질문·답변을 각각 1,200자 조각으로 임베딩한다. 답변에는
  `verified=false`, 생성 모델, 시각, 검색 답변의 출처를 기록한다.
- 새 질문은 과거 질문과 답변 조각을 모두 검색하며 동일 턴은 한 번만 반환한다.
- 검색한 대화는 일반 답변과 RAG 답변에 `untrusted_content`로 제공한다.
  시스템 지시나 확정 사실로 승격하지 않는다. 컨텍스트가 부족하면 해당 블록을
  생략하고 현재 질문·최근 대화를 보존한다. 전용 에이전트 계획 경로의 회상은 별도다.
- 새 대화는 완료 시 자동 저장한다. 이전 JSONL 로그는 아래 명시적 가져오기로 복구한다.
  대화 벡터는 재시작 후에도 유지되며, 관련 대화를 참고해 Qwen이 새 답변을 생성한다.

### 기존 대화 로그 가져오기

벡터 기억 기능을 설치하기 전 대화는 JSONL에만 남아 있을 수 있다. `/recall reindex`는
이미 검색 DB에 있는 원문만 임베딩하므로, 이전 로그는 먼저 가져와야 한다.

```powershell
.\.venv\Scripts\python.exe scripts/import_conversations.py
.\.venv\Scripts\python.exe scripts/import_conversations.py --apply
```

첫 명령은 파일과 대상 턴 수만 확인하고 DB를 변경하거나 모델을 호출하지 않는다.
`--apply`는 기존 벡터DB를 `paths.backups_dir`에 온라인 백업한 뒤 질문·답변을 가져온다.
세션·턴·요청 ID가 일치하는 완성된 대화만 복구하고 원래 시각과 생성 모델을 보존한다.
관리 명령, 미완료·오류·모호한 대화, 보존 기간 밖의 대화, 차단 대상과 이미 마스킹된
차단 대상은 제외한다. 손상된 파일은 수정하지 않고 오류 수로 보고한다.
이미 저장된 턴은 덮어쓰지 않으며 임베딩 장애 후 재실행하면 누락 벡터를 재시도한다.
가져오기는 자동 실행하지 않는다. 명시적으로 재실행하면 로그에 남은, 검색 DB에서
삭제했던 대화도 다시 가져올 수 있다.

## 실패·보존 정책

모델·확장 장애 시 해싱으로 전환하지 않는다. `rag.semantic_unavailable` 이벤트에
오류 종류를 남기고 FTS5로 계속 검색하며 30초 후 재시도한다. 벡터 생성이 실패해도
대화 텍스트는 남아 재색인할 수 있다. `/index`는 벡터 색인 실패를 오류 수에 포함한다.

대화는 임베딩 전에 기존 마스킹 정책을 적용한다. 차단 대상 시크릿을 포함한 턴은
자동 저장에서 제외한다. `local_only` 문서는 외부 전송하지 않으며 로컬 Ollama에는
마스킹한 내용을 제공한다. 과거 AI 답변보다 최신 문서와 사용자 발언을 우선한다.

대화 검색 기록은 기본 90일 보존하며 저장·검색·상태 조회 시 만료분을 삭제한다.
문서 벡터는 `/index`와 검색 시 원본 문서 색인과 동기화한다. 백업에는 기존 DB와
`semantic.sqlite3`를 SQLite 온라인 백업으로 함께 포함한다. 기존 백업에 포함된
삭제 데이터는 기존 백업 보존 정책을 따른다.

## 설정

`rag.semantic`: `enabled=true`, `model=embeddinggemma`, `timeout_s=30`,
`conversations_enabled=true`, `conversation_top_k=3`, `conversation_context_chars=2400`,
`retention_days=90`, `min_similarity=0.3`.
유사도 문턱은 정확도 확률이 아니며 실제 질문 데이터로 조정해야 한다.

## 테스트와 벤치마크

현재 실제 서비스 검색·답변 평가와 상태 라벨 계약은 [RAG 검증](RAG_VALIDATION.md)을 따른다.

```powershell
.\.venv\Scripts\python.exe -m pytest scripts/tests/unit/test_semantic_memory.py scripts/tests/integration/test_conversation_vectors.py
.\.venv\Scripts\python.exe -m pytest scripts/tests/integration/test_local_embeddings_smoke.py
.\.venv\Scripts\python.exe -m pytest scripts/tests/unit/test_reranking.py
.\.venv\Scripts\python.exe -m pytest scripts/tests/integration/test_local_reranker_smoke.py -s
```

두 번째는 실제 로컬 모델을 호출하는 `allow_network` 수동 스모크 테스트다.
일반 테스트는 개발자의 Ollama를 호출하지 않는다.

벤치마크 Vector/Hybrid도 새 모델과 `artifacts/evaluations/indexes/vector_index.sqlite3`를 사용한다.
임베딩 실패 시 벤치마크는 중단해 FTS-only 결과를 Hybrid 성능으로 오인하지 않게 한다.
기존 벤치마크의 `Hybrid RRF`는 재정렬 없는 비교 기준을 유지한다. 실제 서비스의
reranking을 포함한 정확도/지연 수치로 해석하면 안 된다. 별도 reranker 스모크 테스트는
한국어 후보 순위와 대화 검색, 시간 초과 시 복귀만 검증하며 대표 데이터셋 평가가 아니다.
기존 `artifacts/evaluations/benchmark_*`와 `vector_index.json`은 과거 해싱 평가 결과다. 새 품질을
주장하려면 별도 출력 디렉터리에서 동일 질문으로 다시 측정해야 한다. 저장 인덱스를
재사용한 실행의 `build_ms`는 최초 생성 비용과 구분한다.
