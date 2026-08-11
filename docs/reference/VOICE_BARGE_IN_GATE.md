# 답변 중 마이크 게이트와 사람 목소리 통과

이 문서는 TTS 재생 중 “자비스” 끼어들기가 스피커 에코에 막히거나 오인되는 문제를
줄이는 **게이트 강화 설계와 운영 기준**이다. 결정은
[D017](../00-start-here/DECISIONS.md)이며, 전체 음성 동작 설명은
[VOICE_STT.md 9절](./VOICE_STT.md)을 기준으로 한다.

상태: `implemented (S1)` — Gate A+B+WebRTC VAD 구현과 설정 반영 완료, S2 실장치 검증 대기.

## 1. 문제

현재 답변 중 끼어들기는 다음을 동시에 요구한다.

1. Speaking 전용 하한을 넘고 TTS 기준선보다 급상승한 onset이 있다.
2. WebRTC VAD가 해당 구간을 사람 음성으로 판정한다.
3. 게이트가 통과시킨 PCM에서 Vosk가 부분 또는 최종 `자비스`를 본다.
4. 읽는 답변 자체에 `자비스`가 있으면 정확한 최종 호출만 인정한다.

스피커로 TTS를 틀면 그 소리가 USB 마이크로 다시 들어온다. 그 결과:

- 사용자 “자비스”가 TTS에 가려져 STT에 안 잡히거나
- TTS만으로도 dBFS·호출어 조건이 애매해져 끊기/미끊기가 불안정하다

물리적으로 헤드셋을 쓰면 대부분 해결되지만, 스피커 사용을 전제로 한 소프트웨어
보강이 필요하다.

## 2. 목표

| 목표 | 측정 |
|------|------|
| TTS 자기 음성으로 끼어들기 오발동 감소 | 스피커 전용 재생 30초 × N회에서 false barge-in 0 |
| 사용자 근거리 “자비스”로 중단 성공 | 동일 조건에서 성공률 목표를 D017 완료 조건에 기록 |
| 외부 전송·디스크 PCM 저장 없음 | 호출 전·감시 중 PCM은 메모리 제한 버퍼만 |
| Ollama VRAM과 충돌 없음 | 게이트는 CPU/가벼운 신호처리만, Whisper는 질문 구간에만 |

비목표:

- 완전한 상용 AEC 품질 보장
- 온라인 STT/클라우드 에코 제거 API
- TTS 엔진을 온라인으로 교체

## 3. 처리 구조

```text
Speaking (SAPI 재생 중)
  → 마이크 PCM16 16 kHz mono
  → [Gate A] TTS 구간 전용 레벨 게이트
  → [Gate B] 급격한 레벨 상승(onset) 검출
  → [Gate C] WebRTC VAD 사람 음성 판정
  → 통과 프레임만 Vosk 호출어 stream에 feed
  → “자비스” → TTS cancel
  → 안내 후 Recording
```

평상시 호출 대기·질문 녹음 경로는 바꾸지 않는다. Speaking 감시 경로만 게이트를
추가한다.

## 4. 게이트 설계

### 4.1 Gate A — TTS 구간 레벨 상향

Speaking 중에는 질문 녹음용 `speech_threshold_dbfs`보다 **더 큰 소리만** 후보로 본다.

D017 기본값:

| 키 | 의미 | 기본값 |
|----|------|--------|
| `voice.barge_in.speech_threshold_dbfs` | Speaking 중 사람 후보 하한 | `-32` |
| `voice.barge_in.recent_speech_ms` | onset 이후 인정 창 | `800` |
| `voice.barge_in.min_onset_rise_db` | 직전 창 대비 상승량 | `8` |
| `voice.barge_in.baseline_window_ms` | TTS 에코 기준창 | `500` |
| `voice.barge_in.startup_guard_ms` | SAPI 시작 어택 무시 구간 | `750` |
| `voice.barge_in.pre_roll_ms` | 호출 첫 음절 보존 구간 | `500` |

질문 녹음의 `-42`를 Speaking에 그대로 쓰면 스피커 잔향도 “최근 큰 입력”으로 통과하기
쉽다. Speaking 전용 임계값을 분리한다.

