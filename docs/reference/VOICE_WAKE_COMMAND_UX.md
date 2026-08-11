# 호출 오인·한 문장 명령·답변 중 재호출 (제안)

이 문서는 사용자가 보고한 음성 UX 문제 세 가지의 원인 가설, 목표 동작,
구현 방향이다. 착수 전 결정은 [D018](../00-start-here/DECISIONS.md)이다.
답변 중 에코 게이트의 세부 설계는 [VOICE_BARGE_IN_GATE.md](./VOICE_BARGE_IN_GATE.md)
(D017)를 따른다.

상태: `implemented (S1–S3)` + `P4 fix` — D018 decided. 호출 확정 후 Vosk 중단으로
“자비스 가나다” → “자비스 자비스” 강제 매핑을 막는다.

## 1. 사용자가 보고한 문제

| ID | 현상 | 기대 |
|----|------|------|
| P1 | 마이크에 아무 말이나 들어가면 무조건 “자비스”로 인식된다 | 실제 호출어일 때만 깨어난다 |
| P2 | 답변 TTS 중에 “자비스”라고 불러도 중단 인식이 잘 안 된다 | 근거리에서 부르면 답변을 끊고 새 질문을 받는다 |
| P3 | “자비스 수돗물의 성분에 대해서 알려줘”처럼 한 번에 말해도, 지금은 호출 → 안내 TTS → 다시 질문해야 한다 | 한 문장으로 바로 질문에 답한다 |
| P4 | “자비스 가나다”처럼 호출 뒤 다른 말을 하면 화면/인식이 “자비스 자비스”가 된다 | 호출 확정 후 이어지는 말은 Whisper가 그대로 인식한다 |

## 2. 현재 동작 (기준)

```text
Idle
  → WakeListening (Vosk 제한 문법: "자비스", "자 비스")
  → 최종 결과에 호출어 포함 시 break
  → TTS: “무엇을 도와드릴까요.”
  → Recording (무음 종료) → Whisper 질문 인식
  → Orchestrator → Speaking
       └─ Speaking 중 게이트+Vosk로 “자비스” → TTS cancel → 안내 → Recording
```

관련 코드 경로:

- 호출 대기: `LocalVoiceListener._listen_for_wake`
- 질문: `_capture_and_transcribe_command` + Whisper
- 답변 중 감시: `wait_for_barge_in` + D017 게이트

운영 설명: [VOICE_STT.md](./VOICE_STT.md)

## 3. 원인 가설

### P1 — 아무 말이나 “자비스”

호출 대기는 Vosk에 **허용 문장을 `"자비스"`, `"자 비스"`만** 넣은 제한 문법을
쓴다. `[unk]`(알 수 없는 발화)가 문법에 없으면, 모델이 다른 말도 그중 하나로
억지로 맞출 수 있다. 최종 결과에 호출어가 포함되기만 하면 깨어나므로,
첫 큰 소리·다른 한국어 문장도 호출로 이어질 수 있다.

추가로 호출 대기에는 Speaking용 onset/VAD 게이트가 없어, 작은 잡음·잔향도
바로 STT에 들어간다.

### P2 — 답변 중 재호출 실패

D017 S1(게이트 A+B+WebRTC VAD)이 있어도 스피커 에코·거리·TTS 음량이 크면
사용자 “자비스”가 가려진다. S2 실장치 검증과, 필요 시 AEC/핫키 보조가 남아 있다.
상세는 [VOICE_BARGE_IN_GATE.md](./VOICE_BARGE_IN_GATE.md).

### P3 — 두 단계 강제

`VoiceController.run`이 항상

1. `wait_for_wake`
2. acknowledgement TTS
3. `listen_for_command`

순서를 고정한다. 호출과 질문이 한 발화에 있어도, 호출 구간에서 문장 나머지를
버리지 않고 이어 쓰거나 Whisper로 넘기는 경로가 없다.

### P4 — “자비스 가나다” → “자비스 자비스”

한 문장 경로에서도 호출 확정 **이후**에 Vosk 제한 문법 스트림을 계속 먹이면,
허용 어휘가 `자비스` / `자 비스` / `[unk]`뿐이라 후속 음절(예: “가나다”)이 다시
`자비스`로 강제된다. 콘솔 `[STT 부분]`·`[STT 확정]`에 “자비스 자비스”처럼 보이고,
Whisper `initial_prompt`에 호출어가 반복되면 최종 문장도 비슷하게 치우칠 수 있다.

수정 원칙:

1. Vosk는 **호출 확정 전까지만** feed·미리보기한다.
2. 호출 확정 뒤에는 PCM만 모아 Whisper로 질문(또는 한 문장 전체)을 인식한다.
3. Whisper 결과에서 선두 호출어는 반복 제거한다(이중 “자비스” 안전망).

