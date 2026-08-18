# 음성 소스 필터 (음악 + Soft 본인 목소리)

이 문서는 배경 음악과 타인 발화를 **Soft UX 필터**로 조용히 무시하는 설계·운영 기준이다.
결정은 [D019](../00-start-here/DECISIONS.md)이며, 기존 끼어들기 게이트는
[VOICE_BARGE_IN_GATE.md](./VOICE_BARGE_IN_GATE.md)(D017)를 유지한다.

상태: `implemented (S1+S2+S3-defaults)` — 단위·설정·enrollment·스키마 동기화 완료.
초기 운영 임계값은 아래 기본값으로 고정했고, 실장치 측정표로 한 항목씩만 조정한다.

## 1. 문제

WebRTC VAD는 사람 음성 후보만 고른다. 그 결과:

- 노래·반주가 “음성”으로 남아 호출어가 오인될 수 있다
- 근처에 있는 다른 사람이 “자비스”라고 말해도 동일하게 통과한다

완전한 생체 인증은 Phase 7 비목표다. 대신 Soft 필터로 오호출·오질문을 줄인다.

## 2. 목표와 비목표

| 목표 | 측정 |
|------|------|
| 배경 음악만 있을 때 웨이크 오발동 감소 | 음악 픽스처/실장치에서 soft ignore |
| 등록 화자와 뚜렷이 다른 목소리 무시 | enrollment 대비 cosine ≤ `other_reject_threshold` |
| 애매한 점수는 통과 | `unknown`은 accept (오거부보다 오수락) |
| 모델 부재 시 기존 동작 유지 | fail-open + 경고 1회 |
| PCM 비저장 | 분석 창·enrollment 원음은 메모리만, 프로필은 embedding만 |

비목표:

- 음성 생체 인증 / High 도구 승인 대체
- 클라우드 화자·음악 API
- 하드 거부 안내(“인증 실패”) UX

## 3. 처리 구조

```text
Mic PCM
  → (Speaking 경로만) Gate A+B+C (D017)
  → Gate D 음악/말 점수
  → Gate E Soft 화자 점수 (프로필 있을 때만)
  → accept → Vosk/Whisper
  → music | other_speaker → 조용히 무시, 계속 청취
```

훅 지점:

1. **wake** — Vosk가 standalone/prefix 후보를 낸 직후, 확정 전
2. **barge_in** — “자비스” 인식 직후, TTS cancel 전
3. **command** — Whisper 호출 직전 (capture frames)

분석은 후보가 뜬 뒤에만 `analysis_window_ms`(기본 1200ms) 최근 PCM으로 수행한다.
매 프레임 상시 추론하지 않는다.

## 4. 판정 규칙

### 4.1 Gate D — 음악

입력 창에서 `music_score`, `singing_score`, `speech_score` ∈ [0, 1]을 얻는다.

거절(`music`) 조건:

- `max(music_score, singing_score) >= music_reject_threshold`
- 그리고 `speech_score < max(music, singing) - speech_margin`

그 외는 말 후보로 Gate E로 넘긴다.

구현:

- 기본: 로컬 스펙트럼 휴리스틱(`SpectralSpeechMusicClassifier`) — 추가 모델 파일 불필요
- 선택: `models/yamnet/yamnet.onnx`가 있고 `onnxruntime`이 있으면 ONNX 태그거 우선

### 4.2 Gate E — Soft 화자

enrollment 평균 embedding과 현재 창 embedding의 cosine 유사도 `speaker_score`:

| 조건 | label | accept |
|------|-------|--------|
| `speaker_score >= owner_accept_threshold` | `owner` | yes |
| `speaker_score <= other_reject_threshold` | `other_speaker` | no |
| 그 사이 | `unknown` | yes (Soft) |

프로필 파일이 없거나 화자 모델 로드 실패 시 Gate E는 건너뛴다(음악 게이트만 적용).

### 4.3 Fail-open

