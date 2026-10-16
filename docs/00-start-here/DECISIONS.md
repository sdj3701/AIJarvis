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
| D006 | decided | 검색 제공자 | DuckDuckGo (`ddgs`) | Phase 3 | FakeSearchProvider 테스트·실장치 allow_network 스모크 |
| D007 | decided | 백업 대상 | `D:\JarvisBackups` (운영 루트와 분리된 디렉터리 또는 외부 드라이브) | Phase 6 | 격리 디렉터리 복원 검증 |
| D008 | decided | 백업 암호화 도구 | AES-256 암호화 아카이브 (키는 Windows Credential Manager `backup_key`에서 획득) | Phase 6 | 백업 생성 및 복원 자동화 통과 |
| D009 | decided | TTS | Windows SAPI `Microsoft Heami Desktop`, rate 4 로컬 TTS | 음성 세로 기능 | 한국어 음성·약 1.5배 속도·외부 전송 0 확인 |
| D010 | decided | 음성 호출 | opt-in 로컬 웨이크워드 `자비스`, PTT는 후속 보조 입력 | 음성 세로 기능 | `--voice`에서만 마이크 열림·호출 전 PCM 비저장 |
| D011 | decided | 상주 시작 | autostart 기본 false | Phase 8 | 사용자 opt-in만 허용 |
| D012 | decided | PDF parser | 로컬 pdfplumber 0.11.9 (MIT) | 2026-10-15 PDF 적용 | 텍스트 PDF·상한·실패/캐시/구조 회귀 |
| D013 | pending | Windows 패키징 | PyInstaller 또는 대안 | Phase 8 진입 전 | 단일 빌드 방식·재현 명령 확정 |
| D014 | pending | 트레이·전역 단축키 라이브러리 | 미정 | Phase 8 진입 전 | 권한·충돌·종료 동작 검증 |
| D015 | pending | 자동 시작 설치 방식 | 시작프로그램 바로가기 또는 설치 옵션 | Phase 8 진입 전 | 레지스트리 직접 수정 없이 opt-in 구현 |
| D016 | decided | 한국어 STT | Vosk 호출어 + `faster-whisper small` 질문 인식 | 음성 세로 기능 | 로컬 처리·한국어 실장치 인식·낮은 신뢰도 재요청 확인 |
| D017 | decided | 답변 중 끼어들기 마이크 게이트 | Gate A+B+WebRTC VAD, AEC·빔포밍 후순위 | 음성 세로 기능 | 스피커 에코 오발동 0·근거리 “자비스” 중단 성공률·설정 키 확정 |
| D018 | decided | 호출 오인 방지·한 문장 호출+명령·답변 중단 핫키 | `[unk]`+접두 판정, 한 문장 Whisper, 핫키+D017 | 음성 세로 기능 | 오호출 감소·한 문장 경로·`ctrl+alt+j` 중단 |
| D019 | decided | v2 재구축 데이터 격리 | 개발 중 `D:\Jarvis-v2-dev`, 프로토타입 `D:\Jarvis` 접근 금지 | `rebuild/v2` 전체 | 기본 bootstrap·실행·테스트 경로 분리 확인 |
| D023 | decided | RAG 책임·근거 없는 답변 정책 | 문서 준비/질문 준비/검색/생성 분리, 일반 지식과 내부 사실의 폴백 분리 | 2026-10-14 설계 | R3-01~08 구현·검증은 별도 |
| D024 | decided (개발 기본값) | RAG 청크·문맥·갱신 | 384/48토큰, 이웃 1, 문서당 6, 검색 시 5초 확인 | R3-03~08 실제 합성 비교 | 실무 최적값은 미확정; 아래 제한 참조 |

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

## D006 상세 — 웹 검색 제공자 (decided)

- 결정 날짜: 2026-08-11
- 제공자: DuckDuckGo 검색 결과 (`ddgs` 패키지, 지역/언어 `kr-kr` / `ko-kr` 기본)
- API 키: 불필요
- 비용: `settings.rag.search.cost_per_request = "0.00"` (USD)
- 결과 매핑: title, URL, snippet, published_at(없으면 null), fetched_at(요청 시각)
- 테스트: 단위·통합은 `FakeSearchProvider`만 사용. 실네트워크는 `pytest -m allow_network`
- 이유: 하이브리드·로컬 우선 전략에서 API 키·유료 검색 없이 MVP 웹 근거를 연결할 수 있다.
  PLAN의 Tavily 예시는 유료 키가 필요해 기본값으로 두지 않았다.
