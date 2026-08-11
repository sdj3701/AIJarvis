# Phase 7 — 음성 입출력

## 1. 목표

명시적으로 시작한 `--voice` 모드에서 로컬 웨이크워드 “자비스”로 한국어 음성 대화를 시작하고 짧은 응답을 안전하게 낭독한다. 기존 Orchestrator를 재사용하며 음성 경로가 승인 정책을 약화시키지 않게 한다.

> 사용자 요청으로 Phase 1 직후 로컬 음성 세로 기능을 먼저 구현했다. 이는 Phase 7 정식 완료를 뜻하지 않는다. Phase 2~6과 음성 승인 정책을 마친 뒤 이 문서의 전체 게이트를 다시 수행한다.

이전: [Phase 6](../phase-06-security/README.md) · 다음: [Phase 8](../phase-08-resident-ui/README.md)

## 2. 진입 조건

- v0.5/Phase 6 릴리스 게이트 통과
- [D009 TTS](../00-start-here/DECISIONS.md) 확정
- [D016 한국어 STT](../00-start-here/DECISIONS.md) 모델·오디오 입력 장치 사전 확인
- text channel에서 Phase 4~5 작업이 안정적으로 동작

## 3. 만들 파일

```text
app/voice/{base.py,stt.py,tts.py,controller.py}
app/voice/microphone.py
scripts/setup_voice.py
tests/fakes/audio.py
tests/integration/test_voice_parity.py
tests/data/audio/                 # 직접 제작한 짧은 테스트 음성만
```

## 4. 상태 흐름

```text
Idle → WakeListening → “무엇을 도와드릴까요.” → Recording
→ Transcribing → Orchestrator(text, channel=voice)
→ Speaking 또는 ApprovalWaiting → Idle
              └─ Speaking 중 “자비스” → TTS cancel → 안내 → Recording
```

동시에 녹음과 TTS를 수행하지 않는다. 녹음 중 TTS가 시작되면 자신의 출력을 다시 입력으로 듣는 루프가 생긴다.

## 5. 구현 순서

### P7-01 음성 계약

1. `AudioFrame`, `Transcript`, `STTEngine`, `TTSEngine` 프로토콜을 구현한다.
2. 오디오 형식은 mono PCM, sample rate와 dtype을 명시한다.
3. STT 결과에 text, language, confidence/segments, duration을 담는다.
4. 빈 음성·너무 짧은 음성·timeout을 정상 실패로 구분한다.
5. 엔진 타입은 `voice` 모듈 밖으로 노출하지 않는다.

계약은 [DESIGN의 음성·UI 계약](../../DESIGN.md)을 따른다.

### P7-02 웨이크워드 controller와 PTT 보조 입력

1. `--voice`에서만 마이크를 열고 “자비스” 호출을 로컬에서 감지한다.
2. 호출 전 PCM은 제한된 메모리 버퍼에만 두고 디스크·API에 저장하지 않는다.
3. 호출되면 TTS로 정확히 “무엇을 도와드릴까요.”를 재생한 뒤 요청 녹음을 시작한다.
4. PTT는 Phase 8 전역 단축키와 함께 보조 입력으로 추가한다.
5. 최대 녹음 시간과 무음 제한을 적용한다.
6. 녹음 중임을 controller 상태와 UI 이벤트로 즉시 알린다.
7. 입력 장치 오류 시 현재 text UI는 계속 동작하게 한다.
8. 앱 종료 시 스트림을 닫고 자원을 정리한다.

### P7-03 STT

1. 호출어는 `vosk-model-small-ko-0.22`를 고정 SHA-256 검증 후 로컬에서 lazy load하고 `자비스` 변형만 제한 문법으로 감지한다.
2. 호출 뒤 질문 PCM은 처음 음절 pre-roll, 음성 시작, 연속 무음 종료, 최대 녹음 시간을 적용해 메모리에서만 모은다.
3. 질문은 고정 revision의 `Systran/faster-whisper-small`로 `language="ko"`, `beam_size=5`, VAD를 적용해 재인식한다.
4. CUDA `int8_float16`을 우선하고 초기화할 수 없으면 CPU `int8`로 폴백한 사실을 화면에 명시한다.
5. 빈 결과·낮은 평균 log probability·높은 no-speech probability를 정상적인 인식 실패로 분류하고 LLM에 전달하지 않는다.
6. sounddevice·Vosk·faster-whisper 또는 모델이 없으면 설치 명령을 사용자에게 명시한다.
7. 장치명·입력 dBFS·한국어 최종 결과·품질·지연시간을 콘솔에 표시한다.
8. transcript를 raw에 저장하기 전에 Privacy Gate for_log/for_memory를 적용한다.
9. p95 latency 측정 이벤트를 기록한다.

세부 임계값과 실장치 점검 방법은 [한국어 STT 운영 가이드](../reference/VOICE_STT.md)를 따른다.

### P7-04 Orchestrator 연결

1. Transcript text를 기존 `handle_turn`에 전달한다.
2. `RequestContext.channel="voice"`를 정책 엔진까지 유지한다.
3. 인식 결과를 화면에 먼저 표시해 사용자가 취소할 기회를 준다.
4. low 작업은 text와 같은 결과를 내야 한다.
5. high 작업은 음성으로 승인할 수 없고 화면의 text typed confirmation으로 전환한다.