### 4.2 Gate B — onset(급상승)만 STT에 넣기

매 프레임 dBFS만 보지 않고, 짧은 기준창의 중앙값보다
`min_onset_rise_db` 이상 갑자기 커진 구간만 “사람 말 시작”으로 본다.

확정 규칙:

1. TTS 재생 시작 후 처음 750ms는 게이트를 닫아 SAPI 시작 지연·재생 어택을 무시한다.
2. 기준창 레벨을 슬라이딩으로 갱신한다.
3. Speaking 전용 하한·상승량·VAD를 모두 통과한 onset에서만 게이트를 연다.
4. onset 전 메모리 pre-roll과 그 직후 `recent_speech_ms` 동안만 Vosk `feed`를 허용한다.
5. onset 밖 PCM은 폐기하고 STT에 넣지 않는다. 게이트가 닫힐 때 Vosk 상태도 초기화한다.

콘솔 진단 예:

```text
[끼어들기 마이크] -28.4 dBFS · 기준 -40.1 dBFS · VAD 음성 · onset
[끼어들기 STT 부분] 자비스
[말 끼어들기] '자비스'를 감지했습니다.
```

onset이 없으면 `[끼어들기 마이크] … · 감시 중`만 보이고 STT 미리보기는 갱신하지 않는다.

### 4.3 Gate C — WebRTC VAD

`webrtcvad-wheels==2.0.14`를 사용한다. 250ms 마이크 프레임을 지원 형식인 20ms
subframe으로 나누고, 30% 이상이 음성이면 사람 음성 후보로 판정한다. 기본 mode는 2다.

VAD는 키보드 충격·팬 소음 같은 비음성을 줄이는 필터다. TTS도 사람 음성처럼 판정될 수
있으므로 VAD만으로 사용자와 스피커를 구별하지 않는다. Gate A의 근거리 하한과 Gate B의
적응형 onset을 반드시 함께 적용한다. 등록된 사용자 본인만 허용하는 화자 인증도 이번
범위에는 포함하지 않는다.

### 4.4 소프트웨어 AEC와 빔포밍 (선택, 후순위)

Windows에서 완벽한 루프백 AEC는 장치·드라이버 의존이 크다. 현재 SAPI 프로세스는
스피커로 직접 재생하므로 AEC가 요구하는 reverse PCM 기준 신호를 애플리케이션에 주지
않는다. S1은 A/B/VAD로 운영하고, 스피커 실장치 목표에 미달할 때만 AEC를 검토한다.

검토 후보(결정 전 실험만):

| 후보 | 장점 | 리스크 |
|------|------|--------|
| WASAPI loopback으로 TTS 출력 추정 후 감산 | 실제 재생 파형 참조 | 장치 권한·지연 보정·구현량 |
| 단순 adaptive filter (NLMS 등) | 로컬·경량 | 튜닝 어렵고 실패 시 왜곡 |
| OS/마이크 “에코 제거” 토글 안내 | 구현 0 | 장치마다 효과 불균일 |

AEC를 넣을 경우에도 PCM은 메모리에만 두고, loopback·마이크 원문을 디스크나 외부로
보내지 않는다.

현재 `USB Condenser Microphone`은 mono 한 채널로 연다. 빔포밍은 두 개 이상의 마이크
채널과 배열 위치 정보가 필요하므로 현재 장치에는 적용하지 않는다. 다채널 마이크 배열을
도입한 뒤 별도 장치 프로파일로 재검토한다.

### 4.5 기존 호출어 규칙과의 관계

| 규칙 | 유지 여부 |
|------|-----------|
| 호출어는 Vosk, 질문은 Whisper | 유지 |
| 답변 문장에 `자비스` 포함 시 부분 결과 제한 | 유지 |
| 최근 loud 입력 필요 | Gate A/B/VAD로 대체·강화 |
| 온라인 STT 폴백 | 금지 유지 |

## 5. 모듈 경계

기준 인터페이스는 [DESIGN 음성·UI 계약](../../DESIGN.md)을 따른다. 새 공개 엔진
타입을 `voice` 밖으로 노출하지 않는다.

