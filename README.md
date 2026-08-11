# Jarvis 개발 문서 허브

이 파일은 Jarvis를 구현할 때 **가장 먼저 읽는 문서**다. 현재 Phase 0 기반과 Phase 1 로컬 대화 게이트를 통과했으며, Ollama `qwen3.5:9b`로 한국어 멀티턴 대화, raw 선저장, 재시도, 컨텍스트·비용 통제를 수행하는 CLI를 실행할 수 있다. 아래 순서를 지키면 다른 대화나 구두 설명 없이 개발을 이어갈 수 있다.

## 1. 처음 시작하는 순서

1. [착수 안내](./docs/00-start-here/README.md)를 읽고 미결정 항목을 확인한다.
2. [결정 기록](./docs/00-start-here/DECISIONS.md)에서 현재 Phase를 막는 항목을 확정한다.
3. 해당 Phase 폴더의 `README.md`를 위에서 아래로 수행한다.
4. 각 작업마다 테스트를 먼저 연결하고 구현한다.
5. `python scripts\gate.py --phase N`이 종료 코드 0일 때만 다음 Phase로 이동한다.

현재 구현 결과: [Phase 1 — 대화](./docs/phase-01-chat/README.md) 완료 (`Ollama` + `qwen3.5:9b`)
다음 개발 문서: [Phase 2 — 기억](./docs/phase-02-memory/README.md)

현재 진행 상태: [개발 진행 현황](./docs/PROGRESS.md)

Phase 1 실행 명령:

```powershell
python scripts\bootstrap.py
ollama list
python -m app
```

CLI에서는 `/help`, `/clear`, `/budget`, `/bye`를 사용할 수 있다. 한 번만 질문하려면
`python -m app --once "대한민국의 수도는 어디인가요?"`를 실행한다. 자동 완료 게이트는
`python scripts\gate.py --phase 1`이며 외부 네트워크를 사용하지 않는다.

로컬 음성 기능은 다음과 같이 준비하고 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\python.exe scripts\setup_voice.py
.\.venv\Scripts\python.exe -m app --voice
```

PowerShell 실행 정책 때문에 `Activate.ps1`을 실행할 수 없어도 위 명령은 그대로 동작한다.
첫 준비에서는 고정 SHA의 Vosk 호출어 모델과 faster-whisper small 질문 모델을
`D:\Jarvis\models`에 설치한다.

터미널에 `[마이크 켜짐]`이 표시되면 “자비스”만 부르거나,
“자비스 수돗물의 성분에 대해서 알려줘”처럼 **호출과 질문을 한 문장으로** 이어서 말한다.
호출만 하면 안내(“무엇을 도와드릴까요.”) 후 질문을 받고, 한 문장에 질문이 있으면 안내 없이
바로 인식·답변한다. Ctrl+C 또는 “종료”로 끝낼 수 있다. 음성 PCM은 메모리의 제한 버퍼에만
두며 파일이나 외부 API로 보내지 않는다. 호출 대기에는 `[STT 부분]`·`[STT 확정]`,
인식 뒤에는 `[Whisper 확정]`과 품질값이 표시된다. 질문은 연속 무음에서 자동으로 끝난다.
품질이 낮으면 Ollama에 보내지 않고 다시 말해 달라고 안내한다. 정확도 조정은
[한국어 STT 운영 가이드](./docs/reference/VOICE_STT.md)와
[호출·한 문장 UX](./docs/reference/VOICE_WAKE_COMMAND_UX.md)를 따른다.

답변을 읽는 중에는 `[끼어들기 감시]`가 표시된다. 중간에 멈추려면 마이크 가까이에서
“자비스”라고 말하거나 **`Ctrl+Alt+J`**를 누른다. 음성 끊기는 D017 게이트(근거리 onset +
WebRTC VAD)를 통과한 구간만 STT에 넣는다. `[답변 중단]` 뒤 새 질문을 받으면 된다.

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
| 11 | [Post-v1 선택 기능](./docs/post-v1/README.md) | 로컬 LLM·임베딩·연동·웨이크워드 고도화 | 개별 후속 릴리스 |

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

- Phase 1: D005 결정 완료 — Ollama, `qwen3.5:9b`, 외부 단가 USD 0.00
- Phase 3: 검색 API 제공자와 인증 방식
- Phase 3: PDF 지원 여부와 parser
- Phase 6: 운영 백업 대상 경로와 암호화 도구
- Phase 7: D009 로컬 TTS, D010 호출 방식, D016 하이브리드 한국어 STT 결정 완료
- Phase 8: 패키징·전역 단축키·자동 시작 방식

결정 상태와 선택 기준은 [DECISIONS.md](./docs/00-start-here/DECISIONS.md)에 기록한다.

## 7. 참고 문서

- [전체 문서 지도](./docs/README.md)
- [개발 진행 현황](./docs/PROGRESS.md)
- [요구사항 추적표](./docs/reference/TRACEABILITY.md)
- [위협 모델](./docs/reference/THREAT_MODEL.md)
- [문서 변경 규칙](./docs/reference/DOCUMENTATION_RULES.md)
- [운영·장애 대응](./docs/operations/README.md)
