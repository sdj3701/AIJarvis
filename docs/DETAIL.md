# 세부 개발문서 — 전체 지도

> 이 문서는 [docs/README.md](./README.md)와 [루트 README](../README.md)의 내용을 배경·이유
> 까지 풀어 쓴 세부 개발문서다. 설명은 게임 개발 용어에 빗대어 쓴다. 인터페이스·설정 키·
> 완료 기준이 어긋나면 **항상 원문이 기준**이다. 실제 구현은 각 폴더의 `README.md`를 보고
> 한다.
>
> 각 폴더에는 같은 이름의 `DETAIL.md`가 하나씩 있다. 원문을 읽기 전에 세부 개발문서를 먼저
> 읽으면 "왜 이런 규칙이 있는지"가 먼저 이해된다.
>
> 작업 ID 단위의 전체 순서와 의존 관계는 [개발 흐름](./DEVELOPMENT_FLOW.md)에 있다.

## 1. 이 프로젝트가 뭘 만드는 건가

내 PC에서만 도는 개인 비서다. 서버도 없고, 클라우드 AI도 안 쓴다.

- 두뇌: 내 PC에 설치한 로컬 AI 모델 (Ollama + `qwen3.5:9b`)
- 기억: 로컬 SQLite 파일 (게임 세이브 DB와 같은 개념)
- 입력: 키보드 + 마이크("자비스" 하고 부르면 깨어남)
- 출력: 화면 텍스트 + 로컬 음성 낭독
- 손발: 화이트리스트에 등록한 앱 실행·폴더 열기·메모 파일 만들기만

즉 **온라인 게임이 아니라, 세이브 데이터를 다루는 싱글 플레이 클라이언트**를 만드는 것에
훨씬 가깝다. 그래서 문서가 저장 안정성·데이터 손상 방지·조작 방지에 집착한다.

## 2. 게임 프로젝트로 번역하면

| 이 프로젝트의 말 | 게임 개발에서 같은 역할 |
|------------------|--------------------------|
| Phase 0 ~ Phase 8 | 수직 슬라이스 마일스톤. "프로토 → 알파 → 베타 → 출시" 순서 |
| 게이트(gate) | 마일스톤 통과 조건. 사람 판단이 아니라 자동 스크립트가 OK/NG 판정 |
| `PLAN.md` | 기획서(GDD). 무엇을 왜 만드는가 |
| `DESIGN.md` | 기술 설계서(TDD). 클래스·인터페이스·의존 방향 |
| `SCHEMAS.md` | 세이브 파일·DB·로그 포맷 명세서 |
| `TESTING.md` | QA 계획서. 무엇을 어떻게 증명하는가 |
| `docs/phase-*/README.md` | 스프린트 작업 티켓 목록 |
| Orchestrator | GameManager. 한 턴의 흐름을 통제하는 중심 루프 |
| Tool | 실제로 월드를 바꾸는 커맨드 핸들러 (파일 생성, 앱 실행) |
| Privacy Gate | 크래시 리포트 전송 전 개인정보 마스킹 필터 |
| Safety Gate | 서버 사이드 검증. "클라이언트(=AI)가 보낸 요청은 못 믿는다" |
| 감사 로그(audit) | 리플레이 로그 + 부정행위 추적 로그 |
| 예산(budget) | 프레임 예산·메모리 버짓과 같은 개념. 넘으면 거절 |

## 3. 파이썬 도구 이름만 낯선 것들

| 파이썬 쪽 이름 | 게임 개발에서 대응되는 것 |
|----------------|---------------------------|
| `venv` (가상환경) | 프로젝트별 엔진 버전 고정. 다른 프로젝트와 안 섞임 |
| `requirements.lock` | 패키지 매니페스트 + 해시 lock. 팀원 전원이 같은 버전 설치 |
| `pytest` | 유닛 테스트 러너 (NUnit / Unity Test Runner) |
| `ruff` | 린터. 코드 스타일 경고 |
| `mypy` | 정적 타입 검사. C#이면 컴파일러가 대신 해주는 일 |
| Pydantic 모델 | 검증 붙은 설정 클래스. ScriptableObject + `OnValidate()` |
| Protocol / ABC | C# `interface` |
| Fake / 가짜 구현 | 테스트용 스텁. 실제 API 대신 꽂아 넣는 목(mock) |
| ULID | 정렬 가능한 GUID |
| JSONL | 한 줄에 JSON 하나씩 이어 붙인 로그 파일 |
| SQLite | 파일 하나로 끝나는 로컬 DB |

## 4. 개발 순서 (왜 이 순서인가)

```text
00-start-here      기획 확정 · 폴더 경계 정하기
  ↓
phase-00           빈 프로젝트 골격 + 세이브 안전장치
phase-01           AI와 대화 (저장 먼저, 호출은 나중)
phase-02           장기 기억
phase-03           웹/문서 검색으로 근거 찾기   ← 여기가 MVP
  ↓
phase-04           승인 받고 PC 조작
phase-05           여러 단계 자동 수행
phase-06           보안 점검 + 백업/복원         ← v0.5 출시 판정
  ↓
phase-07           음성 입출력
phase-08           트레이 상주 + 설치 패키지     ← v1 후보
operations         라이브 운영 · 장애 대응        ← v1 출시
post-v1            추가 기능은 여기로 미룸
```

