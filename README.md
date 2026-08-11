# Jarvis 개발 문서 허브

이 파일은 Jarvis를 구현할 때 **가장 먼저 읽는 문서**다. 현재 Phase 0 기반 구현과 완료 게이트를 통과했으며, 설정 검증·SQLite·민감정보 마스킹·복구·단일 인스턴스 잠금을 갖춘 안전한 echo CLI를 실행할 수 있다. 아래 순서를 지키면 다른 대화나 구두 설명 없이 개발을 이어갈 수 있다.

## 1. 처음 시작하는 순서

1. [착수 안내](./docs/00-start-here/README.md)를 읽고 미결정 항목을 확인한다.
2. [결정 기록](./docs/00-start-here/DECISIONS.md)에서 현재 Phase를 막는 항목을 확정한다.
3. 해당 Phase 폴더의 `README.md`를 위에서 아래로 수행한다.
4. 각 작업마다 테스트를 먼저 연결하고 구현한다.
5. `python scripts\gate.py --phase N`이 종료 코드 0일 때만 다음 Phase로 이동한다.

현재 구현 결과: [Phase 0 — 기반 구축](./docs/phase-00-foundation/README.md) 완료
다음 개발 문서: [Phase 1 — 대화](./docs/phase-01-chat/README.md) (D005 결정 후 착수)

현재 진행 상태: [개발 진행 현황](./docs/PROGRESS.md)

Phase 0 실행 명령:

```powershell
python scripts\bootstrap.py
python scripts\gate.py --phase 0
python -m app
```

CLI에서는 `/help`, `/bye`를 사용할 수 있고, 그 밖의 입력은 외부 API 호출 없이 그대로 echo한다.

## 2. 문서의 역할과 우선순위

| 문서 | 답하는 질문 | 변경 권한 |
|------|-------------|-----------|
| [PLAN.md](./PLAN.md) | 무엇을, 왜, 어느 릴리스까지 만드는가? | 제품 범위·Phase·완료 기준의 기준 |
| [DESIGN.md](./DESIGN.md) | 모듈이 어떻게 나뉘고 어떤 계약으로 통신하는가? | 코드 구조·인터페이스의 기준 |
| [SCHEMAS.md](./SCHEMAS.md) | 파일·DB·이벤트·도구 데이터는 어떤 모양인가? | 저장 형식의 단일 기준 |
| [TESTING.md](./TESTING.md) | 완료를 어떻게 증명하는가? | 테스트·릴리스 게이트의 기준 |
| [`docs/phase-*`](./docs/README.md) | 지금 어떤 파일을 어떤 순서로 구현하는가? | 실행 순서와 작업 체크리스트 |
| [`config/*.example.yaml`](./config) | 정책·운영 기본값은 무엇인가? | 실행 설정 템플릿 |

내용이 충돌하면 `PLAN → DESIGN → SCHEMAS → TESTING → Phase 문서` 순으로 무조건 덮어쓰지 않는다. 먼저 충돌의 성격에 맞는 기준 문서를 수정하고, [문서 변경 규칙](./docs/reference/DOCUMENTATION_RULES.md)에 따라 하위 문서를 동기화한다.

## 3. 전체 개발 흐름

| 순서 | 개발 단계 | 핵심 산출물 | 완료 후 상태 |
|------|-----------|-------------|--------------|
| 0 | [착수 준비](./docs/00-start-here/README.md) | 결정 기록, 개발 환경 확인 | 구현 조건 확정 |
| 1 | [Phase 0 — 기반](./docs/phase-00-foundation/README.md) | 설정·ID·로그·SQLite·복구 골격 | 안전한 빈 CLI |
| 2 | [Phase 1 — 대화](./docs/phase-01-chat/README.md) | LLM 클라이언트·대화·예산 | 저장되는 챗봇 |
| 3 | [Phase 2 — 기억](./docs/phase-02-memory/README.md) | 기억 lifecycle·검색·요약 | 재시작 후 기억 유지 |
| 4 | [Phase 3 — 검색/RAG](./docs/phase-03-research/README.md) | 웹·문서 검색·근거·신뢰 경계 | 근거를 찾아주는 비서(MVP) |
| 5 | [Phase 4 — PC 도구](./docs/phase-04-tools/README.md) | Safety Gate·승인·Secure Runner | 제한된 PC 제어 |
| 6 | [Phase 5 — 에이전트](./docs/phase-05-agent/README.md) | 멀티스텝·체크포인트·멱등성 | 복합 작업 수행 |
| 7 | [Phase 6 — 보안 게이트](./docs/phase-06-security/README.md) | 보안 회귀·백업·감사 검증 | v0.5 후보 |
| 8 | [Phase 7 — 음성](./docs/phase-07-voice/README.md) | PTT·STT·TTS | 음성 입출력 |
| 9 | [Phase 8 — 상주 UI](./docs/phase-08-resident-ui/README.md) | 트레이·단축키·패키징 | v1 후보 |
| 10 | [운영과 릴리스](./docs/operations/README.md) | 백업·복원·장애 대응·7일 안정화 | v1 릴리스 |
| 11 | [Post-v1 선택 기능](./docs/post-v1/README.md) | 로컬 LLM·임베딩·연동·웨이크워드 | 개별 후속 릴리스 |

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
- 운영 데이터: `D:\Jarvis`
- 테스트 데이터: pytest의 `tmp_path` 아래 임시 루트
- 운영 시크릿: Windows Credential Manager
- 개발용 `.env`: `D:\Ai\Jarvis\.env`, `dev_mode=true`에서만 허용
- 상태 저장: raw 대화는 JSONL, 상태가 있는 데이터는 SQLite
- 기본 보안 정책: 등록되지 않은 도구·경로·도메인은 거부

## 6. 구현을 시작하기 전에 남은 결정

다음 값은 문서에서 임의로 추측하지 않는다.

- Phase 1: LLM 제공자, 정확한 모델 ID, 실제 단가
- Phase 3: 검색 API 제공자와 인증 방식
- Phase 3: PDF 지원 여부와 parser
- Phase 6: 운영 백업 대상 경로와 암호화 도구
- Phase 7: 온라인 TTS 또는 로컬 TTS
- Phase 8: 패키징·전역 단축키·자동 시작 방식

결정 상태와 선택 기준은 [DECISIONS.md](./docs/00-start-here/DECISIONS.md)에 기록한다.

## 7. 참고 문서

- [전체 문서 지도](./docs/README.md)
- [개발 진행 현황](./docs/PROGRESS.md)
- [요구사항 추적표](./docs/reference/TRACEABILITY.md)
- [위협 모델](./docs/reference/THREAT_MODEL.md)
- [문서 변경 규칙](./docs/reference/DOCUMENTATION_RULES.md)
- [운영·장애 대응](./docs/operations/README.md)
