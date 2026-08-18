# L7 — 말하는 자비스

이전: [G6](./G6-security.md) · 다음: [L8](./L8-resident-ui.md)  
구현: [phase-07-voice](../phase-07-voice/README.md) · 큰 흐름: [FLOW](../FLOW.md)

## 이 단계에서 얻는 것

`--voice`에서만 마이크를 열고, 호출어·STT·TTS로 같은 일을 시킨다. “말로 시켜도 된다.”

## 진입

- Phase 6(v0.5) 게이트 통과 권장
- D009·D016~D019 decided (TTS/STT/끼어들기/호출 UX/소스 필터)
- NVIDIA/CUDA는 이 단계에서만 필수에 가깝다

## 핵심 산출

- Vosk 호출 + Whisper 질문, Windows SAPI TTS
- 끼어들기 게이트·한 문장 명령·Soft 소스 필터
- PCM 비저장, High 도구의 음성 승인 금지

## 넘어가는 조건

Phase 7 게이트 0 + 사람 발화 스모크. 참고: [VOICE_*](../reference/README.md)

## 구현 시 볼 작업

Phase 7 README의 P7 작업·실장치 S2/S3 표를 따른다. 선행 구현이 있어도 정식 게이트와 별개다.