음악·화자 분류기 로드/추론 예외 시 해당 게이트를 끄고 통과시킨다. 콘솔에 경고를
세션당 1회만 남긴다. Soft 필터 장애가 음성 경로 전체를 막지 않는다.

## 5. Enrollment

```powershell
python scripts\enroll_voice.py --config D:\Jarvis\config
```

1. 짧은 문장 5회를 마이크에서 녹음한다 (기본 문구에 “자비스” 포함).
2. ECAPA 임베딩을 뽑아 L2 정규화 평균 벡터만 `paths.data_root` /
   `voice.source_filter.profile_path`에 저장한다 (`.npz`).
3. 원본 PCM은 즉시 폐기한다. 디스크에 wav를 남기지 않는다.

재등록은 같은 명령으로 덮어쓴다. 삭제 시 프로필 파일만 지우면 Gate E가 비활성화된다.

## 6. 설정

`settings.voice.source_filter`:

| 키 | 기본 | 의미 |
|----|------|------|
| `enabled` | `true` | 필터 마스터 스위치 |
| `music_enabled` | `true` | Gate D |
| `speaker_enabled` | `true` | Gate E (프로필 없으면 자동 skip) |
| `music_reject_threshold` | `0.45` | 음악/노래 거절 하한 |
| `speech_margin` | `0.05` | speech가 music보다 이만큼 낮아야 거절 |
| `owner_accept_threshold` | `0.60` | 본인 수락 |
| `other_reject_threshold` | `0.30` | 타인 거절 (이하면 ignore). Soft라 unknown 구간을 넓게 둠 |
| `analysis_window_ms` | `1200` | 분석 PCM 창 |
| `profile_path` | `voice/speaker_profile.npz` | data_root 상대 |
| `yamnet_model_path` | `models/yamnet/yamnet.onnx` | 선택 ONNX |
| `ecapa_model_dir` | `models/spkrec-ecapa-voxceleb` | SpeechBrain 캐시 |

`owner_accept_threshold`는 반드시 `other_reject_threshold`보다 커야 한다.

## 7. 모듈 경계

```text
app/voice/source_filter.py   # 정책·분류·매처·SourceFilter
app/voice/enrollment.py      # 프로필 load/save, PCM→embedding
scripts/enroll_voice.py      # 대화형 등록
tests/unit/test_source_filter.py
tests/fakes/audio_source.py
```

`LocalVoiceListener`는 `SourceFilter.classify`의 `accept`/`label`만 본다.
엔진 타입을 `voice` 밖으로 노출하지 않는다.

이벤트 `voice.source_filter` payload:

- `path`: `wake` | `barge_in` | `command`
- `label`, `accept`, `reason`
- `music_score`, `speaker_score` (없으면 null)
- PCM·원문 텍스트 없음

## 8. 실장치 측정표 (S3)

각 조건 10회 권장. 임계값은 한 항목씩만 바꾼다.

| 시나리오 | 기대 |
|----------|------|
| 배경 음악만 | soft ignore (music) |
| 음악+가사 | soft ignore 또는 unknown 통과(실측 기록) |
| 본인 “자비스” | accept |
| 타인 “자비스” | soft ignore (other_speaker) |
| 본인+약한 배경음악 | accept 유지율 기록 |
| 웨이크 경로 지연 | 필터 p95를 콘솔/이벤트로 기록 |

S3 동기화(2026-08-12): 초기 운영 임계값을 `settings.example.yaml` /
`SourceFilterSettings` / D019 / 이 문서에 동일한 기본값으로 고정했다.
실측 후 값을 바꿀 때는 세 곳과 SCHEMAS 설명을 함께 갱신한다.

## 9. 관련 문서

- [DECISIONS D019](../00-start-here/DECISIONS.md)
- [VOICE_BARGE_IN_GATE.md](./VOICE_BARGE_IN_GATE.md)
- [VOICE_STT.md](./VOICE_STT.md)
- [Phase 7](../phase-07-voice/README.md)