## 4. 목표 동작

### 4.1 호출 판정 (P1)

다음을 **모두** 만족할 때만 호출로 인정한다.

1. 입력이 사람 음성 후보이다 (레벨·선택적 VAD).
2. Vosk 결과가 호출어와 충분히 가깝다.  
   - 제한 문법을 쓸 경우 `[unk]`를 포함하거나  
   - 문법을 쓰지 않고 자유 인식 후 정규화 일치만 허용
3. “자비스”만 단독이거나, 호출어로 **시작하는** 문장이다.  
   문장 중간의 우연한 부분 일치는 호출로 쓰지 않는다(정책은 D018에서 확정).

오발동 목표(초안, D018에서 확정): 임의 한국어 문장 20회 중 잘못된 호출 0.

### 4.2 한 문장 호출+명령 (P3)

사용자가 한 호흡에 말한 경우를 우선한다.

```text
예: “자비스 수돗물의 성분에 대해서 알려줘”
  → 호출 확인
  → 나머지 “수돗물의 성분에 대해서 알려줘”를 질문으로 사용
  → acknowledgement TTS 생략(또는 아주 짧게)
  → Whisper 품질 가드 후 Orchestrator
  → 답변 TTS
```

분기:

| 발화 | 동작 |
|------|------|
| “자비스”만 | 기존처럼 안내 TTS 후 질문 녹음 |
| “자비스” + 나머지 명령 | 안내 생략, 나머지를 질문으로 처리 |
| 호출어 없음 | 계속 Idle / WakeListening |

나머지가 너무 짧거나 Whisper 품질 가드 실패 시 기존처럼
“잘 듣지 못했습니다…” 후 호출 대기로 돌아간다.

### 4.3 답변 중 재호출 (P2)

목표 UX는 D017과 동일하다. 이 문서에서는 **제품 체감 목표**만 고정한다.

- 스피커 환경: 마이크 가까이에서 “자비스” → TTS 중단 → 새 질문 가능
- 실패 시 폴백: 핫키 중단(별도 결정·Phase 8과 연계 가능), 헤드셋 권장

D018 구현이 P1/P3를 다루더라도 P2의 게이트 파라미터·AEC는 D017 문서를
단일 기준으로 한다.

## 5. 제안 처리 구조

```text
마이크 PCM
  → (선택) 호출 대기용 가벼운 레벨/VAD
  → Vosk 스트리밍 (오인 방지 규칙 적용)
  → 호출 확정 시 같은 발화 버퍼를 유지
       ├─ 나머지 없음 → acknowledgement → 질문 녹음 → Whisper
       └─ 나머지 있음 → (버퍼 또는 이어 녹음) → Whisper
  → 품질 가드 → Orchestrator → Speaking
       └─ D017 게이트 + “자비스” → cancel → 4.2와 동일한 한 문장/두 단계 분기
```

한 문장 경로에서 Whisper 입력은 **호출어를 제거한 텍스트가 아니라**,
가능하면 **호출 직후~무음 종료까지의 PCM**(또는 호출 확정 전 pre-roll 포함 PCM)을
그대로 넣고, 텍스트에서 선두 호출어만 제거하는 방식을 우선 검토한다.
이유: Vosk가 붙인 나머지 문자열은 자유 발화 품질이 낮다.

## 6. 설계 선택지

### 6.1 P1 오인 방지

| 선택 | 내용 | 장단 |
|------|------|------|
| A | 문법에 `[unk]` 복구 + 최종 결과가 호출어와 동일/접두일 때만 통과 | 구현 작음. 오인 감소 기대 |
| B | 호출 대기에도 onset/VAD 게이트 적용 후 STT | Speaking과 정책 통일. 작은 소리 호출은 어려워질 수 있음 |
| C | open-set 호출어(전용 wake model) | 품질 좋으나 새 의존·결정 필요 |

권장 착수 순서: **A → 필요 시 B**. C는 A/B로 목표 미달일 때만.

### 6.2 P3 한 문장 명령

| 선택 | 내용 | 장단 |
|------|------|------|
| A | 호출 확정 후 같은 마이크 세션을 끊지 않고 무음까지 녹음 → Whisper → 선두 호출어 strip | UX 자연스러움. acknowledgement 생략 조건 명확 |
| B | Vosk 최종 문장에서 나머지를 바로 질문으로 사용 | 빠름. 한국어 자유 발화 정확도 부족 |
| C | 항상 두 단계 유지(현행) | P3 미해결 |

권장: **A**. B는 폴백·진단용으로만.

### 6.3 P2