- 재검토 조건: DDG 차단·품질 저하, 한국어 결과 부실, ToS 변경. 그때 Brave/Tavily 등으로 교체

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

## D017 상세 — 답변 중 마이크 게이트 (decided)

- 문제: 스피커 TTS가 마이크로 들어가 끼어들기(“자비스”)가 실패하거나 불안정함
- 설계·운영 문서: [답변 중 마이크 게이트와 사람 목소리 통과](../reference/VOICE_BARGE_IN_GATE.md)
- 결정: Speaking 전용 임계값 + 적응형 onset + 메모리 pre-roll + WebRTC VAD를 먼저
  적용하고, 이 게이트가 통과시킨 PCM만 Vosk에 전달한다.
- 기본값: `-32 dBFS`, 기준창 `500ms`, onset 상승 `8dB`, 시작 보호 `750ms`,
  통과창 `800ms`, pre-roll `500ms`, WebRTC VAD mode 2/20ms/비율 0.3
- AEC 보류 이유: 현재 Windows SAPI가 스피커로 직접 재생해 reverse PCM 기준 신호를
  제공하지 않는다. 실장치 S2에서 목표 미달일 때 메모리 PCM 재생 구조와 loopback을
  별도 실험한다.
- 빔포밍 보류 이유: 현재 USB Condenser Microphone은 단일 입력 채널로 열리며 마이크
  배열의 채널·위치 정보가 없다. 다채널 장치 도입 뒤 재검토한다.
- 주의: WebRTC VAD는 비음성 소음을 거르는 장치이며 등록 사용자 화자 인증은 아니다.
- 재검토 조건: 스피커 실장치에서 S1 게이트로 목표 미달, 또는 AEC 없이 운영 불가능 판정

## D018 상세 — 호출 오인 방지·한 문장 명령·답변 중단 핫키 (decided)

- 결정 날짜: 2026-08-11
- 문제:
  1. 마이크에 아무 말이나 들어가면 “자비스”로 오인
  2. 답변 중 “자비스” 재호출이 잘 안 됨
  3. “자비스”와 질문을 한 문장으로 말해도 안내 TTS 후 질문을 다시 해야 함
- 제안서: [호출 오인·한 문장 명령·답변 중 재호출](../reference/VOICE_WAKE_COMMAND_UX.md)
- 결정: 선택지 1 + 답변 중 끊기 D(핫키 + D017 유지, AEC 후순위)
  1. Vosk 호출 문법에 `[unk]` 포함, 호출어 단독/접두만 인정
  2. 같은 마이크 세션 PCM을 Whisper로 인식해 선두 호출어를 제거한 나머지가 있으면
     안내 TTS를 생략하고 바로 질문에 응답
  3. 답변 TTS 중 `voice.barge_in.interrupt_hotkey`(기본 `ctrl+alt+j`)로 즉시 중단,
     음성 “자비스” 감시는 D017 게이트와 병행
- D010 관계: 웨이크워드 opt-in·PCM 비저장 유지. 호출 후 항상 안내 TTS를 재생하던
  고정 순서는 한 문장 명령이 있을 때 생략할 수 있게 개정한다
- 후속 수정(P4): 호출 확정 뒤에는 Vosk를 feed하지 않고 PCM→Whisper만 사용한다.
  “자비스 가나다”가 제한 문법 때문에 “자비스 자비스”로 보이던 문제를 막는다.
  상세: [VOICE_WAKE_COMMAND_UX.md P4](../reference/VOICE_WAKE_COMMAND_UX.md)
- 재검토 조건: 오호출 목표 미달, 한 문장 경로 첫 음절 손실, 핫키 충돌, Whisper 지연 초과,
  호출 후 후속어가 다시 호출어로 강제되는 회귀

## Phase 차단 규칙

