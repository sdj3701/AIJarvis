# 결정 기록

코드가 대신 결정해서는 안 되는 선택을 기록한다. 상태는 `decided`, `pending`, `superseded` 중 하나다. 결정을 바꾸면 기존 행을 수정하지 말고 새 ID를 추가하고 이전 행을 `superseded`로 바꾼다.

## 결정 목록

| ID | 상태 | 결정 | 현재 값 | 적용 시점 | 완료 조건 |
|----|------|------|---------|-----------|-----------|
| D001 | decided | 소스 경로 | `D:\Ai\Jarvis` | Phase 0 | 고정 |
| D002 | decided | 운영 데이터 경로 | `D:\Jarvis` | Phase 0 | 고정 |
| D003 | decided | 상태 저장 | JSONL + SQLite WAL/FULL | Phase 0 | DESIGN 9장 준수 |
| D004 | decided | 패키지 관리 | `venv`, `pip`, hash lockfile | Phase 0 | bootstrap 문서화 |
| D005 | decided | LLM 런타임·모델 | `Ollama` + `qwen3.5:9b` | Phase 1 | 로컬 스모크·모델 식별자 검증 |
| D006 | pending | 검색 제공자 | 미정 | Phase 3 진입 전 | API·비용·결과 스키마 확정 |
| D007 | pending | 백업 대상 | 미정 | Phase 6 진입 전 | 별도 장치/보안 위치 경로 확정 |
| D008 | pending | 백업 암호화 도구 | 7-Zip AES-256 또는 age | Phase 6 진입 전 | 설치·복원 자동화 방식 확정 |
| D009 | decided | TTS | Windows SAPI `Microsoft Heami Desktop`, rate 6 로컬 TTS | 음성 세로 기능 | 한국어 음성·약 2배 속도·외부 전송 0 확인 |
| D010 | decided | 음성 호출 | opt-in 로컬 웨이크워드 `자비스`, PTT는 후속 보조 입력 | 음성 세로 기능 | `--voice`에서만 마이크 열림·호출 전 PCM 비저장 |
| D011 | decided | 상주 시작 | autostart 기본 false | Phase 8 | 사용자 opt-in만 허용 |
| D012 | pending | PDF parser | 미정 | Phase 3 PDF 활성화 전 | 파서·라이선스·실패 처리 확정 |
| D013 | pending | Windows 패키징 | PyInstaller 또는 대안 | Phase 8 진입 전 | 단일 빌드 방식·재현 명령 확정 |
| D014 | pending | 트레이·전역 단축키 라이브러리 | 미정 | Phase 8 진입 전 | 권한·충돌·종료 동작 검증 |
| D015 | pending | 자동 시작 설치 방식 | 시작프로그램 바로가기 또는 설치 옵션 | Phase 8 진입 전 | 레지스트리 직접 수정 없이 opt-in 구현 |
| D016 | decided | 한국어 STT | Vosk 호출어 + `faster-whisper small` 질문 인식 | 음성 세로 기능 | 로컬 처리·한국어 실장치 인식·낮은 신뢰도 재요청 확인 |

## 결정 작성 양식

새 결정이 필요하면 아래 형식으로 이 문서에 추가한다.

```text
ID:
상태:
문제:
선택지:
결정:
이유:
영향 문서/설정:
재검토 조건:
결정 날짜:
```

## D005 상세 — 로컬 LLM

- 결정 날짜: 2026-08-11
- 런타임: Ollama 0.32.6, `http://127.0.0.1:11434` 고정
- 모델: `qwen3.5:9b`, GGUF `Q4_K_M`, 9.7B, 6,594,474,711 bytes
- manifest digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- 출처: [Ollama 공식 qwen3.5:9b 모델 페이지](https://ollama.com/library/qwen3.5:9b)
- 라이선스: Apache License 2.0
- 런타임 문맥: 모델 최대치는 262,144 토큰이지만 RTX 4070 Ti 12GB 운영값은 16,384 토큰으로 제한
- 추론 모드: Phase 1 기본 `think=false`
- 라우팅: loopback Ollama만 허용하며 클라우드 LLM 폴백은 만들지 않음
- 비용: 입력·출력 단가 모두 USD 0.00. 전력비는 애플리케이션 외부 비용 예산에 포함하지 않음
- 재검토 조건: 한국어 평가 실패, 12GB VRAM 초과, 라이선스·모델 digest 변경

## D016 상세 — 로컬 한국어 STT

- 결정 날짜: 2026-08-11
- 호출어 감지: 기존 `vosk-model-small-ko-0.22`를 CPU에서 제한 문법으로 실행
- 질문 인식: `Systran/faster-whisper-small` revision `536b0662742c02347bc0e980a01041f333bce120`
- `model.bin` SHA-256: `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`
- 추론: RTX 4070 Ti에서 CUDA `int8_float16`, CUDA 초기화 실패 시 CPU `int8`로 명시적 폴백
- 언어·탐색: `language="ko"`, `task="transcribe"`, `beam_size=5`, VAD 사용
- 녹음 종료: 음성 시작 후 연속 무음과 최대 녹음 시간을 함께 적용하며, 처음 음절 보호용 pre-roll을 유지
- 품질 가드: 빈 결과·낮은 평균 log probability·높은 no-speech probability는 LLM에 전달하지 않고 다시 말해 달라고 안내
- 진단: 마이크 장치, 입력 dBFS, 녹음 상태, 최종 인식문과 품질 수치를 콘솔에 표시
- 개인정보: PCM과 Whisper 입력 배열은 제한된 메모리에서만 처리하고 파일·외부 API로 보내지 않음
- 이유: Vosk 한국어 소형 모델은 호출어처럼 짧고 제한된 어휘에는 적합하지만 자유 발화 질문 정확도가 부족하다. Whisper small은 12GB GPU에서 Ollama 9B와 병행 가능한 정확도·자원 균형을 제공한다.
- 모델 출처: [Systran faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120)
- 런타임 출처: [faster-whisper](https://pypi.org/project/faster-whisper/)
- 상세 운영 기준: [한국어 STT 운영 가이드](../reference/VOICE_STT.md)
- 재검토 조건: 한국어 실장치 문장 세트 실패, 명령 p95 지연 목표 초과, VRAM 경합 또는 모델 revision 변경

## Phase 차단 규칙

- D005가 `pending`이면 Phase 1 구현을 시작하지 않는다. 현재는 위 로컬 LLM 결정으로 해소되었다.
- D006이 `pending`이면 Phase 3의 웹 검색 구현만 차단한다. 로컬 문서 RAG는 먼저 개발할 수 있다.
- D007·D008이 `pending`이면 Phase 6 릴리스 게이트를 통과시킬 수 없다.
- D009는 외부 전송 없는 Windows SAPI 한국어 음성으로 확정되었다. 다른 TTS 엔진은 별도 결정 없이는 추가하지 않는다.
- D016은 Vosk 단독 자유 발화를 대체한다. 호출어는 Vosk, 질문은 고정 revision의 faster-whisper small만 사용하며 온라인 STT 폴백은 추가하지 않는다.
- D012가 `pending`이면 Phase 3에서 PDF 지원을 비활성화하고 `.md`·`.txt`만 제공한다.
- D013~D015가 `pending`이면 Phase 8 패키징·전역 단축키·자동 시작 구현을 시작하지 않는다.
