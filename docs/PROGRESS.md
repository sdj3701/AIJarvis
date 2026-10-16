# 개발 진행 현황

현재 상태와 검증 증거를 기록한다. 상세 요구는 [PLAN](PLAN.md), 실행 순서는
[Phase 3](phase-03-research/README.md), 전체 지도는 [개발 흐름](DEVELOPMENT_FLOW.md)을 따른다.

> 마지막 정리: 2026-10-16 — v2 폴더 정리·main 전환
> 브랜치: `main`; 개발 데이터: `D:\Jarvis-v2-dev`
> 현재 작업: R3-01~07 구현·검증, R3-08 자동 평가·문서 적용
> 남은 인수: 실장치 UI/음성·정식 릴리스; [구현 보고](rag/RAG_R3_IMPLEMENTATION.md)

PDF `.md` 자동 저장 후속 적용: `implemented_verified`. 기존 DB/벡터 저장을 유지하면서 전용 폴더에
전체 Markdown을 내보낸다. 제공 PDF의 DB/파일 일치·34청크/벡터·검색 3건·복원을 확인했고 개발 DB에도
재색인 없이 적용했다. [변경·시험·파일 위치](rag/RAG_PDF_INGESTION.md)의 7절 참고. EXE 재빌드는 별도다.


RG-ANSWER-QUALITY: `implemented_verified`. 재귀 34청크/기존 벡터를 유지하고 동일 PDF 100문항의
완전 정답이 60→82개(+22%p), 인용 178건 위치 오류 0건, 회귀 568개 통과다. 남은 일부 답변 5개와
불필요한 보류 10개, 범위 밖 mypy 오류 7개를 기록했다. [변경·검증·제한](rag/RAG_ANSWER_QUALITY.md).

REPO-LAYOUT: 문서는 docs, 실행 코드는 scripts/app, 테스트는 scripts/tests, 평가 결과는 artifacts/evaluations로 이동했다. Python app 모듈명과 운영 데이터 위치는 유지한다. 전체 테스트 812개 통과(외부 환경 5개 제외), 패키지·런처·문서 검증 완료. 기존 Ruff 52개 및 mypy 7개는 별도 잔여 항목이다. [폴더·검증·main 전환](REPOSITORY_LAYOUT.md).

## 1. 상태 값

- `not_started`: 미착수
- `in_progress`: 작업 중
- `implemented_unverified`: 관련 구현이 있지만 최신 정식 게이트/인수 증거가 없음
- `implemented_verified`: 해당 코드·자동 회귀·실제 모델 평가 확인; 정식 릴리스와 별개
- `unverified`: 이번 점검에서 전체 범위·완료를 확인하지 않음
- `blocked`: 외부 결정/환경 때문에 진행 불가
- `gate_failed`: 정식 게이트 실패
- `completed`: 요구 범위와 정식 게이트의 통과 증거까지 기록

## 2. 현재 구현과 릴리스 상태

| 영역 | 상태 | 확인 범위와 남은 증거 |
|---|---|---|
| 기반·대화·기억 | implemented_unverified | 설정·SQLite·Ollama·대화 기억 코드 존재; 과거 Phase 0 표만으로 현재 상태 판단 금지 |
| 문서 RAG·로컬 임베딩·재정렬 | implemented_unverified | R3 코드·자동 회귀·실제 모델 확인; 실장치 인수와 최신 정식 릴리스 게이트는 미완료 |
| PC 도구·에이전트·보안 | unverified | 관련 코드 존재; 이번 RAG 문서 개정에서 전체 인수 검증하지 않음 |
| 음성·GUI·런처 | unverified | 관련 코드/루트 런처 존재; 실장치·깨끗한 설치 환경 인수 증거 별도 필요 |
| v1 안정화 | unverified | 최신 버전의 7일 운영 증거 확인 필요 |

과거 프로토타입의 gate 성공은 5장에 보존하고 현재 v2 완료 증거로 쓰지 않는다.
루트 `Jarvis.exe`는 `.venv\Scripts\pythonw.exe -m app --gui`를 실행하는 런처다.
소스와 별도로 고정된 PyInstaller 산출물이라고 가정하지 않는다.

## 3. 현재 작업 큐