순서의 논리는 게임 개발과 똑같다. **세이브/로드가 안 깨지는 걸 먼저 만들고**, 그다음
게임플레이를 올린다. 저장이 불안한 상태에서 기능을 쌓으면 나중에 전부 다시 만져야 한다.

특히 Phase 4(PC 조작)가 Phase 3 뒤에 있는 이유가 중요하다. **AI가 파일을 만들거나 앱을
실행할 수 있게 되는 순간부터 실수의 대가가 실제 피해**가 된다. 그 전에 "AI 출력은 못 믿는
데이터"라는 취급 방식을 Phase 3에서 먼저 완성해 둔다.

## 5. 지금 어디까지 왔나

- 브랜치: `rebuild/v2`
- 상태: Phase 0 구현 완료 (P0-01~P0-08), 공식 게이트 실행 대기
- 기존 프로토타입은 `main` 브랜치와 `D:\Ai\Jarvis-prototype`에 얼려 두었다

실시간 상태는 항상 [PROGRESS.md](./PROGRESS.md)를 본다. 이 파일은 "이번 주 스프린트 보드"에
해당한다. Phase 문서는 계획, PROGRESS는 현재 위치다.

## 6. 폴더별 세부 개발문서

| 폴더 | 한 줄 설명 | 세부 개발문서 |
|------|------------|---------------|
| [00-start-here](./00-start-here/README.md) | 착수 전 결정과 폴더 경계 | [세부](./00-start-here/DETAIL.md) |
| [phase-00-foundation](./phase-00-foundation/README.md) | 안 깨지는 빈 골격 | [세부](./phase-00-foundation/DETAIL.md) |
| [phase-01-chat](./phase-01-chat/README.md) | AI와 대화하고 기록 | [세부](./phase-01-chat/DETAIL.md) |
| [phase-02-memory](./phase-02-memory/README.md) | 장기 기억 | [세부](./phase-02-memory/DETAIL.md) |
| [phase-03-research](./phase-03-research/README.md) | 검색과 근거 | [세부](./phase-03-research/DETAIL.md) |
| [phase-04-tools](./phase-04-tools/README.md) | 승인 받고 PC 조작 | [세부](./phase-04-tools/DETAIL.md) |
| [phase-05-agent](./phase-05-agent/README.md) | 여러 단계 자동 수행 | [세부](./phase-05-agent/DETAIL.md) |
| [phase-06-security](./phase-06-security/README.md) | 보안 점검·백업 | [세부](./phase-06-security/DETAIL.md) |
| [phase-07-voice](./phase-07-voice/README.md) | 음성 입출력 | [세부](./phase-07-voice/DETAIL.md) |
| [phase-08-resident-ui](./phase-08-resident-ui/README.md) | 트레이·패키징 | [세부](./phase-08-resident-ui/DETAIL.md) |
| [operations](./operations/README.md) | 운영·장애 대응 | [세부](./operations/DETAIL.md) |
| [post-v1](./post-v1/README.md) | v1 이후 기능 | [세부](./post-v1/DETAIL.md) |
| [reference](./reference/README.md) | 공통 참조 문서 | [세부](./reference/DETAIL.md) |

## 7. 문서 읽는 요령

Phase 문서는 전부 같은 7개 절로 되어 있다. 티켓 템플릿이라고 보면 된다.

| 절 | 실제 의미 |
|----|-----------|
| 진입 조건 | 선행 작업. 안 끝났으면 시작하지 마라 |
| 만들 파일 | 이번 스프린트에 손댈 파일 목록. 이 밖은 건드리지 않는다 |
| 구현 순서 | 커밋 단위로 쪼갠 작업. `P0-01` 같은 ID가 티켓 번호 |
| 계약 | 반드시 지켜야 할 인터페이스·데이터 포맷. 기준 문서 링크 |
| 테스트 | 작업 직후 돌릴 검증 |
| 완료 게이트 | 통과 판정 조건 |
| 하지 않는 것 | 스코프 크립 방지. "이번엔 안 함"을 명시 |

작업 한 건의 사이클은 이렇다.

```text
기준 문서 확인 → 실패하는 테스트부터 작성 → 최소 구현 → 테스트 통과
→ 문서·설정 동기화 → Phase 게이트 실행
```

"실패하는 테스트를 먼저 쓴다"는 게 낯설 수 있는데, 게임으로 치면 **버그 재현 케이스를 먼저
만들고 고치는 것**과 같다. 재현이 안 되면 고쳐졌는지도 증명할 수 없다.

## 8. 원문에서 볼 곳

- [개발 흐름](./DEVELOPMENT_FLOW.md) — 작업 ID 단위 전체 순서와 게이트
- [docs/README.md](./README.md) — 폴더 색인과 릴리스 경계
- [루트 README](../README.md) — 문서 우선순위와 프로젝트 경계
- [PROGRESS.md](./PROGRESS.md) — 현재 상태
- [문서 변경 규칙](./reference/DOCUMENTATION_RULES.md) — 어떤 문서를 먼저 고치는가
