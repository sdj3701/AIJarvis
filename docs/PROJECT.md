# Jarvis 개발 문서 허브

2026-10-16 폴더 구조와 실행 방법은 [저장소 구조](REPOSITORY_LAYOUT.md), RAG 개발은 [RAG 문서](rag/README.md), 평가 결과는 [평가 안내](evaluations/README.md)에 정리했다.

2026-10-14 RAG 개발 문서를 현재 코드에 맞춰 개정했다. 전체 개발 문서는 아래 순서로 읽는다.

1. [RAG 구조·개발 순서](phase-03-research/README.md): 네 단계와 R3-01~08 적용 내용
   - [구현 결과·변경 이유](rag/RAG_R3_IMPLEMENTATION.md), [쉽게 따라가는 구조 설명](phase-03-research/DETAIL.md)
2. [개념 설명](phase-03-research/DETAIL.md): 토큰화·임베딩·검색·생성의 차이
3. [아키텍처 계약](DESIGN.md#16-rag검색-계약): 현재 구현과 책임 경계
4. [이번 변경 사항](rag/RAG_REDESIGN_CHANGELOG.md): 수정 이유·확인한 결함·검증 범위

현재는 embeddinggemma + FTS5/sqlite-vec + RRF + Cross-Encoder로 문서를 찾고,
검색 원문을 Qwen에 전달해 생성·검사한다. Ollama는 임베딩과 생성의 런타임이다.
새 대화는 미검증 기억으로 저장한다. 문서 재귀 청크·질문별 검색·문맥 보강·답변 검증은 구현되어 있으며, 세부 요구사항의 완전한 누락 검사는 후속 과제다.
설치·명령은 [로컬 임베딩과 대화 검색](post-v1/LOCAL_SEMANTIC_MEMORY.md)을 따른다.

이 파일은 Jarvis를 구현할 때 **가장 먼저 읽는 문서**다. 아래 순서를 지키면 다른 대화나 구두 설명 없이 개발을 이어갈 수 있다.

> 현재 기본 브랜치는 `main`이며 v2 구현을 기준으로 한다. 현재 작업 트리에는 대화·문서 RAG·로컬 임베딩·재정렬이 구현되어 있다.
> 기존 프로토타입은 `main`과 `D:\Ai\Jarvis-prototype`에 동결되어 있다.
> v2 개발 데이터는 `D:\Jarvis-v2-dev`만 사용한다. 작업 규칙은
> [v2 재구축 안내](00-start-here/REBUILD.md)를 먼저 확인한다.

## 1. 처음 시작하는 순서

1. [착수 안내](00-start-here/README.md)를 읽고 미결정 항목을 확인한다.
2. [결정 기록](00-start-here/DECISIONS.md)에서 현재 Phase를 막는 항목을 확정한다.
3. 해당 Phase 폴더의 `README.md`를 위에서 아래로 수행한다.
4. 각 작업마다 테스트를 먼저 연결하고 구현한다.
5. `python scripts\gate.py --phase N`이 종료 코드 0일 때만 다음 Phase로 이동한다.

현재 RAG 구현·평가 기준: [RAG 실행·검색·근거 검증](post-v1/RAG_VALIDATION.md)
아래 Phase 순서는 개발 계획이며 현재 구현 상태나 릴리스 인증을 뜻하지 않는다.

현재 진행 상태: [개발 진행 현황](PROGRESS.md)

프로토타입과 동작을 비교할 때는 `D:\Ai\Jarvis-prototype`만 실행한다. v2 코드와 `D:\Jarvis`를 섞지 않는다.

Phase 0 준비·실행 명령:

```powershell
python scripts\bootstrap.py
python -m app
```

현재 CLI는 설정·단일 인스턴스 락을 확인하고 대화/RAG 경로를 실행한다. 초기 기반 단계의 자동 게이트는 `python scripts\gate.py --phase 0`이다.

## 2. 문서의 역할과 우선순위

| 문서 | 답하는 질문 | 변경 권한 |
|------|-------------|-----------|
| [PLAN.md](PLAN.md) | 무엇을, 왜, 어느 릴리스까지 만드는가? | 제품 범위·Phase·완료 기준의 기준 |
| [DESIGN.md](DESIGN.md) | 모듈이 어떻게 나뉘고 어떤 계약으로 통신하는가? | 코드 구조·인터페이스의 기준 |
| [SCHEMAS.md](SCHEMAS.md) | 파일·DB·이벤트·도구 데이터는 어떤 모양인가? | 저장 형식의 단일 기준 |
| [TESTING.md](TESTING.md) | 완료를 어떻게 증명하는가? | 테스트·릴리스 게이트의 기준 |
| [`docs/phase-*`](README.md) | 지금 어떤 파일을 어떤 순서로 구현하는가? | 실행 순서와 작업 체크리스트 |
| [`docs/*/DETAIL.md`](DETAIL.md) | 그 규칙이 왜 필요한가? | 세부 개발문서, 설명 전용 |
| [`config/*.example.yaml`](../config) | 정책·운영 기본값은 무엇인가? | 실행 설정 템플릿 |

내용이 충돌하면 `PLAN → DESIGN → SCHEMAS → TESTING → Phase 문서` 순으로 무조건 덮어쓰지 않는다. 먼저 충돌의 성격에 맞는 기준 문서를 수정하고, [문서 변경 규칙](reference/DOCUMENTATION_RULES.md)에 따라 하위 문서를 동기화한다.

## 3. 전체 개발 흐름

작업 ID 단위의 상세 흐름·게이트·의존 관계는 [개발 흐름](DEVELOPMENT_FLOW.md)에 있다.
아래는 단계 요약이다.

| 순서 | 개발 단계 | 핵심 산출물 | 완료 후 상태 |
|------|-----------|-------------|--------------|
| 0 | [착수 준비](00-start-here/README.md) | 결정 기록, 개발 환경 확인 | 구현 조건 확정 |
| 1 | [Phase 0 — 기반](phase-00-foundation/README.md) | 설정·ID·로그·SQLite·복구 골격 | 안전한 빈 CLI |
| 2 | [Phase 1 — 대화](phase-01-chat/README.md) | LLM 클라이언트·대화·예산 | 저장되는 챗봇 |
| 3 | [Phase 2 — 기억](phase-02-memory/README.md) | 기억 lifecycle·검색·요약 | 재시작 후 기억 유지 |
| 4 | [Phase 3 — 검색/RAG](phase-03-research/README.md) | 웹·문서 검색·근거·신뢰 경계 | 근거를 찾아주는 비서(MVP) |
| 5 | [Phase 4 — PC 도구](phase-04-tools/README.md) | Safety Gate·승인·Secure Runner | 제한된 PC 제어 |
| 6 | [Phase 5 — 에이전트](phase-05-agent/README.md) | 멀티스텝·체크포인트·멱등성 | 복합 작업 수행 |
| 7 | [Phase 6 — 보안 게이트](phase-06-security/README.md) | 보안 회귀·백업·감사 검증 | v0.5 후보 |
| 8 | [Phase 7 — 음성](phase-07-voice/README.md) | PTT·STT·TTS | 음성 입출력 |
| 9 | [Phase 8 — 상주 UI](phase-08-resident-ui/README.md) | 트레이·단축키·패키징 | v1 후보 |
| 10 | [운영과 릴리스](operations/README.md) | 백업·복원·장애 대응·7일 안정화 | v1 릴리스 |
| 11 | [Post-v1 선택 기능](post-v1/README.md) | 다중 모델·검색 규모·연동·웨이크워드 고도화 | 개별 후속 릴리스 |

## 4. Phase 문서 사용법

각 Phase 문서는 같은 구조를 사용한다.

1. `진입 조건`: 이전 Phase에서 반드시 끝났어야 하는 것
2. `산출물`: 새로 만들거나 변경할 파일
3. `구현 순서`: 커밋 가능한 작은 작업 단위
4. `계약`: 구현이 반드시 지켜야 할 인터페이스·스키마
5. `테스트`: 작업 직후 실행할 검증
6. `완료 게이트`: 다음 Phase로 넘어가는 객관적 조건
7. `이 Phase에서 하지 않는 것`: 범위 폭발 방지

작업 하나의 기본 사이클은 다음과 같다.

```text
기준 문서 확인 → 실패 테스트 작성 → 최소 구현 → 단위 테스트
→ 통합 테스트 → 문서/설정 동기화 → Phase 게이트
```

## 5. 고정된 프로젝트 경계

- 소스 저장소: `D:\Ai\Jarvis`
- 프로토타입 데이터: `D:\Jarvis` (v2에서 접근 금지)
- v2 개발 데이터: `D:\Jarvis-v2-dev`
- v2 출시 후 운영 데이터: 별도 마이그레이션 승인 전까지 미변경
- 테스트 데이터: pytest의 `tmp_path` 아래 임시 루트
- 운영 시크릿: Windows Credential Manager
- 개발용 `.env`: `D:\Ai\Jarvis\.env`, `dev_mode=true`에서만 허용
- 상태 저장: raw 대화는 JSONL, 상태가 있는 데이터는 SQLite
- 기본 보안 정책: 등록되지 않은 도구·경로·도메인은 거부

## 6. 구현을 시작하기 전에 남은 결정

결정과 구현·인수 상태를 구분한다. 현재 R3 재현·설계 작업을 막는 결정은 없다.

- Phase 1: D005 결정 완료 — Ollama, `qwen3.5:9b`, 외부 단가 USD 0.00
- Phase 3: D006 결정 완료 — DuckDuckGo (`ddgs`)
- Phase 3: 텍스트 PDF parser (D012 구현·검증), RAG 청크·문맥·갱신 세부값 (D024 개발 기본값 적용)
- Phase 6: 백업 대상·암호화 도구 선택 완료 (D007~D008), 복원·릴리스 검증 별도
- Phase 7: D009 로컬 TTS, D010 호출 방식, D016 하이브리드 한국어 STT 결정 완료
- Phase 8: 패키징·전역 단축키·자동 시작 방식 (D013~D015 pending)

결정 상태와 선택 기준은 [DECISIONS.md](00-start-here/DECISIONS.md)에 기록한다.

## 7. 참고 문서

- [전체 개발 흐름](DEVELOPMENT_FLOW.md)
- [전체 문서 지도](README.md)
- [세부 개발문서 지도](DETAIL.md)
- [개발 진행 현황](PROGRESS.md)
- [요구사항 추적표](reference/TRACEABILITY.md)
- [위협 모델](reference/THREAT_MODEL.md)
- [문서 변경 규칙](reference/DOCUMENTATION_RULES.md)
- [운영·장애 대응](operations/README.md)

## 8. 로컬 RAG 검색 벤치마크

2026-10-14 이후 실제 서비스 검색·근거 검증 평가는 [RAG 검증 문서](post-v1/RAG_VALIDATION.md)를 따른다.
아래 기존 3방식 벤치마크는 검색 비교용이며 재정렬·답변 생성·인용 검증을 포함하지 않는다.

Vector Search, SQLite FTS5(BM25), Hybrid RRF가 같은 쿼리·top-k로 검색품질,
지연시간, 인덱스 운영 비용을 비교한다. 벤치마크 자체는 기존 `documents`/
`doc_chunks`를 읽기만 하며, 생성한 인덱스와 리포트는 `artifacts/evaluations/`에만 저장한다.

```powershell
pip install -e ".[benchmark]"
python -m app.rag.benchmark --config-dir D:\Jarvis-v2-dev\config
```

실행 전 [evaluation_queries.json](../datasets/evaluation_queries.json)의 문서 ID와 쿼리를 실제 코퍼스에
맞게 지정한다. 현재 파일은 데모 문서 20개에 대한 서로 다른 질문 200개다.
`keyword` 67개, `semantic` 67개, `hybrid` 66개이며 이전 60개 질문을 포함한다.
정답 매핑은 사람이 검토·수정할 수 있다. 실행 후 `artifacts/evaluations/document_catalog.csv`에 실제 인덱스의
`document_id`가 출력되므로 정답 매핑을 점검할 수 있다.

기본 설정은 방식별 10개 질문을 워밍업한 후 질문당 5회 반복 측정하고 `top_k=1,3,5,10`을 모두
평가한다. 기본으로는 기존 인덱스를 읽기만 하며, 현재 `docs_dir`를 다시 동기화할 필요가 있을 때만
`--sync`를 추가한다. 확인용으로는
`--limit 5 --repeats 1 --warmup-queries 0 --top-k 10`을 사용할 수 있다. Hybrid RRF의
스무딩 상수는 `rag.rrf_k`로 설정하며 기본값은 60이다.

기존 그래프 5종과 함께 하늘색 격자·원형 점·직선 연결 스타일의 선 그래프 3종을 생성한다.
`recall_by_top_k.png`는 결과 수에 따른 Recall, `quality_convergence.png`는 평가 질문 수에
따른 누적 평균 Recall@5, `cumulative_response_time.png`는 질문별 평균 전체 응답 시간의
누적 합이다. 후자의 시간은 인덱싱·워밍업을 제외하며 5회 반복 시간을 합산하지 않는다.
누적 그래프는 모든 방식에 동일한 고정 셔플(seed=42)을 적용한다. 보간이나 점수 조작은 없다.
질문 증가가 품질 상승 또는 매끄러운 곡선을 보장하지 않으며, 이 결과는 데모 문서 20개에
대한 평가다. 실제 운영 자료·사용자 질문으로 일반화하려면 별도 평가가 필요하다.

## 명령 기억

명령 기억을 켜면 확인된 앱 실행 문장과 문장 임베딩을 기존 기억 DB에 저장해 재시작 후에도
재사용한다. 이 개발 환경에는 `embeddinggemma`를 설치하고 `command_memory.enabled=true`를 적용했다.
처음 듣는 유사 표현은 “앱 실행이라는 뜻인가요?”를 먼저 확인하며 최초 앱 실행 허용은 별도다.
`/commands`로 명령/벡터 건수와 목록을 확인하고,
`/learn 작업 시작 => /open_app discord`로 새로운 표현을 직접 가르칠 수 있다.
잘못된 예시는 `/commands forget ID`, 벡터 재생성은 `/commands reindex`를 사용한다.
앱 실행 이외의 종료·파일 작업 학습 및 모델 가중치 재학습은 포함하지 않는다.
상세는 [명령 기억 문서](post-v1/COMMAND_MEMORY.md)를 따른다.

## 응답 룰북

[response_rulebook.md](../scripts/app/orchestrator/prompts/response_rulebook.md)를 시작 시 읽고
모든 사용자 답변 생성에 적용한다. 기본은 결론 한 문장·100자이며 승인·경고는 예외다.
수정 후 Jarvis를 완전히 종료하고 다시 실행하면 반영된다. `/clear`로 지워지지 않는다.
GUI ‘상세 보기’ 또는 `/details`로 직전 원문을, `/status`로 버전·해시를 확인한다.
‘자세히 설명해줘’는 이번 화면 답변만 상세하게, ‘말로도 자세히 설명해줘’는 음성까지
상세하게 요청한다. 실제 낭독 성능 비교는 아직 수행하지 않았다.
개발 계약과 평가 범위는 [룰북 문서](post-v1/PROPOSAL_PERSISTENT_RESPONSE_RULEBOOK.md)를 따른다.
