"""Owner voice enrollment: embeddings only, PCM discarded immediately."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.voice.base import AudioFrame
from app.voice.source_filter import SpeakerEmbedder, concat_pcm, l2_normalize

PROFILE_VERSION = 1


@dataclass(frozen=True, slots=True)
class SpeakerProfile:
    embedding: tuple[float, ...]
    sample_count: int
    embedder_id: str

    def __post_init__(self) -> None:
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if not self.embedding:
            raise ValueError("embedding must not be empty")
        if not self.embedder_id:
            raise ValueError("embedder_id must not be empty")


class TorchEcapaSpeakerEmbedder:
    """Lazy SpeechBrain ECAPA embedder running on CPU."""

    embedder_id = "speechbrain/spkrec-ecapa-voxceleb"

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._classifier: object | None = None
        self._failed = False

    def warm(self) -> None:
        """Load the ECAPA classifier eagerly for lower first-wake latency."""
        self._ensure_classifier()

    def embed(self, frames: Sequence[AudioFrame]) -> tuple[float, ...]:
        if self._failed:
            raise RuntimeError("ECAPA embedder previously failed to load")
        classifier = self._ensure_classifier()
        pcm, sample_rate = concat_pcm(frames)
        if sample_rate != 16_000:
            raise ValueError("ECAPA embedder expects 16 kHz PCM")
        try:
            import numpy as np
            import torch

            waveform = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32_768.0
            tensor = torch.from_numpy(waveform).unsqueeze(0)
            with torch.no_grad():
                embedding = classifier.encode_batch(tensor)  # type: ignore[attr-defined]
            vector = embedding.squeeze().detach().cpu().tolist()
            if isinstance(vector, float):
                raise RuntimeError("ECAPA returned a scalar embedding")
            return l2_normalize([float(item) for item in vector])
        except Exception as error:
            self._failed = True
            raise RuntimeError(f"ECAPA embedding failed: {error}") from error

    def _ensure_classifier(self) -> object:
        if self._classifier is not None:
            return self._classifier
        try:
            prepare_speechbrain_runtime()
            from speechbrain.inference.speaker import EncoderClassifier
            from speechbrain.utils.fetching import LocalStrategy

            self._model_dir.mkdir(parents=True, exist_ok=True)
            # Windows often lacks symlink privilege; COPY avoids WinError 1314.
            self._classifier = EncoderClassifier.from_hparams(
                source=self.embedder_id,
                savedir=str(self._model_dir),
                run_opts={"device": "cpu"},
                local_strategy=LocalStrategy.COPY,
            )
        except Exception as error:
            self._failed = True
            raise RuntimeError(f"failed to load ECAPA model: {error}") from error
        return self._classifier


def prepare_speechbrain_runtime() -> None:
    """Apply SpeechBrain compatibility shims for current torchaudio/Windows."""
    import logging

    patch_torchaudio_for_speechbrain()
    patch_speechbrain_windows_copy()
    # Keep wake-path console readable; fetch/copy chatter is not user-facing.
    logging.getLogger("speechbrain").setLevel(logging.WARNING)


def patch_torchaudio_for_speechbrain() -> None:
    """torchaudio 2.9+ removed list_audio_backends; SpeechBrain 1.0.2 still calls it."""
    import torchaudio

    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]  # type: ignore[attr-defined]


def patch_speechbrain_windows_copy() -> None:
    """SpeechBrain from_hparams does not forward local_strategy to Pretrainer."""
    from speechbrain.utils.fetching import LocalStrategy
    from speechbrain.utils.parameter_transfer import Pretrainer

    if getattr(Pretrainer.collect_files, "_jarvis_copy_patched", False):
        return

    original = Pretrainer.collect_files

    def collect_files(
        self: object,
        default_source: object = None,
        use_auth_token: bool = False,
        local_strategy: LocalStrategy = LocalStrategy.COPY,
    ) -> object:
        return original(
            self,
            default_source=default_source,
            use_auth_token=use_auth_token,
            local_strategy=local_strategy,
        )

    collect_files._jarvis_copy_patched = True  # type: ignore[attr-defined]
    Pretrainer.collect_files = collect_files  # type: ignore[method-assign]


def average_embeddings(embeddings: Sequence[Sequence[float]]) -> tuple[float, ...]:
    if not embeddings:
        raise ValueError("embeddings must not be empty")
    width = len(embeddings[0])
    if width == 0:
        raise ValueError("embedding dimension must be positive")
    if any(len(item) != width for item in embeddings):
        raise ValueError("all embeddings must share the same dimension")
    sums = [0.0] * width
    for embedding in embeddings:
        for index, value in enumerate(embedding):
            sums[index] += float(value)
    mean = [value / len(embeddings) for value in sums]
    return l2_normalize(mean)


def build_profile_from_frames(
    utterances: Sequence[Sequence[AudioFrame]],
    embedder: SpeakerEmbedder,
    *,
    embedder_id: str,
) -> SpeakerProfile:
    if len(utterances) < 1:
        raise ValueError("at least one enrollment utterance is required")
    embeddings: list[tuple[float, ...]] = []
    for frames in utterances:
        if not frames:
            raise ValueError("enrollment utterance must contain audio")
        embeddings.append(tuple(embedder.embed(frames)))
        # Caller retains no PCM after this function returns; frames are not stored.
    return SpeakerProfile(
        embedding=average_embeddings(embeddings),
        sample_count=len(embeddings),
        embedder_id=embedder_id,
    )


def save_speaker_profile(path: Path, profile: SpeakerProfile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    try:
        import io

        import numpy as np

        buffer = io.BytesIO()
        np.savez_compressed(
            buffer,
            version=np.asarray([PROFILE_VERSION], dtype=np.int32),
            embedding=np.asarray(profile.embedding, dtype=np.float32),
            sample_count=np.asarray([profile.sample_count], dtype=np.int32),
            embedder_id=np.asarray([profile.embedder_id]),
        )
        temporary.write_bytes(buffer.getvalue())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_speaker_profile(path: Path) -> SpeakerProfile | None:
    if not path.is_file():
        return None
    import numpy as np

    with np.load(path, allow_pickle=False) as payload:
        version = int(payload["version"][0])
        if version != PROFILE_VERSION:
            raise ValueError(f"unsupported speaker profile version: {version}")
        embedding = tuple(float(value) for value in payload["embedding"].tolist())
        sample_count = int(payload["sample_count"][0])
        embedder_id = str(payload["embedder_id"][0])
    return SpeakerProfile(
        embedding=l2_normalize(embedding),
        sample_count=sample_count,
        embedder_id=embedder_id,
    )