| 작업 | 상태 | 증거/남은 행동 |
|---|---|---|
| R3-01 질문 계획·후속 질문 | implemented_verified | QueryPlan 회귀·실제 후속 질문 |
| R3-02 역할별 임베딩 | implemented_verified | digest/캐시 격리·실제 raw/role 비교 |
| R3-03 문맥·토큰 청크 | implemented_verified | recursive-context-v4, 문단·원문 보존·토큰 상한·질문 경로 분리 |
| R3-04 갱신·세대 | implemented_verified | 설정 변경·삭제·중단·롤백·사본 복구 |
| R3-05 문맥 선택·예산 | implemented_verified | 512토큰 뒤쪽·이웃·중복 제거·입력 예산 |
| R3-06 답변 모드 | implemented_verified | text/voice·출처·기억·오류/내부 질문 분기 |
| R3-07 계산 근거 | implemented_verified | 합/차·단위·날짜 회귀·실제 합계 생성 |
| R3-08 평가·운영 인수 | in_progress | 자동 평가·문서 완료; 물리 UI/음성·정식 릴리스 인수 남음 |

### 최신 검증 증거

2026-10-15 PDF 후속 적용: [구현·검증 보고](rag/RAG_PDF_INGESTION.md). 실제 6쪽 PDF를 직접 등록해
34청크, 최대 381토큰, 제목 전용/조항 혼합 0건, 검색 Hit@1=8/9·Hit@3=9/9를 확인했다.
최종 Phase 0~3·security 531개 통과, 실제 답변 회귀 17/17 통과. 개발 DB는 21문서·54청크로 갱신했다.
아래 재귀 청크 수치는 PDF 지원 전 이력이다.

2026-10-15 재귀 청크 보완: [적용 보고](rag/RAG_RECURSIVE_CHUNKING.md),
[새 결과](../artifacts/evaluations/rag-recursive-20261015). 개발 문서 20개를 백업 후 새 세대로 교체했다.
짧은 문서 20개는 각각 한 청크, 최대 123토큰이며 모든 청크의 토큰 측정 완료·DB 무결성 정상이다.
- 최종 Phase 0~3·security **513 passed**, 집중 회귀 **45 passed**. Ruff·RAG mypy 통과.
- 최종 실제 답변 **17/17**, 검색 Hit@1=9/11·Hit@5=11/11. 실제 Unicode 문서도 토큰 상한·원문 보존 확인.

아래는 **2026-10-14 기준선**이며 새 코드 검증과 합산하지 않는다.

- Phase 0~3·security 직접 pytest: **488 passed**, 260 deselected.
- 전체 비네트워크·비slow pytest: **728 passed, 기존 setup 오류 8건**, 12 deselected.
  작업 전 사본에서 동일한 Sandbox 인자 누락 8건 재현.
- 실제 로컬 모델 답변: **17/17**. 검색 합성 11질의: Hit@1=9/11, Hit@5=11/11.
- 수정 Python Ruff 통과. RAG/query_plan mypy 26소스 통과; 전체는 기존 음성·GUI 타입 오류 7개.
- 정식 `gate.py --phase 3`: 기존 미커밋 변경 때문에 실행 거부. 직접 pytest와 정식 게이트를 구분한다.
- [구현 보고·한계](rag/RAG_R3_IMPLEMENTATION.md), [결과 폴더](../artifacts/evaluations/rag-r3-20261014), [TESTING](TESTING.md).

과거 75개 집중 회귀·20문서 200질의·12답변 평가와 이번 수치를 합산하지 않는다.
평가는 합성 DB에서 수행한다. 2026-10-15 별도 적용 단계에서 개발 DB의 기존 문서 색인을 갱신했다.

### 과거 Phase 0 작업 기록

아래는 2026-08-18~19 당시 작업 단위 기록이다. 현재 대시보드나 최신 Phase gate로 해석하지 않는다.

| 작업 | 당시 상태 | 담당 | 시작 | 완료 | 당시 증거/메모 |
|------|------|------|------|------|-----------|
| P0-01 프로젝트와 품질 도구 | completed | Cursor | 2026-08-18 | 2026-08-18 | collect-only 453, ruff/mypy 통과, lock은 `--extra=dev` |
| P0-02 설정 모델과 로더 | completed | Cursor | 2026-08-19 | 2026-08-19 | example 3파일 로드, deny·해시·v2 config dir |
| P0-03 시크릿 로더 | completed | Cursor | 2026-08-19 | 2026-08-19 | keyring 우선, .env는 dev_mode만, 원문 비노출 |
| P0-04 공통 타입 | completed | Cursor | 2026-08-19 | 2026-08-19 | Clock·ID·예외·canonical hash |
| P0-05 데이터 트리와 SQLite | completed | Cursor | 2026-08-19 | 2026-08-19 | bootstrap 멱등, FTS integrity-check |
| P0-06 이벤트·마스킹 | completed | Cursor | 2026-08-19 | 2026-08-19 | 봉투·fsync·민감문자열 0건 |
| P0-07 원자적 쓰기·복구·단일 인스턴스 | completed | Cursor | 2026-08-19 | 2026-08-19 | tmp 격리, lock, 종료 코드 1 |
| P0-08 CLI와 조립 | completed | Cursor | 2026-08-19 | 2026-08-19 | `python -m app` echo, LLM 없음 |