D017 S2 실장치 튜닝을 먼저 하고, 목표 미달 시 핫키 중단·AEC 실험을
[VOICE_BARGE_IN_GATE.md](./VOICE_BARGE_IN_GATE.md) 8절 단계에 따라 진행한다.

## 7. D010과의 관계

[D010](../00-start-here/DECISIONS.md)은 opt-in 로컬 웨이크워드와 호출 전 PCM
비저장을 고정한다. 한 문장 명령은 웨이크워드를 없애지 않고 **호출 직후 질문
수집 방식만** 바꾼다.

- 유지: `--voice`에서만 마이크, 호출 전 PCM 파일/외부 전송 금지
- 변경 후보: 호출 후 항상 acknowledgement를 재생하는 고정 순서
- PTT는 引き続き 후속 보조 입력(Phase 8)

D010 문구를 바꾸려면 D018이 `decided`된 뒤 새 결정으로 `superseded` 처리한다.
구현 전에 D010을 직접 수정하지 않는다.

## 8. 모듈·설정 (착수 시)

제안 변경 지점:

```text
app/voice/controller.py     # 한 세션 wake→command, acknowledgement 조건부 생략
app/voice/stt.py            # 호출 문법·[unk]·접두 판정 헬퍼
app/voice/wake_match.py     # (신규 후보) 정규화·접두·단독 호출 판정 순수 함수
tests/unit/test_wake_match.py
tests/unit/test_voice_controller.py
```

설정 키는 D018 확정 전에는 `settings.example.yaml`에 넣지 않는다. 후보:

| 키(후보) | 의미 |
|----------|------|
| `voice.wake.require_prefix` | 호출어가 문장 선두에 있어야 함 |
| `voice.wake.allow_inline_command` | 한 문장 명령 허용 |
| `voice.wake.skip_ack_when_command` | 나머지 명령 있으면 안내 TTS 생략 |
| `voice.wake.grammar_include_unk` | Vosk 문법에 `[unk]` 포함 |

이벤트 후보는 기존 `voice.recording` / `stt.result`에
`wake_mode=standalone|inline_command` 정도만 추가하는 것을 검토한다.
스키마 변경은 [SCHEMAS.md](../../SCHEMAS.md)와 동기화한다.

## 9. 검증 계획

자동:

- 문법/`[unk]`/접두 판정 단위 테스트: “안녕하세요” → 호출 아님
- “자비스”만 → standalone, acknowledgement 경로
- “자비스 수돗물…” 버퍼 → inline_command, ack 생략, Whisper에 넘길 PCM·strip 규칙
- 답변 문장에 “자비스” 포함 시 기존 barge-in 회귀 유지

실장치:

1. 프로그램 시작 후 호출어 없이 아무 말 → 깨어나지 않음
2. “자비스 수돗물의 성분에 대해서 알려줘” → 안내 없이 바로 답변 시도
3. “자비스”만 → 안내 후 질문 대기
4. 답변 중 근거리 “자비스” → 중단 (D017 S2와 동일 체크리스트)

## 10. 단계적 도입

| 단계 | 내용 | 완료 조건 |
|------|------|-----------|
| S0 | 본 제안·D018 pending 합의 | 문서·결정 ID만 |
| S1 | P1: `[unk]`·접두/단독 호출 판정 | 임의 문장 오호출 0(합의 세트) |
| S2 | P3: 한 세션 녹음 + ack 생략 | 한 문장 명령 실장치 성공 |
| S3 | P2: D017 S2 튜닝·필요 시 핫키 | 중단 성공률 목표 |
| S4 | P4: 호출 확정 후 Vosk 중단·선두 호출어 반복 strip | “자비스 가나다”가 자비스로 강제되지 않음 |

S1 없이 S2만 넣으면 오호출된 상태에서 긴 문장까지 Whisper로 넘어가 체감이
더 나빠질 수 있으므로 **S1을 먼저** 한다.

## 11. 비목표

- 화자 인증(“내 목소리만”)
- 온라인 STT
- 호출어를 없앤 always-listening 자유 대화
- 날씨 등 웹 검색(별도 Phase 3 / D006)

## 12. 관련 문서

- [VOICE_STT.md](./VOICE_STT.md) — 현재 STT 운영
- [VOICE_BARGE_IN_GATE.md](./VOICE_BARGE_IN_GATE.md) — 답변 중 게이트 (P2)
- [Phase 7](../phase-07-voice/README.md) — 음성 Phase
- [DECISIONS D018](../00-start-here/DECISIONS.md) — 본 제안 채택 여부
- [DOCUMENTATION_RULES.md](./DOCUMENTATION_RULES.md) — 기준 문서 수정 순서
