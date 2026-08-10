# Phase 7 — 음성 입출력

## 1. 목표

push-to-talk으로 한국어 음성을 텍스트 요청으로 변환하고 짧은 응답을 안전하게 낭독한다. 기존 Orchestrator를 재사용하며 음성 경로가 승인 정책을 약화시키지 않게 한다.

이전: [Phase 6](../phase-06-security/README.md) · 다음: [Phase 8](../phase-08-resident-ui/README.md)

## 2. 진입 조건

- v0.5/Phase 6 릴리스 게이트 통과
- [D009 TTS](../00-start-here/DECISIONS.md) 확정
- GPU·CUDA·오디오 입력 장치 사전 확인
- text channel에서 Phase 4~5 작업이 안정적으로 동작

## 3. 만들 파일

```text
app/voice/{base.py,stt.py,tts.py,controller.py}
tests/fakes/audio.py
tests/integration/test_voice_parity.py
tests/data/audio/                 # 직접 제작한 짧은 테스트 음성만
```

## 4. 상태 흐름

```text
Idle → Recording → Transcribing → Orchestrator(text, channel=voice)
→ Speaking 또는 ApprovalWaiting → Idle
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

### P7-02 Push-to-talk controller

1. 키 누름 시작에서 녹음하고 뗄 때 중단한다.
2. 최대 녹음 시간과 무음 제한을 적용한다.
3. 녹음 중임을 controller 상태와 UI 이벤트로 즉시 알린다.
4. 입력 장치 오류 시 현재 text UI는 계속 동작하게 한다.
5. 앱 종료 시 스트림을 닫고 GPU 작업을 정리한다.

### P7-03 STT

1. faster-whisper를 설정에 따라 lazy load한다.
2. 모델 load 실패 시 CPU fallback 여부를 사용자에게 명시한다.
3. Korean language hint를 주되 결과 language를 기록한다.
4. transcript를 raw에 저장하기 전에 Privacy Gate for_log/for_memory를 적용한다.
5. p95 latency 측정 이벤트를 기록한다.

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
5. 사용자가 말하기 시작하면 현재 TTS를 취소한다.
6. edge-tts 선택 시 요청 전 online_tts 예산을 확인하고 성공 비용을 기록한다.
7. edge-tts 선택 시 네트워크 전송 사실과 실패를 명확히 표시한다.

### P7-06 자원 관리

- STT 모델과 향후 로컬 LLM이 GPU를 동시에 점유하지 않도록 lazy load/unload 정책 적용
- 메모리 부족 시 작은 STT 모델 또는 CPU fallback
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

- 웨이크워드·상시 녹음
- 음성 생체 인증
- 음성만으로 High 작업 승인
- 긴 문서 전체 낭독