- D005가 `pending`이면 Phase 1 구현을 시작하지 않는다. 현재는 위 로컬 LLM 결정으로 해소되었다.
- D006은 DuckDuckGo(`ddgs`)로 해소되었다. 자동 테스트는 FakeSearchProvider만 쓰고
  실네트워크는 allow_network 스모크로만 검증한다.
- D007·D008이 `pending`이면 Phase 6 릴리스 게이트를 통과시킬 수 없다.
- D009는 외부 전송 없는 Windows SAPI 한국어 음성으로 확정되었다. 다른 TTS 엔진은 별도 결정 없이는 추가하지 않는다.
- D016은 Vosk 단독 자유 발화를 대체한다. 호출어는 Vosk, 질문은 고정 revision의 faster-whisper small만 사용하며 온라인 STT 폴백은 추가하지 않는다.
- D017은 Gate A+B+WebRTC VAD로 해소되었다. AEC는 S2 실장치 결과가 목표에 미달할
  때만 별도 결정으로 추가한다.
- D018은 `[unk]`·접두 호출 판정·한 문장 명령·답변 중단 핫키로 해소되었다. AEC는
  D017과 동일하게 실장치 목표 미달 시에만 별도 결정한다.
- D012는 사용자 PDF 구현 요청에 따라 해소했다. 텍스트 PDF를 지원하며 OCR/복잡한 레이아웃은 별도다.
- D013~D015가 `pending`이면 Phase 8 패키징·전역 단축키·자동 시작 구현을 시작하지 않는다.

## D022: 명령 의미의 영구 저장 (2026-09-09)

상태: decided. 사용자 요청에 따라 기존 SQLite에 앱 실행 명령 예시와 실제 로컬 문장
임베딩을 저장하고 재사용한다. 새 유사 표현은 의미 확인을 거치며 실행 권한과 분리한다.
가중치 재학습이 아닌 확인 사례 축적이며 종료·파일 작업 학습은 별도 확장 범위다.

## D021: 영구 응답 룰북 (2026-09-09)

상태: decided. 사용자 요청에 따라 소스 파일 기반 룰북과 기본 한 문장·100자 결론을 적용한다.
프로세스 시작 시 검증하고 요청마다 같은 스냅샷을 적용하며 상세/음성을 분리한다.
안전·개인정보·승인은 스타일보다 우선하고 긴 답변의 추가 모델 요약은 하지 않는다.
개발 구현은 적용하되 실장치 낭독 비교를 운영 출시 검증에 남긴다.

## D020: 앱 탐색과 저장 승인 결정 (2026-09-09)

ID: D020 · 상태: decided · 근거: 사용자의 최초 1회 승인·저장·자동 탐색 구현 요청.

앱 최초 실행 승인은 SID·정규 경로·SHA-256에 한정해 영구 보관한다.
정적 app_map도 예외가 아니며, 종료 권한과 공유하지 않는다. 업데이트는 재승인한다.
권한 DB는 기억 DB/탐색 캐시와 분리하며 손상 시 자동 초기화하지 않는다.
상세 계약: [앱 자동 탐색과 최초 실행 승인 저장](../post-v1/PROPOSAL_APP_DISCOVERY_AND_SAVED_APPROVAL.md).


## D023 상세 — RAG 책임과 답변 정책 (2026-10-14)

- 상태: decided **개발 설계**. 사용자의 구조 재검토·개발 문서 전반 개정 요청을 반영한 기본안이다.
- 트랜스포머는 신경망의 한 종류이며 Q/K/V·FFN·concat은 모델 내부 연산이다.
  RAG 문서 탐색은 외부 색인의 키워드/벡터 검색과 재정렬로 수행한다.
- 기존 embeddinggemma·sqlite-vec/FTS5·RRF·Cross-Encoder·Qwen/Ollama 기반을 유지한다.
- 문서 준비, 질문/문맥 준비, 문서 탐색, 생성/검사를 분리한다. 현재 구현과 목표 설계를 구분한다.
- 근거가 없는 일반 지식 답변은 같은 로컬 모델로 생성하고 일반 답변임을 표시한다.
  내부 회사/개인 사실은 자료가 없으면 보류하며 오류·상충을 일반 답변으로 덮지 않는다.