## 4. 남은 결정과 제한

| 항목 | 상태 | 영향 |
|---|---|---|
| D023 RAG 책임·답변 정책 | decided | R3 코드와 자동 평가 적용 |
| D024 청크/문맥/갱신 수치 | decided (개발 기본값) | 384/48토큰·이웃1·5초 확인; 실무 최적화 별도 |
| D012 PDF parser | decided | `.md`·`.txt`·텍스트 `.pdf`; OCR/복잡한 레이아웃 별도 |
| D007·D008 백업 | decided | 선택 완료와 복원 인수 통과는 별개 |
| D013~D015 배포·UI | pending | 현재 개발용 런처 존재와 정식 패키징 결정은 별개 |

정식 값과 근거는 [DECISIONS](00-start-here/DECISIONS.md)를 따른다.

## 5. Phase 게이트 증거 로그

Phase를 완료할 때 행을 추가한다. 프로토타입 행은 비교용이며 `rebuild/v2` 완료로 쓰지 않는다.

| 날짜 | Phase | commit/build | 명령 | 종료 코드 | 핵심 지표 | 증거 경로 |
|------|-------|--------------|------|-----------|-----------|-----------|
| 2026-08-11 | Phase 0 (prototype-v1) | 298f093 | `python scripts\gate.py --phase 0` | 0 | 137 passed, failed 0, skipped 0 | [phase0-20260811.json](../artifacts/gates/phase0-20260811.json) |
| 2026-08-11 | Phase 1 (prototype-v1) | 368e8e4 | `python scripts\gate.py --phase 1` | 0 | 283 passed, failed 0, skipped 0, crash 20/20 입력 유실 0 | [phase1-20260811.json](../artifacts/gates/phase1-20260811.json) |
| 2026-08-11 | Phase 2 (prototype-v1) | 40ba9cc | `python scripts\gate.py --phase 2` | 0 | 300 passed, failed 0, skipped 0, memory_eval ≥90% | [phase2-20260811.json](../artifacts/gates/phase2-20260811.json) |
| 2026-08-11 | Phase 3 (prototype-v1) | 40ba9cc | `python scripts\gate.py --phase 3` | 0 | 337 passed, failed 0, skipped 0, security·phase3 green | [phase3-20260811.json](../artifacts/gates/phase3-20260811.json) |
| 2026-08-11 | Phase 4 (prototype-v1) | 40ba9cc | `python scripts\gate.py --phase 4` | 0 | 379 passed, failed 0, skipped 0, phase4·security green | [phase4-20260811.json](../artifacts/gates/phase4-20260811.json) |
| 2026-08-11 | Phase 5 (prototype-v1) | 40ba9cc | `python scripts\gate.py --phase 5` | 0 | 393 passed, failed 0, skipped 0, phase5·security green | [phase5-20260811.json](../artifacts/gates/phase5-20260811.json) |
| 2026-08-18 | Phase 0 (경로 정리, 재구축 완료 아님) | 4ed1eaf | `python scripts\gate.py --phase 0` | 0 | 148 passed, failed 0, skipped 0 | [phase0-20260818.json](../artifacts/gates/phase0-20260818.json) |

기록 예:

```text
2026-08-20 | Phase 1 | abc1234 | python scripts\gate.py --phase 1
0 | crash 20/20, retry 통과 | artifacts/gates/phase1-20260820.json
```

## 6. 업데이트 규칙

1. 시작 시 작업을 in_progress로, 요구 검증과 게이트 증거가 있을 때 completed로 바꾼다.
2. 기존 테스트 통과만으로 새 요구의 MISSING을 지우지 않는다.
3. 문서·설계 완료, 코드 적용, migration, 실제 모델 평가, 릴리스 승인을 구분한다.
4. 게이트에는 branch/commit 또는 소스 hash·명령·종료 코드·증거 경로를 남긴다.
5. 실패 로그에 시크릿이나 사용자 문서/대화 원문을 붙이지 않는다.

인용 개선 및 TC 1·2 결과: [변경 보고](rag/RAG_CITATION_FIXES.md).
