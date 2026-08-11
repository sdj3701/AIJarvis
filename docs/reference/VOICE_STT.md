# 한국어 STT 운영 가이드

이 문서는 `python -m app --voice`의 한국어 음성 인식 구조, 고정 모델, 품질 판정,
개인정보 경계와 실장치 점검 방법을 정의한다. 구현 기준 결정은
[D016](../00-start-here/DECISIONS.md)이며 Phase 7의 선행 음성 세로 기능에 적용한다.

## 1. 문제와 목표

USB 마이크의 PCM 수신과 Vosk 부분 결과 출력은 정상 동작하지만,
`vosk-model-small-ko-0.22` 단독 자유 발화는 한국어 질문을 다른 문장으로 바꾸는 경우가
많았다. 목표는 호출 대기 자원은 작게 유지하면서 실제 질문 정확도를 높이는 것이다.

## 2. 처리 구조

```text
마이크 PCM16 16 kHz mono
  → Vosk 제한 문법으로 “자비스” 감지
  → SAPI: “무엇을 도와드릴까요.”
  → 질문 녹음(pre-roll + 음성 시작 + 연속 무음 종료)
  → faster-whisper small 한국어 인식
  → 품질 가드
      ├─ 통과: 화면에 최종 문장 표시 → Ollama → SAPI
      └─ 실패: 다시 말해 달라는 TTS → 호출 대기
```

호출어와 질문 인식기를 분리하는 이유는 Vosk의 낮은 대기 자원과 Whisper의 자유 발화
정확도를 각각 필요한 구간에만 사용하기 위해서다.

## 3. 고정 모델과 실행 값

| 구분 | 고정 값 |
|------|---------|
| 호출어 엔진 | `vosk==0.3.45` |
| 호출어 모델 | `vosk-model-small-ko-0.22` |
| 질문 엔진 | `faster-whisper==1.2.1` |
| 질문 모델 | `Systran/faster-whisper-small` |
| 모델 revision | `536b0662742c02347bc0e980a01041f333bce120` |
| `model.bin` SHA-256 | `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671` |
| 언어·작업 | `ko`, `transcribe` |
| 탐색 | `beam_size=5` |
| GPU | CUDA `int8_float16` |
| CPU 폴백 | `int8` |
| 오디오 | PCM16, mono, 16 kHz |

Whisper small은 다국어 모델이며 이 프로젝트의 RTX 4070 Ti 12GB에서 Ollama 9B와
병행할 수 있도록 medium 대신 선택했다. 모델과 런타임은 아래 원본 출처를 고정한다.

