# Phase 1 — 대화와 raw 저장

## 1. 목표

로컬 Ollama로 멀티턴 대화를 수행하고, 사용자 입력을 모델 호출 전에 저장하며, 재시도·비용·컨텍스트 한도를 통제한다.

이전: [Phase 0](../phase-00-foundation/README.md) · 다음: [Phase 2](../phase-02-memory/README.md)

## 2. 진입 조건

- `python scripts\gate.py --phase 0` 종료 코드가 0이다.
- [D005](../00-start-here/DECISIONS.md)가 `decided`다.
- `settings.yaml`의 provider, base URL, model, digest, pricing 값이 placeholder가 아니다.
- Ollama가 실행 중이고 `qwen3.5:9b`의 digest가 D005와 일치한다. API 키는 필요하지 않다.

## 3. 만들 파일

```text
app/budget.py
app/llm/{base.py,ollama_client.py,fake.py}
app/orchestrator/{prompt.py,loop.py,prompts/system_core.md}
app/memory/store.py              # 세션·raw 범위만
app/telemetry/metrics.py
tests/fakes/llm.py
tests/integration/test_chat_turn.py
tests/unit/test_{prompt_budget,budget_guard}.py
tests/slow/test_crash_loop.py
```

## 4. 한 턴의 고정 흐름

```text
입력 수신
→ request/session/turn ID 생성
→ raw user 줄 append+flush
→ user.input 이벤트 append+flush
→ Ollama loopback 대상·모델 digest 검사
→ BudgetGuard 사전 검사
→ 프롬프트 조립
→ 로컬 LLM 호출/제한된 재시도
→ llm.response·비용 기록
→ raw assistant 줄 append+flush
→ 화면 출력
```

저장보다 모델 호출이 먼저 일어나는 구현은 허용하지 않는다.

## 5. 구현 순서

### P1-01 LLM 계약과 가짜 클라이언트

1. [DESIGN 5.1](../../DESIGN.md)의 `Message`, `ToolCall`, `LLMUsage`, `LLMResponse`, `LLMClient`를 구현한다.
2. `FakeLLMClient`를 먼저 구현해 네트워크 없이 이후 작업을 테스트한다.
3. 스크립트 응답이 소진되면 즉시 예외를 던지게 한다.
4. Phase 1에서는 tool call을 받으면 `LLMBadResponse`로 처리한다.

### P1-02 Ollama 클라이언트

1. `wiring.py`에서 Ollama 구현 하나만 조립한다.
2. 연결 실패·timeout·5xx만 지수 backoff+jitter로 최대 횟수까지 재시도한다.
3. 잘못된 요청·모델 누락·digest 불일치는 재시도하지 않는다.
4. 각 시도에 `llm.request`, `llm.retry`, `llm.response` 이벤트를 남긴다.
5. Ollama 응답을 내부 타입으로 변환하고 알 수 없는 finish reason은 거부한다.
6. base URL은 `http://127.0.0.1:11434`만 허용하고 외부 호스트·클라우드 폴백은 거부한다.

Ollama 응답 타입이 `orchestrator`나 `memory`로 새어나오면 안 된다.

### P1-03 세션과 raw 로그

1. `sessions` 행을 생성하고 raw 경로를 연결한다.
2. [SCHEMAS 4장](../../SCHEMAS.md)의 raw 레코드를 JSONL로 쓴다.
3. 마지막 줄이 깨졌을 때 유효 줄과 깨진 꼬리를 분리한다.
4. `/clear`는 현재 프롬프트 히스토리만 비우고 raw 감사 기록은 지우지 않는다.
5. `/bye`는 세션을 종료하되 요약은 Phase 2 전까지 만들지 않는다.

### P1-04 프롬프트와 컨텍스트 예산

1. `system_core.md`에 한국어 응답·추측 금지·검색 전 단정 금지 규칙을 기록한다.
2. [DESIGN 7.1](../../DESIGN.md)의 메시지 순서를 구현하되 Phase 1에서는 memory/tool 블록을 비운다.
3. 최근 3턴과 현재 사용자 발화는 유지한다.
4. 히스토리 상한을 넘으면 오래된 턴부터 압축한다.
5. 입력 자체가 한도를 넘으면 모델을 호출하지 않고 사용자 오류로 끝낸다.
6. prompt 파일의 version을 `llm.request`에 기록한다.

### P1-05 비용 예산

1. [DESIGN 12장](../../DESIGN.md)의 `BudgetGuard`를 구현한다.
2. 금액은 `Decimal`로 계산하고 DB에는 문자열로 저장한다.
3. 요청 전 최악 비용을 검사한다.
4. 80%에서 세션당 한 번 경고하고, 100%에서 신규 요청만 차단한다.
5. `/budget`으로 일·월 사용량을 출력한다.

### P1-06 대화 오케스트레이터와 CLI

1. 도구 없는 `handle_turn`을 구현한다.
2. 취소 토큰을 Ollama 호출과 프롬프트 조립에서 확인한다.
3. 오류는 사용자 메시지로 변환하고 raw/event 로그에 실패 상태를 남긴다.
4. `/help`, `/clear`, `/budget`, `/bye`를 CLI 디스패처로 분리한다.
5. Ollama 클라이언트 외부에서는 네트워크를 사용하지 않는다.

### P1-07 크래시·재시도 테스트

1. [TESTING 8장](../../TESTING.md)의 5개 종료 지점 × 4회 테스트를 구현한다.
2. 강제 종료 후 사용자 입력이 raw에 남아 있는지 확인한다.
3. timeout/연결 실패/5xx가 max retry 뒤 끝나는지 확인한다.
4. 실제 대기 없이 주입한 sleeper로 backoff를 검증한다.
5. 운영 모드에서 테스트 kill hook이 무효인지 확인한다.

## 6. 필수 이벤트

- `session.start`, `session.end`
- `user.input`
- `llm.request`, `llm.retry`, `llm.response`
- `budget.warn`, `budget.stop`
- `error`

payload는 [SCHEMAS 2.2](../../SCHEMAS.md)를 그대로 따른다.

## 7. 완료 게이트

```powershell
python scripts\gate.py --phase 1
```

- [ ] 멀티턴 문맥 유지
- [ ] Ollama 오류가 사용자 메시지와 이벤트에 기록됨
- [ ] 20회 강제 종료에서 사용자 입력 유실 0건
- [ ] 무한 재시도 없음
- [ ] 컨텍스트 압축 후 최근 턴 유지
- [ ] 일/월 예산 100%에서 신규 요청 차단
- [ ] 실제 로컬 모델 수동 스모크 3턴 성공, GPU 적재, 비용 USD 0.00 확인
- [ ] Ollama loopback 외 외부 HTTP 0건

## 8. 이 Phase에서 하지 않는 것

- 장기 기억을 프롬프트에 넣기
- 웹 검색과 도구 호출
- 후보 fact 자동 생성
- 다중 LLM 제공자 추상화 확장
