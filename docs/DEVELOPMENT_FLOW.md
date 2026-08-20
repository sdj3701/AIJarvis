# 전체 개발 흐름

착수 준비부터 v1 운영까지를 **작업 ID 단위**로 이어 붙인 문서다. "지금 무엇을 하고, 그것이
끝나면 무엇이 열리는가"를 한 곳에서 본다.

이 문서는 순서와 의존 관계를 보여주는 지도이며 **기준 문서가 아니다**. 인터페이스·스키마·
완료 기준이 어긋나면 [문서 계층](#2-문서-계층)의 상위 문서를 따른다.

- 각 단계의 실행 절차: 해당 폴더의 `README.md`
- 각 단계의 배경과 이유: 같은 폴더의 `DETAIL.md` (세부 개발문서)
- 현재 진행 위치: [PROGRESS.md](./PROGRESS.md)

---

## 1. 현재 위치

| 항목 | 값 |
|------|-----|
| 브랜치 | `rebuild/v2` |
| 현재 단계 | Phase 0 — 기반 구축 |
| 상태 | P0-01 ~ P0-08 구현 완료, 공식 게이트 실행 대기 |
| 다음 행동 | `python scripts\gate.py --phase 0` 종료 코드 0 확보 → Phase 1 진입 |
| 프로토타입 | `main` 브랜치와 `D:\Ai\Jarvis-prototype`에 동결. v2 완료로 계산하지 않는다 |

상세 상태와 게이트 증거는 [PROGRESS.md](./PROGRESS.md)에서 관리한다. 이 문서의 표는 요약이며,
값이 어긋나면 PROGRESS가 기준이다.

---

## 2. 문서 계층

| 층 | 문서 | 답하는 질문 | 기준 여부 |
|----|------|-------------|-----------|
| 기준 | [PLAN.md](../PLAN.md) | 무엇을, 왜, 어느 릴리스까지 | 제품 범위의 단일 기준 |
| 기준 | [DESIGN.md](../DESIGN.md) | 모듈·인터페이스·의존 방향 | 코드 구조의 단일 기준 |
| 기준 | [SCHEMAS.md](../SCHEMAS.md) | 파일·DB·이벤트·도구 데이터 모양 | 저장 형식의 단일 기준 |
| 기준 | [TESTING.md](../TESTING.md) | 완료를 어떻게 증명하는가 | 테스트·게이트의 단일 기준 |
| 실행 | `docs/*/README.md` | 어떤 파일을 어떤 순서로 구현하는가 | 작업 순서의 기준 |
| 세부 | `docs/*/DETAIL.md` | 그 규칙이 왜 필요한가 | 설명 전용, 기준 아님 |
| 흐름 | 이 문서 | 단계가 어떻게 이어지는가 | 지도, 기준 아님 |
| 상태 | [PROGRESS.md](./PROGRESS.md) | 지금 어디까지 왔는가 | 진행 상태의 기준 |
| 결정 | [DECISIONS.md](./00-start-here/DECISIONS.md) | 사람이 골라야 하는 값 | 미결정 값의 기준 |

충돌이 생기면 위쪽 문서를 먼저 고친 뒤 아래를 동기화한다. 절차는
[문서 변경 규칙](./reference/DOCUMENTATION_RULES.md)에 있다.

---

## 3. 전체 흐름 한눈에

```text
착수 준비 (00-start-here)
  │  경로 계약 · 환경 확인 · 결정 기록
  ▼
Phase 0  기반 구축        P0-01 ~ P0-08   안 깨지는 빈 CLI
  ▼
Phase 1  대화             P1-01 ~ P1-07   저장되는 챗봇
  ▼
Phase 2  장기 기억        P2-01 ~ P2-07   재시작 후에도 기억
  ▼
Phase 3  검색과 근거      P3-01 ~ P3-08   ★ MVP
  ▼
Phase 4  PC 도구          P4-01 ~ P4-07   승인 기반 PC 제어
  ▼
Phase 5  에이전트         P5-01 ~ P5-07   멀티스텝 자동 수행
  ▼
Phase 6  보안 게이트      P6-01 ~ P6-08   ★ v0.5
  ▼
Phase 7  음성            P7-01 ~ P7-06   음성 입출력
  ▼
Phase 8  상주 UI         P8-01 ~ P8-07   v1 후보
  ▼
운영·안정화 (operations)                  ★ v1
  ▼
Post-v1 선택 기능                          기능별 개별 릴리스
```

### 릴리스 경계

| 릴리스 | 포함 Phase | 사용자에게 보이는 결과 | 출시 조건 |
|--------|------------|------------------------|-----------|
| MVP | 0 ~ 3 | 기억하고 근거를 찾아주는 CLI 비서 | 검색·기억·개인정보 테스트 통과 |
| v0.5 | 4 ~ 6 | 안전하게 PC 작업을 수행하는 텍스트 에이전트 | Critical/High 보안 결함 0건 |
| v1 | 7 ~ 8 | 음성·단축키로 호출하는 상주형 비서 | 1주 안정화와 최종 데모 통과 |

출처: [PLAN 2.3](../PLAN.md)

### 이 순서인 이유

저장이 깨지지 않는 것을 먼저 만들고 그 위에 기능을 쌓는다. 순서를 바꾸면 아래가 무너진다.

- **Phase 0이 맨 앞인 이유**: 원자적 쓰기·복구·마스킹을 나중에 붙이면 이미 쌓인 로그와
  세이브 데이터는 되돌릴 수 없다.
- **Phase 4가 Phase 3 뒤인 이유**: AI가 파일을 만들고 앱을 실행할 수 있게 되는 순간부터
  실수의 대가가 실제 피해가 된다. "외부 텍스트와 LLM 출력은 못 믿는 데이터"라는 취급
  방식을 Phase 3에서 먼저 완성해 둔다.
- **Phase 6이 기능 Phase 사이에 있는 이유**: 기능을 더 쌓기 전에 v0.5 신뢰 경계를 공격
  관점에서 한 번 닫는다.

---

## 4. 작업 한 건의 사이클

Phase 안의 모든 작업 ID는 같은 사이클을 돈다.

```text
기준 문서 확인 → 실패하는 테스트 작성 → 최소 구현 → 단위 테스트
→ 통합 테스트 → 문서·설정 동기화 → Phase 게이트
```

"실패하는 테스트를 먼저 쓴다"는 버그 재현 케이스를 먼저 만들고 고치는 것과 같다. 재현이
안 되면 고쳐졌는지도 증명할 수 없다.

### Phase 문서의 고정 7절

| 절 | 의미 |
|----|------|
| 진입 조건 | 선행 작업. 안 끝났으면 시작하지 않는다 |
| 만들 파일 | 이번에 손댈 파일 목록. 이 밖은 건드리지 않는다 |
| 구현 순서 | 커밋 단위로 쪼갠 작업. `P0-01` 같은 ID가 티켓 번호 |
| 계약 | 반드시 지킬 인터페이스·데이터 포맷과 기준 문서 링크 |
| 테스트 | 작업 직후 돌릴 검증 |
| 완료 게이트 | 통과 판정 조건 |
| 하지 않는 것 | 범위 폭발 방지 |

### 게이트 명령

```powershell
python scripts\gate.py --phase N     # Phase N 완료 판정 (0~8)
python scripts\gate.py --report      # p95·정확도 정량 지표
python scripts\gate.py --verify-audit # 감사 로그 해시 체인 검증
python scripts\gate.py --integrity   # 운영 중 일일 점검
```

`--phase N`은 `(phase0 or ... or phaseN) and not allow_network` 마커를 실행하고, 실패가
있으면 종료 코드 1, 정량 기준 미달이면 종료 코드 2를 낸다. 결과는
`artifacts\gates\phase<N>-<YYYYMMDD>.json`에 남고 이 파일이 PROGRESS의 게이트 증거다.

**Phase 완료는 사람이 판정하지 않는다. 게이트 종료 코드 0만이 완료다.** `slow` 마커는
제외하지 않는다. 20회 강제 종료 같은 느린 테스트가 곧 완료 기준이기 때문이다.

---

## 5. 단계별 상세

### 착수 준비 — [00-start-here](./00-start-here/README.md)

코드를 만들기 전 한 번만 수행한다. 세부: [착수 준비 세부 개발문서](./00-start-here/DETAIL.md)

**환경 조건**

| 항목 | 요구 | 미충족 시 |
|------|------|-----------|
| OS | Windows 10/11 | 진입 불가 |
| Python | 3.11 이상 | Phase 0 진입 차단 |
| `D:\Ai\Jarvis` | 쓰기 가능 | Phase 0 진입 차단 |
| `D:\Jarvis-v2-dev` | 생성 권한 + 5GB 여유 | Phase 0 진입 차단 |
| NVIDIA 드라이버·CUDA | Phase 7에서만 필요 | Phase 0~6은 진행 가능 |

**경로 계약**

| 용도 | 경로 | 규칙 |
|------|------|------|
| 소스 | `D:\Ai\Jarvis` | Git 관리 대상 |
| 프로토타입 소스 | `D:\Ai\Jarvis-prototype` | `main` 동결본, 비교 전용 |
| 프로토타입 데이터 | `D:\Jarvis` | v2에서 접근·변경 금지 |
| v2 개발 데이터 | `D:\Jarvis-v2-dev` | Git 관리 금지 |
| 개발 시크릿 | `D:\Ai\Jarvis\.env` | `dev_mode=true`에서만, Git 제외 |
| 운영 시크릿 | Windows Credential Manager | 파일 저장 금지 |
| 테스트 | pytest `tmp_path` | 운영 경로 접근 금지 |

**완료 조건**: 착수 체크리스트 6항목 전부 체크. 현재 완료됨.

---

### Phase 0 — 기반 구축 · [README](./phase-00-foundation/README.md) · [세부](./phase-00-foundation/DETAIL.md)

**목표**: 외부 API도 PC 도구도 없이 안전하게 시작·종료하는 빈 CLI 골격. 설정 오류, 시크릿
노출, 중복 실행, 부분 파일을 여기서 전부 차단한다.

**진입 조건**: 착수 체크리스트 완료 · Python 3.11+ · [D001~D004](./00-start-here/DECISIONS.md) `decided`

| ID | 작업 | 핵심 내용 | 계약 |
|----|------|-----------|------|
| P0-01 | 프로젝트와 품질 도구 | `pyproject.toml`, `.venv`, 해시 포함 `requirements.lock`, `.gitignore`. `artifacts\gates\`는 제외하지 않는다 | — |
| P0-02 | 설정 모델과 로더 | Pydantic `extra="forbid"`, `schema_version`·경로·예산·비율·`default: deny` 검증, `config_hash` 계산 | [SCHEMAS 11장](../SCHEMAS.md) |
| P0-03 | 시크릿 로더 | 운영은 Credential Manager만. `.env`는 `dev_mode=true`에서만 허용하고 `secrets.dev_fallback` 이벤트 기록. 읽는 즉시 마스킹 등록 | — |
| P0-04 | 공통 타입 | `Clock`·`Sleeper`·`RandomSource` 주입, `<prefix>_<ULID>` ID, `RequestContext`·`CancelToken`, 예외 계층, `canonical_json`·`args_hash` | [DESIGN 6장](../DESIGN.md) |
| P0-05 | 데이터 트리와 SQLite | `bootstrap.py` 멱등 실행, DDL 적용, FTS5 `trigram` 부재 시 `ConfigError`, 트리거 6개 생성, 상태 전이 후 `integrity-check` 통과 | [SCHEMAS 5장](../SCHEMAS.md) |
| P0-06 | 이벤트·마스킹 | 이벤트 봉투, append → flush → fsync, 기록 전 마스킹 통과, `app.start`/`app.stop`/`error`/`recovery.*` | [SCHEMAS 2.1](../SCHEMAS.md) |
| P0-07 | 원자적 쓰기·복구·단일 인스턴스 | `write_atomic`(tmp → fsync → `os.replace`), 시작 시 `*.tmp`·깨진 꼬리를 `state/quarantine`으로 격리, `msvcrt.locking` 락, 두 번째 인스턴스는 종료 코드 1 | [DESIGN 11장](../DESIGN.md) |
| P0-08 | CLI와 조립 | `wiring.py` 한 곳에서 조립, `/help`·`/bye`·echo, Ctrl+C는 종료 코드 130, 스택 트레이스는 개발 모드에서만 | — |

**권장 커밋 경계**: (1) pyproject·lock·gitignore → (2) config → (3) core 타입 →
(4) bootstrap·DDL → (5) telemetry·마스킹 → (6) atomic·복구·single instance → (7) CLI·wiring

**완료 게이트**: `python scripts\gate.py --phase 0`

- 종료 코드 0
- example 설정 3개 정상 로드 / `default: allow`와 알 수 없는 키 거부
- 테스트 로그에 시크릿 원문 0건
- bootstrap 두 번 실행해도 기존 설정 미덮어씀
- 두 번째 인스턴스 거부 / 부분 파일 격리와 `recovery.result` 기록
- SQLite DDL·트리거 적용, FTS `integrity-check` 통과
- `budget.on_exceed` 변경 시 실행 거부

**하지 않는 것**: 실제 LLM·검색 호출, 기억 검색, PC 도구, 음성·트레이 UI

**이 Phase가 열어주는 것**: 이후 모든 Phase가 쓰는 저장·로그·복구·조립 지점

---

### Phase 1 — 대화와 raw 저장 · [README](./phase-01-chat/README.md) · [세부](./phase-01-chat/DETAIL.md)

**목표**: 로컬 Ollama로 멀티턴 대화. 사용자 입력을 **모델 호출 전에** 저장하고 재시도·비용·
컨텍스트 한도를 통제한다.

**진입 조건**: Phase 0 게이트 0 · [D005](./00-start-here/DECISIONS.md) `decided` ·
`settings.yaml`의 provider·model·digest·pricing이 placeholder가 아님 · Ollama 실행 중이고
`qwen3.5:9b` digest 일치

**한 턴의 고정 흐름**

```text
입력 수신 → ID 생성 → raw user 줄 append+flush → user.input 이벤트
→ loopback·digest 검사 → BudgetGuard 사전 검사 → 프롬프트 조립
→ LLM 호출/제한된 재시도 → llm.response·비용 기록
→ raw assistant 줄 append+flush → 화면 출력
```

저장보다 모델 호출이 먼저 일어나는 구현은 허용하지 않는다.

| ID | 작업 | 핵심 내용 | 계약 |
|----|------|-----------|------|
| P1-01 | LLM 계약과 가짜 클라이언트 | `Message`·`ToolCall`·`LLMUsage`·`LLMResponse`·`LLMClient`. `FakeLLMClient`를 **먼저** 만들어 네트워크 없이 이후 작업을 테스트. tool call은 `LLMBadResponse` | [DESIGN 5.1](../DESIGN.md) |
| P1-02 | Ollama 클라이언트 | base URL은 `http://127.0.0.1:11434`만 허용. 연결 실패·timeout·5xx만 지수 backoff+jitter 재시도, 잘못된 요청·digest 불일치는 재시도 금지. `llm.request`/`llm.retry`/`llm.response` 기록 | — |
| P1-03 | 세션과 raw 로그 | `sessions` 행 생성, raw JSONL 기록, 깨진 꼬리 분리. `/clear`는 프롬프트만 비우고 감사 기록은 보존 | [SCHEMAS 4장](../SCHEMAS.md) |
| P1-04 | 프롬프트와 컨텍스트 예산 | `system_core.md`에 한국어 응답·추측 금지·검색 전 단정 금지. 최근 3턴 유지, 상한 초과 시 오래된 턴부터 압축, 입력 자체가 한도 초과면 호출하지 않음 | [DESIGN 7.1](../DESIGN.md) |
| P1-05 | 비용 예산 | `BudgetGuard`. 금액은 `Decimal` 계산·문자열 저장. 요청 전 최악 비용 검사, 80% 세션당 1회 경고, 100%에서 신규 요청 차단, `/budget` | [DESIGN 12장](../DESIGN.md) |
| P1-06 | 대화 오케스트레이터와 CLI | 도구 없는 `handle_turn`, 취소 토큰 확인, 오류를 사용자 메시지로 변환, 명령 디스패처 분리 | — |
| P1-07 | 크래시·재시도 테스트 | 5개 종료 지점 × 4회. 강제 종료 후 입력 유실 0건, 주입한 sleeper로 backoff 검증, 운영 모드에서 kill hook 무효 | [TESTING 8장](../TESTING.md) |

**필수 이벤트**: `session.start`/`session.end`, `user.input`, `llm.request`/`llm.retry`/`llm.response`,
`budget.warn`/`budget.stop`, `error`

**완료 게이트**: `python scripts\gate.py --phase 1`

- 멀티턴 문맥 유지 / Ollama 오류가 사용자 메시지와 이벤트에 기록
- 20회 강제 종료에서 입력 유실 0건 / 무한 재시도 없음
- 컨텍스트 압축 후 최근 턴 유지 / 예산 100%에서 신규 요청 차단
- 실제 모델 3턴 스모크 성공, GPU 적재, 비용 USD 0.00
- loopback 외 외부 HTTP 0건

**하지 않는 것**: 장기 기억 주입, 웹 검색·도구 호출, 자동 fact 생성

---

### Phase 2 — 장기 기억과 세션 복구 · [README](./phase-02-memory/README.md) · [세부](./phase-02-memory/DETAIL.md)

**목표**: 명시적 기억·교정·세션 요약 후보를 SQLite에 저장하고 다음 세션에서 검색한다.
사용자가 생성 이유를 확인하고 수정·삭제·내보낼 수 있어야 한다.

**진입 조건**: Phase 1 게이트 0 · raw에서 세션 재구성 가능 · SQLite `integrity_check` 통과 ·
`FakeLLMClient`로 요약 스크립트 가능

**기억 lifecycle**

```text
Summarizer → candidate → 사용자 confirm → confirmed
candidate → reject → deleted
confirmed → correction → superseded + 새 confirmed correction
confirmed/candidate → /forget → deleted
```

자동 confidence는 정렬·표시용이며 **절대로 확정 조건이 아니다**.

| ID | 작업 | 핵심 내용 | 계약 |
|----|------|-----------|------|
| P2-01 | 모델과 DB 저장소 | `MemoryStore` 계약, WAL·synchronous FULL·foreign keys·busy timeout, `put_record` ID 기준 멱등, 같은 key의 confirmed 하나 제약을 트랜잭션과 인덱스로 이중 보장 | [DESIGN 5.2](../DESIGN.md), [SCHEMAS 5장](../SCHEMAS.md) |
| P2-02 | FTS와 검색 랭킹 | 시작 시 FTS5 trigram 검사, key exact + FTS 후보 수집(임베딩 비활성), 가중치·반감기·tie-break를 순수 함수로, deleted·superseded 제외 | [DESIGN 8장](../DESIGN.md) |
| P2-03 | 명시적 기억과 교정 | `기억해:`, `틀림: A → B`, `/memory` 하위 명령(`list`·`confirm`·`edit`·`export`), `/forget`. key를 확실히 못 찾으면 저장하지 말고 되묻는다 | [SCHEMAS 6장](../SCHEMAS.md) |
| P2-04 | 세션 요약 | `/bye`에서 raw 유효 줄을 Privacy Gate 통과 후 Summarizer로. fact는 전부 candidate, 각 candidate에 `evidence_turn_ids` 필수. 구조 위반 시 세션 종료를 실패시키지 말고 `session.summary_failed` 기록 | [SCHEMAS 7장](../SCHEMAS.md) |
| P2-05 | 프롬프트 기억 주입 | confirmed 검색 후 주입, candidate는 별도 블록에 미확정 명시, 예산 초과 시 낮은 점수부터 제외, 주입 ID를 `llm.request.memory_record_ids`에 기록 | — |
| P2-06 | 체크포인트와 시작 복구 | N턴마다 `session_checkpoints` 커밋. 시작 시 tmp/quarantine → DB integrity → 미완료 세션 → running task 순 검사. `prompt`/`auto`/`discard` 정책 | — |
| P2-07 | 삭제·인덱스 일관성 | `/forget`은 한 트랜잭션에서 상태 변경 + tombstone + FTS 제거 + 임베딩 제거 + `memory.delete`. 실패 시 전체 rollback | — |

**완료 게이트**: `python scripts\gate.py --phase 2` + `--report`

- 기억 질의 정확도 90% 이상 (`memory_eval.jsonl`)
- candidate/confirmed/superseded/deleted 전이 통과
- correction이 다른 key 순위에 영향 없음
- `/forget` 후 본문·FTS·embedding에서 제외
- 크래시 세션 복구 후 candidate 생성 가능

**하지 않는 것**: 웹·문서 RAG, 임베딩 활성화, 자동 fact 확정, 다중 사용자 프로필

---

### Phase 3 — 검색과 근거 · [README](./phase-03-research/README.md) · [세부](./phase-03-research/DETAIL.md)

> ★ **이 Phase 완료가 MVP 경계다.**

**목표**: 모델의 기억만으로 답하지 않고 웹·로컬 문서에서 근거를 찾는다. 외부 텍스트는 항상
신뢰할 수 없는 데이터로 취급하고, 핵심 주장에 출처와 확인 날짜를 붙인다.

**진입 조건**: Phase 2 게이트 0 + 기억 정확도 90% 이상 · [D006](./00-start-here/DECISIONS.md)
`decided` · `privacy.yaml` 문서 전송 등급 검토 · D012가 `pending`이면 `.md`·`.txt`만 지원

| ID | 작업 | 핵심 내용 | 계약 |
|----|------|-----------|------|
| P3-01 | Privacy Gate 완성 | 탐지기 컴파일, 잘못된 정규식은 시작 시 거부. `for_api`·`for_log`·`for_tts`·`for_memory_write`를 독립 경로로. Finding에 원문 미저장. **`secret`은 사용자가 승인해도 외부 전송 금지** | [DESIGN 5.3](../DESIGN.md) |
| P3-02 | 도구 공통 계약과 레지스트리 | `ToolSpec`·`ToolResult`·`Tool`. 현재 Phase 이하 + enabled만 등록. `additionalProperties=false`·required·길이 제한 검사. LLM에는 이름·설명·인자 스키마만 노출하고 risk·capability·실제 경로는 숨김. 검색 결과는 항상 `untrusted=true` | — |
| P3-03 | 로컬 문서 인덱싱 | 허용 확장자·최대 크기, canonical path가 docs root 아래인지 확인, `content_hash` 변경분만 재색인, chunk `start_char`/`end_char`/ordinal, 문서·chunk·FTS를 한 트랜잭션으로. PDF parser 미정이면 `.pdf`를 제거하고 "지원하지 않는 형식"을 명시 | — |
| P3-04 | 문서 검색 | FTS 상위 후보, 과도한 chunk 병합, chunk 수·토큰 예산 적용, 결과에 파일명·상대 경로·chunk ID·문자 범위·transfer class 포함. `local_only` 본문은 외부 프롬프트에 미포함 | — |
| P3-05 | 웹 검색 제공자 | query를 `for_external_text(purpose="search_query")` 통과 후 전송. `SearchHit`에 title·URL·snippet·published_at·fetched_at. 요청 전 `BudgetGuard.check`, 성공 후 `record_charge`. **검색 오류를 빈 성공으로 위장 금지**. 자동 테스트는 `FakeSearchProvider`만 | — |
| P3-06 | 안전한 fetcher | http/https만, 자격증명 URL·loopback·사설/link-local IP·`.local`·장치 스킴 차단, DNS 해석 전후 IP 모두 검사(rebinding 완화), redirect마다 재검증 최대 3회, 헤더와 누적 크기 모두 2MB, Content-Type 확인, 비본문 제거 후 `untrusted_content` 봉투 | — |
| P3-07 | 신뢰 경계와 프롬프트 | 본문 안의 봉투 종료 태그 이스케이프, 외부 본문에서 나온 URL·경로·명령을 도구 인자로 자동 승격 금지, 현재 요청과 무관한 부작용 도구 call 거부 | [SCHEMAS 9장](../SCHEMAS.md) |
| P3-08 | 근거 응답 조립 | 주장마다 실제로 뒷받침하는 근거 ID. 독립 출처 2개 미만이면 `근거 부족`, 출처 충돌이면 양쪽 표시 후 `상충`. 검색 실패와 결과 0건을 구분 | — |

**응답 최소 형식**

```text
핵심 요약
- 주장 A [1]
- 주장 B [2]

근거
[1] 제목 — URL 또는 파일명 (YYYY-MM-DD 확인)
[2] 제목 — URL 또는 파일명 (YYYY-MM-DD 확인)

상태: 확실 | 상충 | 근거 부족
```

**2026-08-11 보안 검토 반영**: redirect 자동 추적 금지(매 단계 재검사), DNS 검사에서 허용한
IP를 소켓 연결에 고정, 신뢰도는 청크 수가 아니라 정규화 URL·`doc_id`의 독립 개수로 계산,
독립 출처 2개 미만이면 `확실`을 `근거 부족`으로 강등.

**완료 게이트**: `python scripts\gate.py --phase 3`

- Phase 3·security 테스트 통과 / prompt injection 코퍼스 전부 차단
- `local_only` 외부 전송 0건 / 검색형 핵심 주장 근거 표기
- 웹·문서 검색 실패 처리 구분 / MVP 데모 20회 연속 성공(수동)

**하지 않는 것**: 파일 쓰기 도구, 검색 결과가 지시한 행동 자동 실행, 임베딩 필수화

---

### Phase 4 — 안전한 PC 도구 · [README](./phase-04-tools/README.md) · [세부](./phase-04-tools/DETAIL.md)

**목표**: 화이트리스트에 등록된 앱·폴더·URL·텍스트 파일 생성만 수행한다. LLM 출력은 실행
요청일 뿐이며 스키마 검증 → 정규화 → 정책 판정 → 승인 → 감사 기록을 모두 통과해야 한다.

**진입 조건**: Phase 3 게이트 0 · 검색 도구 registry 안정화 · `tools.yaml`의 실제 앱 경로와
sandbox root를 사용자가 검토 · 미등록 도구가 LLM 스키마에 미노출

**실행 파이프라인**

```text
LLM ToolCall → registry 조회 → JSON Schema 검증
→ SafetyGate 정규화·위험도 판정 → 필요 시 승인 대기로 TurnOutcome 반환
→ 승인 ticket 발급 → 실행 직전 재평가·args_hash 비교·ticket 소진
→ audit intent flush → 제한된 실행 → audit result flush → ToolResult
```

승인 UI와 실행 코드를 직접 연결하지 않는다. 승인 대기는 값으로 저장하고 오케스트레이터가
재개한다.

| ID | 작업 | 핵심 내용 | 계약 |
|----|------|-----------|------|
| P4-01 | 경로 정규화 | 설정 경로 함수와 도구 인자 경로 함수를 분리. 도구는 root enum + relative path만 수용. 환경 변수·절대 경로·UNC·장치 경로·NTFS ADS·Windows 예약어·끝 공백/점 거부. **중간 요소마다** reparse point 검사, `commonpath` 대소문자 무시 비교 | [DESIGN 11.4](../DESIGN.md) |
| P4-02 | Safety Gate | `Verdict` 구현, normalized args에서 정책 엔진이 display 생성, 기본 risk + 조건별 escalation 합산, forbidden은 승인과 무관하게 deny, `interactive=false`에서 승인 필요 작업은 `ApprovalRequired` | [DESIGN 5.4](../DESIGN.md) |
| P4-03 | 승인 ticket | request·tool·args hash·risk·channel·TTL 결합, 1회용이며 프로세스 재시작 시 자동 무효, medium은 y/n·high는 고정 문구 입력, **voice channel은 high ticket 발급 불가**, 실행 직전 재정규화 후 hash 비교 | — |
| P4-04 | 감사 로그 | intent/result/denied 레코드. intent를 **실행 전에** flush. 단조 seq + 이전 entry hash로 날짜 파일 연결. 실행 전에 끝난 요청도 `phase="denied"` 한 줄과 `cause`. 일반 대화 내용은 미포함 | [SCHEMAS 3장](../SCHEMAS.md) |
| P4-05 | Secure Tool Runner | Phase 3에서 전용 경로로 돌던 `web_search`·`doc_search`·`fetch_url`을 Runner로 이관(실행 경로가 둘이면 정책·감사가 한쪽만 적용). `shell=True`·`os.system`·문자열 명령 조립 금지. 최소 환경 변수와 고정 cwd. `managed_process`는 Job Object로 자식 트리 묶고 timeout에 전체 종료, `detached_allowlisted`는 PID 기록 후 유지 | [DESIGN 5.6](../DESIGN.md) |
| P4-06 | 개별 도구 | `open_app`(low), `open_folder`(low), `open_url`(low/medium), `create_file`(신규 medium / overwrite high). 실패를 성공 메시지로 바꾸지 않는다 | [SCHEMAS 8장](../SCHEMAS.md) |
| P4-07 | CLI 승인 흐름 | `pending_approval` display 그대로 표시, 거부 시 `approval.deny` 후 미실행 종료, 승인 시 ticket을 `resume_after_approval`로 전달, 대기 중 새 입력·Ctrl+C·timeout은 ticket 폐기 | — |

**2026-08-11 보안 검토 반영**: `typed_confirm`은 `user_typed_phrase` 방식으로만 ticket 발급.
감사 로그의 `normalized_args`와 표시값은 로그용 마스킹을 거치되, 실제 변경 경로는 조사
가능성을 위해 원문 유지.

**완료 게이트**: `python scripts\gate.py --phase 4` + `pytest -m "phase4 and security"`

- 허용 앱·폴더 작업 성공 / 비허용 요청 거부와 이유 표시
- medium/high 승인 동작 구분 / 승인 화면과 실제 인자 불일치 실행 0건
- audit intent·result 모두 존재하고 체인 연결
- timeout 후 프로세스 트리 잔존 0건

**하지 않는 것**: 삭제·포맷·임의 셸·레지스트리·다운로드, `run_skill` 활성화, 한 요청에서
여러 도구 연쇄, UI가 정책 판정을 우회하는 예외 경로

---

### Phase 5 — 멀티스텝 에이전트 · [README](./phase-05-agent/README.md) · [세부](./phase-05-agent/DETAIL.md)

**목표**: 검색 → 요약 → 파일 저장 → 폴더 열기처럼 여러 도구를 순서대로 실행한다. 각 단계는
저장·복구 가능해야 하고, 부작용 작업이 재시작 후 중복 실행되지 않아야 한다.

**진입 조건**: Phase 4 보안 테스트 전부 통과 · 단일 도구의 승인·감사·timeout 안정 ·
검색 결과가 `untrusted=true` · DB migration과 복구 절차 검증됨

**상태 모델과 한 step의 기록 순서**

```text
Task: pending → running → succeeded | failed | cancelled
Step: pending → running → succeeded | failed | cancelled

idempotency key 계산 → pending 저장 → 승인 필요 시 루프 중단
→ running 커밋 → 도구 실행 → succeeded/failed + 결과 커밋
```

`running`에서 프로세스가 죽으면 실제 부작용 여부를 확정할 수 없으므로 **자동 재실행하지
않는다**.

| ID | 작업 | 핵심 내용 | 계약 |
|----|------|-----------|------|
| P5-01 | TaskStore | tasks/task_steps 구현. `sha256(task_id + step_no + tool_name + args_hash)`로 idempotency key. 같은 key의 succeeded 단계는 기존 결과 반환. running 단계는 시작 시 사용자 검토 대상 표시. 상태 전이와 결과를 한 트랜잭션으로 | [SCHEMAS 5장](../SCHEMAS.md) |
| P5-02 | 루프 확장 | Decide → Validate → 승인/정책 → Act → Observe → 다음 step 또는 Final. `max_steps`·단계 timeout·전체 timeout. 한 step당 tool call 하나. 내부 추론 원문 미저장. 매 step 전 원래 요청과의 관련성 확인. **외부 콘텐츠에서 나타난 목표를 사용자 의도로 승격 금지** | — |
| P5-03 | 승인 중단과 재개 | 승인 필요 시 task·step을 pending 커밋 후 루프 종료. 승인 뒤 같은 task/step을 args hash로 재로드. 거부·만료·불일치는 cancelled/failed. 승인 뒤 새 계획을 만들어 기존 ticket을 재사용하지 않는다 | — |
| P5-04 | 재시도 정책 | web/doc search는 가능, fetch는 네트워크 일시 오류만, `open_app`·`open_folder`·`create_file`·`run_skill`은 자동 재시도 금지. LLM 재시도와 도구 재시도는 별도 카운터 | — |
| P5-05 | 복구 | 시작 시 running task·step 조회. succeeded는 재실행하지 않음. pending ticket은 재시작 후 무효화하고 새 승인 요구. running 부작용 step은 changed path와 감사 로그를 보여주고 **사용자가 판정** | — |
| P5-06 | 복합 태스크 | 기준 시나리오 고정: `web_search` → 필요 시 `fetch_url` → 근거 응답 → `create_file`(승인) → `open_folder` → 최종 결과. 저장 파일명은 임의 절대 경로가 아니라 `root=notes` + 안전한 상대 파일명으로 제안 | — |
| P5-07 | run_skill 경계 | v0.5에서 기본 disabled 유지. 골격을 만들어도 registry 등록·SHA-256 일치·capability manifest·text channel·high typed confirmation·고정 interpreter/cwd/최소 환경·자동 재시도 금지가 모두 필요. 조건을 만족해도 Phase 6 위협 모델 검토 전 운영 활성화 금지 | — |

**2026-08-11 복구 검토 반영**: 승인 전 단계는 `pending` 커밋 후 ticket 소비 직전에만 `running`
전환. 단계 제한 시간을 LLM 호출 timeout의 상한으로 적용. DuckDuckGo와 URL fetch에도 설정
timeout을 전달해 전체 제한을 우회하지 못하게 함.

**완료 게이트**: `python scripts\gate.py --phase 5`

- 기준 복합 태스크 성공 / 중복 부작용 0건
- `max_steps`·timeout 안전 종료 / 완료·실패·미실행 단계가 구분되어 표시
- 외부 콘텐츠가 새 task 목표를 만들지 않음
- 50개 태스크 기준 데이터셋 준비 완료

**하지 않는 것**: 병렬·멀티 에이전트, 승인 없는 백그라운드 부작용, running step 자동 재실행,
LLM 내부 추론 원문 저장

---

### Phase 6 — 보안 게이트 · [README](./phase-06-security/README.md) · [세부](./phase-06-security/DETAIL.md)

> ★ **v0.5 릴리스 게이트. 새 기능을 추가하지 않는다.**

**목표**: Phase 0~5의 신뢰 경계·도구·복구·백업을 공격 관점에서 검증한다. Critical/High 결함
0건과 **실제 복원 성공**이 출시 조건이다.

**진입 조건**: Phase 0~5 게이트 0 · `tasks_eval.jsonl` 50건 준비 ·
[D007·D008](./00-start-here/DECISIONS.md) 확정 · 백업 대상이 별도 물리 장치 또는 보안 위치 ·
`run_skill` disabled

| ID | 작업 | 핵심 내용 |
|----|------|-----------|
| P6-01 | 위협 모델 검토 | [위협 모델](./reference/THREAT_MODEL.md)의 자산·경계·시나리오를 코드와 연결. 각 위협에 예방 통제·탐지 통제·테스트·잔여 위험. **테스트 없는 High 위협은 릴리스 차단** |
| P6-02 | 보안 코퍼스 완성 | prompt injection·envelope escape·memory exfiltration 확장. path 코퍼스에 인코딩·대소문자·8.3 short name·ADS·UNC·장치 경로. URL 코퍼스에 IPv4 변형·IPv6·redirect-to-private·mixed-script IDN. ticket 만료·재사용·도구명 변경·args 변경 검증 |
| P6-03 | 시크릿 유출 매트릭스 | 같은 테스트 시크릿을 LLM 메시지·검색 query·events/raw/audit·memory·TTS·예외 traceback·백업 산출물에 넣고 원문 0건 검증. 탐지기의 false positive/negative 샘플도 기록 |
| P6-04 | 감사 로그 검증기 | 날짜 파일을 seq 순서로 읽고 파일 경계에서도 prev hash 연결 확인. canonical JSON으로 entry hash 재계산. 누락·중복 seq·변조 line·깨진 마지막 줄을 구분 보고. **검증은 로그를 수정하지 않는다** (`gate.py --verify-audit`) |
| P6-05 | 백업 | SQLite online backup API로 일관된 사본 → raw·config staging 복사 → manifest에 경로·크기·SHA-256·schema version → 암호화 → 별도 target 복사 → target hash 재검증 → 평문 staging 안전 삭제 → `backup.result`. 백업 암호는 Credential Manager에서만 읽는다 |
| P6-06 | 복원 | **운영 루트 위에 바로 복원하지 않는다.** 빈 target 확인 → 복호화 후 manifest hash → SQLite integrity → schema version 및 migration 사전 보고 → raw 유효성 → 설정 시크릿이 백업에 없는지 확인 → 테스트 모드 앱으로 기억 검색 1회 → 성공 후에만 완료 보고 |
| P6-07 | 공급망·설정 검토 | lockfile hash 설치 재현, 미사용 의존성 제거, 모든 example 설정을 운영 모델로 로드, `dev_mode=false`에서 `.env`·kill hook·live test hook 비활성 확인, tools default deny와 forbidden 변경 불가 확인, 설정·프롬프트·schema version을 릴리스 manifest에 기록 |
| P6-08 | 정량 게이트 | `pytest -m "not allow_network"` + `--verify-audit` + `--report` + 빈 target 복원. 50개 복합 태스크 중 95% 이상, 금지 동작 0건, 중복 부작용 0건 |

**결함 등급**

| 등급 | 예 | 릴리스 처리 |
|------|----|-------------|
| Critical | 승인 없이 forbidden 실행, 시크릿 외부 전송 | 즉시 차단 |
| High | sandbox 우회, ticket 재사용, 복원 불가 | 차단 |
| Medium | 오류 메시지 부족, 우회 불가한 DoS | 수정 계획과 기한 필요 |
| Low | 문서·표시 문제 | backlog 가능 |

**완료 게이트**

- slow 포함 전체 pytest 통과 / Critical·High 0건
- 위협 모델의 모든 High 행에 테스트 연결
- 감사 체인 변조 탐지 성공 / 별도 target 복원 후 기억 검색 성공
- 복합 태스크 50건 95% 이상 / v0.5 릴리스 manifest 작성

**하지 않는 것**: 보안 테스트 통과를 위한 기능 삭제 은폐, 운영 루트 직접 복원, 평문 백업 보존,
Medium/High 결함의 무문서 예외 처리

---

### Phase 7 — 음성 입출력 · [README](./phase-07-voice/README.md) · [세부](./phase-07-voice/DETAIL.md)

**목표**: 명시적으로 시작한 `--voice` 모드에서 로컬 웨이크워드 "자비스"로 한국어 음성 대화를
시작하고 짧은 응답을 안전하게 낭독한다. 기존 Orchestrator를 재사용하며 **음성 경로가 승인
정책을 약화시키지 않게** 한다.

> 사용자 요청으로 Phase 1 직후 로컬 음성 세로 기능을 먼저 구현했다. 이는 Phase 7 정식 완료를
> 뜻하지 않는다. Phase 2~6과 음성 승인 정책을 마친 뒤 전체 게이트를 다시 수행한다.

**진입 조건**: v0.5/Phase 6 게이트 통과 · [D009](./00-start-here/DECISIONS.md) TTS 확정 ·
[D016](./00-start-here/DECISIONS.md) STT 모델·오디오 장치 사전 확인 · text channel에서 Phase
4~5가 안정 동작

**상태 흐름**

```text
Idle → WakeListening → "무엇을 도와드릴까요." → Recording
→ Transcribing → Orchestrator(text, channel=voice)
→ Speaking 또는 ApprovalWaiting → Idle
              └─ Speaking 중 "자비스" → TTS cancel → 안내 → Recording
```

동시에 녹음과 TTS를 수행하지 않는다. 녹음 중 TTS가 시작되면 자기 출력을 다시 입력으로 듣는
루프가 생긴다.

| ID | 작업 | 핵심 내용 |
|----|------|-----------|
| P7-01 | 음성 계약 | `AudioFrame`·`Transcript`·`STTEngine`·`TTSEngine`. mono PCM, sample rate·dtype 명시. 빈 음성·너무 짧은 음성·timeout을 정상 실패로 구분. 엔진 타입은 `voice` 모듈 밖으로 미노출 |
| P7-02 | 웨이크워드 controller와 PTT | `--voice`에서만 마이크 개방. **호출 전 PCM은 제한된 메모리 버퍼에만 두고 디스크·API에 저장하지 않는다.** 호출 시 정확히 "무엇을 도와드릴까요." 재생 후 녹음. 최대 녹음 시간·무음 제한. 녹음 중임을 상태와 UI 이벤트로 즉시 알림. 장치 오류 시에도 text UI 유지 |
| P7-03 | STT | 호출어는 `vosk-model-small-ko-0.22`를 SHA-256 검증 후 CPU 제한 문법으로. 질문은 고정 revision `Systran/faster-whisper-small`로 `language="ko"`·`beam_size=5`·VAD. CUDA `int8_float16` 우선, 실패 시 CPU `int8` 폴백을 화면에 명시. 빈 결과·낮은 log probability·높은 no-speech probability는 인식 실패로 분류해 LLM에 전달하지 않음. raw 저장 전 Privacy Gate 적용. 세부는 [VOICE_STT](./reference/VOICE_STT.md) |
| P7-04 | Orchestrator 연결 | Transcript를 기존 `handle_turn`에 전달, `RequestContext.channel="voice"`를 정책 엔진까지 유지. 인식 결과를 먼저 표시해 취소 기회 제공. low는 text와 동일 결과. **high는 음성으로 승인 불가하고 화면 typed confirmation으로 전환** |
| P7-05 | TTS | 최종 답변만 낭독하고 tool 원문·감사 로그·승인 token은 읽지 않음. 모든 문자열이 `for_tts` 통과. secret/pii_high는 화면 전용 fallback 문장. 최대 글자 수 초과 시 요약만 낭독. Windows SAPI `Microsoft Heami Desktop` 고정(`rate=4`, 약 1.55배), 온라인 TTS 폴백 없음. [D017](./00-start-here/DECISIONS.md) 게이트와 [D018](./00-start-here/DECISIONS.md) 한 문장 명령·중단 핫키 적용 |
| P7-06 | 자원 관리 | Vosk 호출어는 CPU, Whisper small은 질문 처리 중에만 GPU. 녹음 buffer 상한. 장시간 idle이면 선택적 모델 unload |

**완료 게이트**: `python scripts\gate.py --phase 7`

- 음성으로 허용 앱 실행 성공 / text·voice 결과 동등성 통과
- 음성 High 승인 0건 / 민감정보 낭독 0건
- PTT 종료 후 STT p95 목표 측정 / 장치 오류 후 text UI 사용 가능

**하지 않는 것**: OS 로그인 자동 시작과 사용자 모르게 마이크 열기, 음성 생체 인증, 음성만으로
High 승인, 긴 문서 전체 낭독

---

### Phase 8 — 상주 UI와 패키징 · [README](./phase-08-resident-ui/README.md) · [세부](./phase-08-resident-ui/DETAIL.md)

> ★ **v1 후보.**

**목표**: 터미널을 직접 열지 않고 트레이·전역 단축키로 호출한다. 승인 대기와 마이크 상태를
숨기지 않고, Windows 재시작 뒤에도 데이터 손상 없이 복구 상태를 표시한다.

**진입 조건**: Phase 7 게이트 통과 · [D013~D015](./00-start-here/DECISIONS.md) 확정 ·
CLI 경로에서 모든 기능·승인·복구 동작 · UI가 Orchestrator 내부를 직접 호출하지 않음

**UI 상태 머신**

```text
Starting → Idle
Idle → Listening → Transcribing → Thinking
Thinking → ApprovalWaiting | Acting | ShowingResult | Error
ApprovalWaiting → Acting | Idle
Acting → Thinking | ShowingResult | Error
ShowingResult → Idle
Error → Idle | ShuttingDown
```

허용되지 않은 전이는 로그를 남기고 무시한다. 동일 시점의 상태는 하나만 존재한다.

| ID | 작업 | 핵심 내용 |
|----|------|-----------|
| P8-01 | UI 계약과 이벤트 브리지 | `TurnOutcome`과 voice controller 상태를 UI event로 변환. **UI는 LLM·MemoryStore·ToolRunner를 직접 import하지 않는다.** 승인 요청에는 Verdict display와 risk만 전달. UI thread와 작업 thread 사이는 thread-safe queue |
| P8-02 | 트레이 | 열기·PTT 시작/중지·현재 상태·미완료 task 확인·자동 시작 설정·로그 폴더 열기·종료. 아이콘이 사라져도 백그라운드 프로세스가 유령으로 남지 않게 |
| P8-03 | 전역 단축키 | 기본 단축키 충돌 감지. 등록 실패 시 앱을 종료하지 않고 설정에서 변경 요청. 두 번째 인스턴스는 재등록 불가. 키 반복 debounce. text 창 호출과 PTT 단축키 구분 |
| P8-04 | 승인 UI | medium/high 위험·정확한 대상·예상 변경·만료 시간 표시. display는 Safety Gate가 만든 값 그대로. high는 typed phrase만 수용. 창 닫기·timeout·새 요청은 거부 처리. **승인 창을 background notification으로 대체하지 않는다** |
| P8-05 | 복구·알림 | 시작 시 recovery가 끝날 때까지 일반 입력을 받지 않음. 미완료 session/task/running step 구분 표시. 완료 알림에 민감한 결과 본문 미포함. 오류 알림은 user_message만 보여주고 상세는 로그 링크. 마이크 indicator는 트레이와 입력 창 양쪽에 |
| P8-06 | 자동 시작 | 사용자 opt-in이며 agent tool이 아니라 설치/UI 설정 기능. 레지스트리 직접 수정 금지. enable/disable 대칭 제공. 제거 시 자동 시작 항목도 제거. 자동 시작 실패가 수동 실행을 막지 않음 |
| P8-07 | 패키징 | `scripts/build.ps1` 한 명령으로 재현 가능한 빌드. 앱·schema·prompt·설정 template version을 manifest에. **시크릿·운영 설정·운영 DB·raw 로그는 패키지에 미포함.** 새 Windows 프로필에서 bootstrap부터 테스트. 기존 데이터는 덮어쓰지 않고 migration. rollback 시 DB schema 호환 여부 선검사 |

**완료 게이트**: `python scripts\gate.py --phase 8` + `pytest tests\slow\test_packaged_bootstrap.py`

- 단축키로 입력 창·PTT 호출 / 단일 인스턴스·중복 단축키 차단
- 마이크 상태 항상 표시 / 승인 상태와 실제 실행 상태 일치
- Windows 재시작 뒤 복구 목록 표시 / 패키징된 앱에서 bootstrap·migration 성공
- v1 후보 manifest 작성

**하지 않는 것**: 화면 비전 기반 임의 클릭, 숨겨진 상시 녹음, UI 전용 정책 예외, 운영 데이터를
설치 패키지에 포함

---

### 운영과 릴리스 · [README](./operations/README.md) · [세부](./operations/DETAIL.md)

> ★ **7일 안정화 통과가 v1 릴리스다.**

**운영 원칙**

- 운영 DB·raw·설정은 Git과 설치 패키지에 넣지 않는다.
- 문제가 생기면 쓰기를 멈추고 원본을 보존한 뒤 **복사본에서** 조사한다.
- DB integrity 또는 감사 체인이 실패하면 PC 도구를 비활성화한다.
- 백업 성공이 아니라 **복원 성공**을 기준으로 본다.
- 시크릿 노출이 의심되면 로그 삭제보다 **키 폐기를 먼저** 한다.

**정기 점검 주기**

| 주기 | 명령 | 확인 |
|------|------|------|
| 매일 | `python scripts\gate.py --integrity` | DB integrity, 미완료 task, 감사 체인, 예산 80% 경고, retention, 최근 error |
| 매주 | `python scripts\backup.py create` | 암호화 archive, 별도 target 복사와 hash, 보존 개수, 평문 staging 잔여 0건 |
| 매월 | `python scripts\backup.py restore --archive <latest> --target <empty>` | 새 경로 복원, integrity, 기억 검색 1회, 설정 로드, raw 유효성 |

**장애 대응 요약**

| 증상 | 첫 행동 |
|------|---------|
| 설정 오류 (종료 코드 2) | 사용자 설정 보존 후 example과 키·schema version 비교. `default: deny` 완화로 우회하지 않는다 |
| SQLite integrity 실패 (종료 코드 5) | 앱·자동 시작 중단 → 손상 DB를 읽기 전용 사본으로 보존 → 최신 백업을 새 target에 복원 |
| 감사 체인 실패 | PC 도구를 전부 disabled로 시작 → 끊긴 seq 전후 파일 보존 → 원인 규명 전 v0.5 기능 재활성화 금지 |
| running step 발견 | task·tool·args·intent 로그·changed paths 표시. **자동 재실행하지 않고** 사용자가 마감 판정 |
| 시크릿 노출 의심 | 키 폐기·재발급 먼저 → 도구·외부 전송 비활성화 → 로그 조사 → 재현 테스트 추가 후 재활성화 |

**릴리스 체크리스트**

| v0.5 | v1 |
|------|-----|
| Phase 0~6 전체 게이트 통과 | v0.5 체크리스트 유지 |
| Critical/High 0건 | Phase 7~8 게이트 통과 |
| 복합 태스크 50건 95% 이상 | 깨끗한 Windows 프로필 설치 성공 |
| 암호화 백업·새 경로 복원 성공 | 마이크 indicator·음성 High 차단 확인 |
| 감사 체인 검증 성공 | 재시작 복구·단축키 충돌 테스트 |
| `run_skill` 활성 여부와 근거 기록 | 7일간 매일 integrity 기록 |
| 버전 manifest 보관 | 데이터 손상·금지 동작·시크릿 유출 0건 |

---

### Post-v1 — 선택 고도화 · [README](./post-v1/README.md) · [세부](./post-v1/DETAIL.md)

v1의 7일 안정화가 끝나기 전에는 시작하지 않는다. 아래를 **한 릴리스에 묶지 않고** 각각 별도
branch·결정·게이트로 진행한다.

| 후보 | 범위 |
|------|------|
| 로컬 LLM 고도화 | 다중 모델 라우팅·모델 교체·더 큰 문맥. 교체마다 hash·출처·라이선스를 새 결정으로 기록 |
| 임베딩 검색 | 현재 FTS 정확도를 먼저 저장하고, 혼합 시 평가셋 정확도가 실제로 오를 때만 기본 활성화 |
| 외부 서비스 연동 | 캘린더·메일은 읽기 전용부터. 응답은 untrusted content. 쓰기·발송은 별도 High 기능 |
| Wakeword 고도화 | 사용자별 호출어. 호출 전 오디오는 계속 미저장. false activation 장기 테스트 |
| 피드백 통계 | 평가 데이터로만 저장하고 프롬프트·도구 정책을 자동 변경하지 않음 |
| 파인튜닝 | 마지막 선택지. 동의·삭제·익명화·license를 먼저 정의 |

각 제안은 [기능 제안 문서 양식](./post-v1/README.md)을 채우고 결정 ID를 받아야 한다.

---

## 6. 결정 의존 맵

코드가 대신 정할 수 없는 값이다. `pending`인 항목은 해당 Phase를 막는다. 전체 목록과 근거는
[DECISIONS.md](./00-start-here/DECISIONS.md)에 있다.

| Phase | 결정 | 상태 | 미결정 시 영향 |
|-------|------|------|----------------|
| Phase 0 | D001~D004 경로·저장·패키지 관리 | decided | — |
| Phase 1 | D005 LLM 런타임·모델 (Ollama + `qwen3.5:9b`) | decided | 구현 시작 불가였음 |
| Phase 3 | D006 검색 제공자 (DuckDuckGo `ddgs`) | decided | 웹 검색 구현 불가였음 |
| Phase 3 | D012 PDF parser | **pending** | `.pdf` 비활성, `.md`·`.txt`만 지원 |
| Phase 6 | D007 백업 대상 · D008 암호화 도구 | **pending** | v0.5 릴리스 게이트 통과 불가 |
| Phase 7 | D009 TTS · D010 음성 호출 · D016 한국어 STT | decided | — |
| Phase 7 | D017 끼어들기 게이트 · D018 호출·한 문장 명령 | decided | — |
| Phase 8 | D011 상주 시작 (autostart 기본 false) | decided | — |
| Phase 8 | D013 패키징 · D014 트레이·단축키 · D015 자동 시작 방식 | **pending** | Phase 8 구현 시작 불가 |
| 전체 | D019 v2 재구축 데이터 격리 | decided | — |

**지금 막혀 있는 것은 없다.** D007·D008·D012·D013~D015는 해당 Phase 진입 전에 확정하면 된다.

---

## 7. 관련 문서

- [문서 지도](./README.md) — 폴더 색인과 릴리스 경계
- [세부 개발문서 전체 지도](./DETAIL.md) — 배경 설명 모음
- [개발 진행 현황](./PROGRESS.md) — 현재 상태와 게이트 증거
- [결정 기록](./00-start-here/DECISIONS.md) — 미결정 값
- [요구사항 추적표](./reference/TRACEABILITY.md) — 요구 → 설계 → 데이터 → 테스트
- [위협 모델](./reference/THREAT_MODEL.md) — 자산·경계·공격·통제
- [문서 변경 규칙](./reference/DOCUMENTATION_RULES.md) — 어떤 문서를 먼저 고치는가
