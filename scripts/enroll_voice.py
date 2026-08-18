"""Record short utterances and store an owner speaker embedding profile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.loader import DEFAULT_CONFIG_DIR, load_config
from app.voice.base import AudioFrame
from app.voice.enrollment import (
    TorchEcapaSpeakerEmbedder,
    build_profile_from_frames,
    save_speaker_profile,
)
from app.voice.microphone import MicrophoneStream, SpeechCapture, SpeechCapturePolicy

DEFAULT_PHRASES = (
    "자비스",
    "자비스 오늘 일정 알려줘",
    "안녕하세요 자비스",
    "자비스 메모장 열어줘",
    "내 목소리 등록 테스트입니다",
)
MIN_PEAK_DBFS = -42.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis Soft 화자 프로필 등록")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_DIR,
        help="settings.yaml이 있는 설정 디렉터리",
    )
    parser.add_argument(
        "--utterances",
        type=int,
        default=5,
        help="녹음할 문장 수 (기본 5)",
    )
    return parser


def _resolve(data_root: Path, configured: str | Path) -> Path:
    path = Path(configured)
    if path.is_absolute():
        return path
    return (data_root / path).resolve(strict=False)


def _require_speechbrain() -> int | None:
    try:
        from app.voice.enrollment import prepare_speechbrain_runtime

        prepare_speechbrain_runtime()
        import speechbrain  # noqa: F401
    except ImportError:
        print(
            "speechbrain이 없습니다. 먼저 아래를 실행하세요:\n"
            r'  .\.venv\Scripts\python.exe -m pip install -e ".[voice]"',
            file=sys.stderr,
        )
        return 3
    except Exception as error:  # pragma: no cover - environment specific
        print(f"speechbrain을 불러오지 못했습니다: {error}", file=sys.stderr)
        return 3
    return None


def _record_utterance(
    *,
    device: str,
    sample_rate: int,
    policy: SpeechCapturePolicy,
) -> tuple[AudioFrame, ...] | None:
    capture = SpeechCapture(policy)
    peak_dbfs = -96.0
    with MicrophoneStream(device, sample_rate=sample_rate) as microphone:
        while not capture.finished:
            frame = microphone.next_frame(timeout_s=0.5)
            if frame is None:
                continue
            peak_dbfs = max(peak_dbfs, frame.rms_dbfs)
            capture.feed(frame)
            print(
                f"\r음량 {frame.rms_dbfs:.1f} dBFS · 최고 {peak_dbfs:.1f} dBFS",
                end="",
                flush=True,
            )
    print()
    if not capture.acceptable or not capture.frames or peak_dbfs < MIN_PEAK_DBFS:
        print(
            f"음성이 충분히 잡히지 않았습니다. (최고 {peak_dbfs:.1f} dBFS, "
            f"목표 {MIN_PEAK_DBFS:.0f} dBFS 이상)\n"
            "마이크를 가까이 두고 더 크게 말한 뒤 같은 문장을 다시 시도합니다.",
            file=sys.stderr,
        )
        return None
    return tuple(capture.frames)


def main(argv: list[str] | None = None) -> int:
    missing = _require_speechbrain()
    if missing is not None:
        return missing

    args = _parser().parse_args(argv)
    config = load_config(args.config)
    voice = config.settings.voice
    source = voice.source_filter
    device = voice.stt.device
    sample_rate = voice.stt.sample_rate_hz
    profile_path = _resolve(config.settings.paths.data_root, source.profile_path)
    model_dir = _resolve(config.settings.paths.data_root, source.ecapa_model_dir)

    print("Soft 화자 등록을 시작합니다. 원본 PCM은 저장하지 않습니다.")
    print(f"장치: {device}")
    print(f"프로필: {profile_path}")
    print("첫 실행이면 ECAPA 모델을 내려받으므로 시간이 걸릴 수 있습니다.")
    embedder = TorchEcapaSpeakerEmbedder(model_dir)
    utterances: list[tuple[AudioFrame, ...]] = []
    phrases = list(DEFAULT_PHRASES)
    while len(phrases) < args.utterances:
        phrases.append(DEFAULT_PHRASES[len(phrases) % len(DEFAULT_PHRASES)])

    policy = SpeechCapturePolicy(
        pre_roll_ms=voice.stt.command.pre_roll_ms,
        speech_threshold_dbfs=voice.stt.command.speech_threshold_dbfs,
        trailing_silence_ms=voice.stt.command.trailing_silence_ms,
        min_speech_ms=voice.stt.command.min_speech_ms,
        max_duration_ms=int(voice.stt.max_command_seconds * 1000),
    )

    index = 0
    while index < args.utterances:
        phrase = phrases[index]
        input(f"\n[{index + 1}/{args.utterances}] Enter 후 말하세요: {phrase}\n")
        frames = _record_utterance(
            device=device,
            sample_rate=sample_rate,
            policy=policy,
        )
        if frames is None:
            continue
        utterances.append(frames)
        index += 1

    try:
        profile = build_profile_from_frames(
            utterances,
            embedder,
            embedder_id=TorchEcapaSpeakerEmbedder.embedder_id,
        )
    except RuntimeError as error:
        print(f"화자 임베딩 실패: {error}", file=sys.stderr)
        return 4
    # Explicitly drop PCM before writing profile metadata.
    utterances.clear()
    save_speaker_profile(profile_path, profile)
    print(
        f"등록 완료: samples={profile.sample_count}, "
        f"dim={len(profile.embedding)}, path={profile_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
