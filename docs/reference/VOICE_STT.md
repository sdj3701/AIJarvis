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