- 일반 답변과 과거 AI 대화를 검증된 문서 지식으로 자동 승격하지 않는다.
- 영향: DESIGN 16장, SCHEMAS 13장, TESTING 13장, Phase 3 R3-01~08.
- 이번 결정은 문서 설계이며 코드 적용·데이터 전환·배포가 완료됐다는 뜻이 아니다.

## D024 상세 — R3 개발 기본값 (2026-10-14)

사용자의 R3 순차 구현 요청 범위에서 실행 가능한 기본값을 정했다. 실무 최적값이나 사용자 운영 튜닝 완료로 해석하지 않는다.

- 청크 384토큰, overlap 최대 48토큰; 기존 1200/150자 보조 상한 유지.
- 2026-10-15 사용자 요청에 따라 문서/질문 목적별 경로를 명시하고 `recursive-context-v2`를 적용.
  문서는 절/문단을 보존하며 초과 부분만 재귀 분할; 질문은 전체 임베딩. 겹침은 완전한 분할 단위가
  들어갈 때만 사용한다. 크기 기본값은 유지하고 PDF parser(D012) 선택과는 분리한다.
- 이웃 반경 1, 문서당 최대 6, 전체 최대 6, 재정렬 후보 24·입력 512 유지.
- 시작 및 /index, 검색 시 마지막 확인 후 5초가 지났으면 파일 해시 검사. 상시 watcher는 추가하지 않음.
- 원문·FTS·벡터는 주 DB의 세대로 원자 게시. semantic DB는 복구 가능한 사본으로 정의.
- 합성 11질의에서 256/384/512 모두 Hit@1=9/11, Hit@5=11/11이었다.
  384는 검증된 중간 개발값이며 품질 최적값이라는 증거는 없다. 실제 최대 토큰과 청크 수는 결과 JSON에 보존.
- 초기 임베딩 cache/실행 순서가 달라 build_ms로 청크값 간 속도 우열을 단정하지 않는다.
- 한국어 중심 소표본이다. 다양한 실무 표/코드·대규모 문서, 인수 환경에서 추가 평가가 필요하다.
- 설정 모델·예제·SCHEMAS·새 회귀를 함께 적용했다. 기존 운영 YAML의 명시값은 변경하지 않았다.

근거: [R3 구현 보고](../rag/RAG_R3_IMPLEMENTATION.md), [검색 비교](../../artifacts/evaluations/rag-r3-20261014/retrieval-final/retrieval_report.json).


## D012 상세 — 텍스트 PDF 추출 (2026-10-15)

사용자의 PDF 추출·머리말/꼬리말 제거·법령 구조 보존 적용 요청 범위에서
pdfplumber 0.11.9를 선택했다. [공식 문서·MIT 라이선스](https://github.com/jsvine/pdfplumber).
페이지별 문자 좌표를 제공하므로 반복 여백 제거와 원본 페이지 연결에 사용한다.
외부 전송·OCR·생성 모델 재작성 없이 로컬에서 처리한다. 버전은 pyproject와 hash lockfile에 고정한다.
손상/암호화 PDF는 읽기 오류, 이미지뿐인 페이지는 OCR 필요로 표시한다. 기본 300쪽/추출 200만자 상한을 둔다.
구 파일 갱신 실패 시 이전 완전한 색인을 보존하고 오래된 근거임을 표시한다.
새 chunker 정책은 recursive-context-v3이며 이전 D024 크기 설정은 유지한다.
[구현·시험·제한](../rag/RAG_PDF_INGESTION.md).


### D024 보완 — 인용과 짧은 조문 packing (2026-10-15)

재귀 정책 v4. 같은 장의 짧은 조문 최대 4개 packing, 개별 1/4 예산·전체 토큰/문자 상한 검사.
큰 조문은 재귀 분할을 유지하고 검색 시 조문 첫 청크를 전제 문맥으로 보충한다.
인용은 passage ID 선택 후 앱의 원문·위치 렌더링, 복합 질문은 항목별 검색·검증을 적용한다.
[인용 개선 보고](../rag/RAG_CITATION_FIXES.md)의 동일 PDF 비교와 TC 1·2를 검증 근거로 사용한다.