- [Systran faster-whisper-small 고정 revision](https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120)
- [faster-whisper 패키지와 GPU 실행 방법](https://pypi.org/project/faster-whisper/)
- [OpenAI Whisper 모델 크기 안내](https://github.com/openai/whisper#available-models-and-languages)
- [Vosk 공식 모델 목록](https://alphacephei.com/vosk/models)

## 4. 녹음과 무음 종료

- 마이크 프레임은 250ms 단위로 제한된 큐에 둔다.
- 호출 전 PCM은 파일에 쓰지 않으며 오래된 프레임은 즉시 폐기한다.
- 평상시 호출 대기에서는 Vosk 부분 결과를 화면 진단에만 쓰고 `자비스` 최종 결과에서
  호출을 확정한다. 답변 재생 중 끼어들기는 9절의 별도 기준을 사용한다.
- 질문 구간은 처음 음절을 잃지 않도록 짧은 pre-roll을 포함한다.
- 입력 dBFS가 음성 임계값을 넘으면 발화가 시작된 것으로 본다.
- 발화 시작 뒤 설정된 연속 무음 시간이 지나면 질문을 끝낸다.
- 최대 15초가 되면 강제로 종료해 메모리 사용과 대기를 제한한다.
- 음성이 시작되지 않았거나 최소 발화 길이에 못 미치면 인식기로 보내지 않는다.

콘솔의 입력 dBFS는 사용자가 마이크 거리·Windows 입력 볼륨·무음 임계값을 조절하는
진단 정보다. 이 값과 부분 문장은 파일 로그에 저장하지 않는다.

## 5. 품질 가드

Whisper 결과는 다음 조건을 모두 통과해야 Ollama로 전달한다.

1. 공백을 제거한 최종 한국어 문장이 비어 있지 않다.
2. 실제 음성 길이가 설정된 최소 길이 이상이다.
3. segment의 평균 log probability가 설정 하한 이상이다.
4. no-speech probability가 설정 상한 이하이다.

실패는 프로그램 오류가 아니다. 화면에 실패 이유를 짧게 표시하고
“잘 듣지 못했습니다. 다시 말씀해 주세요.”를 로컬 TTS로 안내한 뒤 호출 대기로 돌아간다.
낮은 품질 문장을 추측해서 실행 명령으로 사용하지 않는다.

현재 기본값:

| 항목 | 기본값 | 조정 기준 |
|------|--------|-----------|
| 질문 음성 임계값 | `-42 dBFS` | 말해도 `대기`면 `-45`·`-48`, 잡음이 음성이면 `-39`·`-36` |
| pre-roll | `500 ms` | 첫 음절이 잘리면 늘림 |
| 연속 무음 종료 | `900 ms` | 문장 중간에 끊기면 1,100~1,300ms로 늘림 |
| 최소 음성 | `400 ms` | 짧은 명령이 거부되면 로그를 확인한 뒤만 낮춤 |
| 최소 평균 log probability | `-1.0` | 더 작은 값은 불확실한 결과로 거부 |
| 최대 no-speech probability | `0.6` | 더 큰 값은 무음 가능성이 높아 거부 |
| 최대 질문 길이 | `15 s` | 메모리·대기 상한이므로 임의로 크게 늘리지 않음 |

값은 `D:\Jarvis\config\settings.yaml`의 `voice.stt.command`에서 조정한다. 한 번에
하나만 바꾸고 같은 세 문장을 다시 말해 전후 결과를 비교한다.

## 6. 개인정보와 보안

- 원본 PCM과 Whisper용 float 배열은 메모리 안에서만 변환한다.
- 녹음 파일, 임시 WAV, 외부 STT API를 만들지 않는다.
- 최종 transcript만 기존 raw 선저장·Privacy Gate 규칙에 따라 처리한다.
- 음성 채널은 High 위험 작업을 승인할 수 없다.
- secret 또는 pii_high 답변은 TTS로 읽지 않는다.

## 7. 설치와 실행

PowerShell 실행 정책과 무관하게 가상환경 Python을 직접 호출한다.

```powershell
cd D:\Ai\Jarvis
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\python.exe scripts\setup_voice.py
.\.venv\Scripts\python.exe -m app --voice
```

첫 설치에는 Vosk와 Whisper 모델 다운로드가 필요하다. 설치가 끝난 뒤 음성 인식과
답변은 loopback Ollama를 포함해 모두 로컬에서 동작한다.

## 8. 실장치 점검

1. `[마이크 켜짐]`에 `USB Condenser Microphone`이 선택됐는지 확인한다.
2. 말할 때 입력 dBFS가 무음보다 뚜렷하게 커지는지 확인한다.
3. “자비스” 호출 뒤 안내 음성이 끝난 다음 0.2초 정도 쉬고 질문한다.
4. `[Whisper 확정]` 문장을 보고 실제 발화와 비교한다.
5. 세 문장 이상 반복해 누락, 엉뚱한 단어, 첫 음절 손실 여부를 확인한다.

권장 점검 문장:

- “오늘 날짜를 알려줘.”
- “파이썬으로 무엇을 만들 수 있어?”
- “자비스 프로젝트의 다음 개발 단계를 알려줘.”

마이크는 입에서 15~30cm 떨어뜨리고 Windows 입력 볼륨이 너무 커서 포화되지 않게 한다.
정확도 조정은 모델을 임의로 교체하기 전에 dBFS, 무음 임계값, 발화 종료 시간을 먼저
확인한다.

정상 질문 처리의 핵심 콘솔 예시는 다음과 같다.

```text
[마이크 켜짐] 요청을 듣고 있습니다. (장치: USB Condenser Microphone)
[마이크 음량] -31.5 dBFS · 음성 감지
[마이크 꺼짐]
[녹음 종료] 연속 무음을 감지했습니다.
[Whisper 처리] 한국어 질문을 로컬에서 인식하고 있습니다.
[Whisper 확정] 오늘 날짜를 알려줘. (평균 logprob=-0.362, 무음 확률=0.018, 장치=cuda)
```

`[Whisper 폴백]`이 보이면 CUDA 초기화에 실패해 CPU `int8`로 전환된 상태다. 기능은
계속 동작하지만 응답이 느릴 수 있다. `[인식 거부]`가 반복되면 모델을 바꾸기 전에
마이크 dBFS와 Windows 입력 볼륨을 확인한다.

## 9. 답변 중 끼어들기와 TTS 속도

답변 TTS가 재생되는 동안 Speaking 전용 적응형 게이트가 먼저 마이크 입력을 거른다.
`-32 dBFS` 이상이면서 최근 TTS 기준선보다 8dB 이상 급상승하고 WebRTC VAD가 사람
음성으로 판정한 구간만 500ms pre-roll과 함께 Vosk에 전달한다. 부분 또는 최종 결과에
`자비스`가 나타나면 즉시 중단한다. 현재 읽는 답변 자체에 `자비스`가 포함된 경우에는
스피커 소리 오인을 막기 위해 부분·긴 최종 결과를 사용하지 않고 정확한 최종 호출만
인정한다. 상세 기준은 [마이크 게이트 운영 문서](./VOICE_BARGE_IN_GATE.md)와
[D017](../00-start-here/DECISIONS.md)을 따른다.

호출 오인 방지·한 문장 “자비스 …질문”·답변 중 `ctrl+alt+j` 중단은
[VOICE_WAKE_COMMAND_UX.md](./VOICE_WAKE_COMMAND_UX.md)와
[D018](../00-start-here/DECISIONS.md)을 따른다. 호출이 확정된 뒤에는 Vosk 미리보기를
멈추고 PCM만 모아 Whisper로 인식한다. “자비스 가나다”가 “자비스 자비스”로 강제되지
않아야 한다.

사용 순서:

1. 답변 중 `[끼어들기 감시]`가 표시되는지 확인한다.
2. 마이크 가까이에서 “자비스”를 말하거나 `ctrl+alt+j`를 누른다.
3. `[말 끼어들기]` 또는 `[단축키 끼어들기]`와 `[답변 중단]`이 표시되며 재생이 종료된다.
4. 안내가 나오면 새 질문을 말한다. 한 문장으로 “자비스 …질문”을 이어서 말해도 된다.

```text
[끼어들기 감시] 답변 중 '자비스'라고 부르면 중단합니다.
[끼어들기 마이크] -28.4 dBFS · 기준 -40.1 dBFS · VAD 음성 · onset
[끼어들기 STT 부분] 자비스
[말 끼어들기] '자비스'를 감지했습니다.
[답변 중단] 새 질문을 받을 준비를 합니다.
```

`[끼어들기 마이크]`만 보이고 STT 문구가 없다면 발화가 `-32 dBFS` 이상인지,
`VAD 음성`인지, 상태가 `onset`으로 변하는지 차례로 본다. 음량이 작으면 Windows 입력
볼륨·거리를 먼저 조정하고, VAD 음성인데 onset이 없으면
`voice.barge_in.min_onset_rise_db`를 8에서 6으로 낮춰 비교한다. 그래도 작을 때만
`voice.barge_in.speech_threshold_dbfs`를 `-35` 정도로 낮춘다. 질문 녹음용
`voice.stt.command.speech_threshold_dbfs`는 바꾸지 않는다. 설정 변경 뒤에는 프로그램을
`Ctrl+C`로 종료하고 다시 실행해야 한다.

답변을 읽는 중이 아닐 때는 기존처럼 “자비스” 호출 후 질문한다.

TTS는 `D:\Jarvis\config\settings.yaml`의 `voice.tts.rate=4`를 사용한다. Heami 동일
문장의 WAV 길이를 비교했을 때 rate 0은 645,968 bytes, rate 4는 417,944 bytes로
rate 4가 약 1.55배 빨랐다. SAPI 허용 범위는 -10~10이며 더 빠르게 바꾸면 발음이
부자연스러워질 수 있다.

## 10. 현재 검증 증거

- RTX 4070 Ti에서 faster-whisper small CUDA `int8_float16` 모델 load와 forward 성공
- SAPI `Microsoft Heami Desktop`의 “오늘 날짜를 알려줘.”를 정확히 복원
- 해당 문장 품질: 평균 log probability `-0.362`, no-speech probability `0.018`
- USB Condenser Microphone에서 10초 무음 대기 중 잘못된 최종 호출 0회
- 전체 PCM·Whisper 배열 디스크 저장 0건, 임시 SAPI 스모크 파일은 검증 직후 제거
- Heami `rate=4` 실제 스피커 재생 성공, 동일 문장 기준 기본 대비 약 1.55배
- 답변 중 `자비스` 부분·최종 호출 시 SAPI cancel과 새 질문 전환 자동 테스트 통과
- 일정한 큰 TTS 에코·큰 비음성 소음에서 게이트가 열리지 않는 자동 테스트 통과
- 게이트가 닫힌 구간에서 Vosk feed 0회 자동 테스트 통과
- 읽는 답변 속 `자비스` 부분·긴 최종 결과를 사용자 끼어들기로 오인하지 않는 회귀 통과

사람의 실제 발음·거리·방 환경은 사용자 실장치 점검 문장으로 별도 확인해야 한다.