구현 파일:

```text
app/voice/barge_in_gate.py   # onset·임계값·pre-roll·WebRTC VAD 순수 로직
app/voice/controller.py      # wait_for_barge_in에서 gate 경유 feed
tests/unit/test_barge_in_gate.py
```

`LocalVoiceListener.wait_for_barge_in`은 게이트가 통과시킨 PCM만 recognizer에 넣는다.
게이트는 프레임 in / 통과 여부·진단 레벨 out만 다루고, Vosk·SAPI를 직접 호출하지 않는다.

## 6. 설정·이벤트

D017 결정에 따라 아래 항목을 함께 동기화했다.

1. `config/settings.example.yaml`의 `voice.barge_in.*`
2. 설정 모델·로더 검증
3. [SCHEMAS.md](../../SCHEMAS.md)의 `voice.barge_in` payload 확장
   필드: `gate`, `onset`, `level_dbfs`, `baseline_dbfs`, `gate_frames`, `voice_frames`
4. [TESTING.md](../../TESTING.md) / Phase 7 게이트 항목
5. [VOICE_STT.md 9절](./VOICE_STT.md) 운영 문구

## 7. 검증 계획

자동 검증 완료:

- [x] TTS 에코처럼 일정하고 큰 레벨만 있는 가짜 PCM → gate closed
- [x] 기준창 대비 급상승 + VAD 음성 → pre-roll과 현재 프레임 통과
- [x] 큰 비음성 소음 → gate closed
- [x] 답변 문장에 `자비스`가 있을 때 부분·긴 최종 결과로 true 금지
- [x] 게이트 닫힌 구간에서는 recognizer에 feed 0회

실장치(사람):

1. 스피커로 긴 답변 재생, 사용자는 침묵 → 오발동 0
2. 마이크 가까이에서 “자비스” → 중단·안내·새 질문
3. 헤드셋 재생에서도 동일하게 동작 (회귀)

## 8. 단계적 도입

| 단계 | 내용 | 완료 조건 |
|------|------|-----------|
| S1 | Gate A+B+WebRTC VAD, 설정, 단위 테스트 | **완료** — 가짜 PCM 오발동 0·onset 성공 |
| S2 | 실장치 스피커 스모크, 임계값 조정 | D017 완료 조건의 성공률 |
| S3 | 필요 시에만 AEC 실험 보고서 | AEC 채택/기각을 DECISIONS에 기록 |

S2에서 목표 성공률이 나오면 AEC는 기본 경로에 넣지 않는다.

## 9. 운영과 튜닝

기본값으로 먼저 실장치 테스트하고 아래 순서로 조정한다.

1. `[끼어들기 마이크]`에서 사용자 발화가 `-32 dBFS` 이상인지 확인한다.
2. `VAD 음성`이 표시되지만 onset이 없으면 `min_onset_rise_db`를 8에서 6으로만 낮춰 본다.
3. 사용자 음량 자체가 작으면 Windows 입력 볼륨·거리부터 조정한 뒤 하한을 `-35`로 낮춘다.
4. 오발동이 생기면 반대로 하한·상승량·VAD mode를 한 항목씩 높인다.
5. 물리적 완화가 필요하면 TTS를 헤드셋으로 듣고 마이크를 스피커에서 멀리 둔다.

질문 녹음용 `voice.stt.command.speech_threshold_dbfs`와 Speaking 전용
`voice.barge_in.speech_threshold_dbfs`는 분리되어 있다. 끼어들기 때문에 질문 녹음 값을
바꾸지 않는다. 설정은 한 번에 하나만 바꾸고 프로그램을 재시작해 비교한다.

## 10. 관련 문서

- [VOICE_STT.md](./VOICE_STT.md) — 현재 STT·끼어들기 운영
- [Phase 7](../phase-07-voice/README.md) — 음성 Phase 체크리스트
- [DECISIONS D017](../00-start-here/DECISIONS.md) — 게이트 채택 여부
- [DOCUMENTATION_RULES.md](./DOCUMENTATION_RULES.md) — 기준 문서 수정 순서