### P7-05 TTS

1. 최종 답변만 읽고 tool 원문·감사 로그·승인 token은 읽지 않는다.
2. 모든 문자열은 `PrivacyGate.for_tts`를 통과한다. 온라인 TTS는 추가로 `for_external_text(..., purpose="online_tts")`를 통과한 문자열만 전송한다.
3. secret/pii_high는 화면 전용 fallback 문장으로 대체한다.
4. 최대 글자 수를 넘으면 첫 요약만 읽고 전체는 화면에 표시한다.
5. 사용자가 답변 중 “자비스”만 말하면 현재 TTS를 취소한다.
6. Windows SAPI `Microsoft Heami Desktop`만 사용하며 온라인 TTS로 폴백하지 않는다.
7. Heami `rate=4`로 기본 대비 실측 약 1.55배 속도로 낭독한다.
8. 답변 중 최근 음성 입력과 함께 Vosk 부분·최종 결과에서 `자비스`가 확인되면 현재
   SAPI 프로세스를 종료한 뒤 새 질문을 받는다. 읽는 답변에 호출어가 포함된 구간은
   부분 결과를 제한해 자기 음성 오인을 막는다.
9. [D017](../00-start-here/DECISIONS.md)에 따라 Speaking 전용 임계값·적응형 onset·
   메모리 pre-roll·WebRTC VAD를 적용하고 통과 PCM만 Vosk에 보낸다. AEC는 스피커
   실장치 목표에 미달할 때만 후속 실험한다.
10. [D018](../00-start-here/DECISIONS.md)에 따라 Vosk `[unk]`·접두 호출 판정,
    한 문장 호출+명령(안내 TTS 생략), 답변 중 `interrupt_hotkey` 중단을 적용한다.
    상세는 [VOICE_WAKE_COMMAND_UX.md](../reference/VOICE_WAKE_COMMAND_UX.md).

### P7-06 자원 관리

- Vosk 호출어 감지는 CPU에서 실행하고 Whisper small은 질문을 받은 동안에만 GPU 추론
- Whisper는 `int8_float16`로 실행하고 CUDA 실패 시 CPU `int8` 폴백
- 녹음 buffer 상한 적용
- 장시간 idle이면 선택적으로 모델 unload

## 6. 필수 테스트

- 같은 transcript의 text/voice TurnOutcome 의미 일치
- 빈 음성·장치 없음·STT timeout 처리
- mic indicator가 Recording 전체 구간에 켜짐
- voice channel high 승인 거부
- secret/pii_high TTS 입력 0건
- 긴 답변 TTS 길이 제한
- TTS 중 PTT 시작 시 TTS 취소
- GPU 없는 환경은 명확한 skip 또는 CPU fallback
- 무음·잡음·낮은 신뢰도 결과가 Ollama에 전달되지 않음
- 질문 첫 음절이 pre-roll에 포함되고 연속 무음 뒤 자동 종료

현재 선행 세로 기능 검증:

- [x] USB 마이크 PCM 입력, 오버플로 0 확인
- [x] 로컬 한국어 TTS “무엇을 도와드릴까요.” 실제 재생
- [x] “자비스” 호출→음성 질문→`channel=voice` Ollama→답변 TTS 조립 테스트
- [x] secret/pii_high 실제 문장 낭독 0건
- [x] 호출 전 PCM 파일·외부 전송 0건
- [x] RTX 4070 Ti CUDA Whisper 모델 load·forward 성공
- [x] 로컬 SAPI 한국어 “오늘 날짜를 알려줘.” 정확히 복원
- [x] 평상시 호출 대기에서 Vosk 부분 결과로 호출하지 않음·10초 무음 잘못된 최종 호출 0회
- [x] 답변 중 `자비스` 부분·최종 호출→TTS cancel→웨이크 대기 생략→새 질문 조립 테스트
- [x] 읽는 답변 속 `자비스` 부분 결과를 끼어들기로 오인하지 않음
- [x] 일정한 큰 TTS 에코·큰 비음성 소음에서 Speaking 게이트 닫힘
- [x] VAD 음성 onset에서 pre-roll 포함, 닫힌 게이트의 Vosk feed 0회
- [x] Heami rate 0/4 동일 문장 비교에서 약 1.55배 속도 확인
- [ ] 스피커 답변 30초 침묵 오발동 0회·근거리 “자비스” 10회 성공률 기록
- [ ] Vosk 호출어 + Whisper 질문 하이브리드 실장치 스모크

## 7. 완료 게이트

```powershell
python scripts\gate.py --phase 7
```

- [ ] 음성으로 허용 앱 실행 성공
- [ ] text/voice 결과 동등성 테스트 통과
- [ ] 음성 High 승인 0건
- [ ] 민감정보 낭독 0건
- [ ] PTT 종료 후 STT 결과 p95 목표 측정
- [ ] 장치 오류 후 text UI 사용 가능

## 8. 이 Phase에서 하지 않는 것

- OS 로그인 자동 시작과 사용자 모르게 마이크 열기
- 음성 생체 인증
- 음성만으로 High 작업 승인
- 긴 문서 전체 낭독
