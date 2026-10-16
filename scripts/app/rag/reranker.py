"""Bounded, offline Cross-Encoder ranking after hybrid retrieval.

RRF scores remain retrieval scores. Cross-Encoder logits only determine order;
they are not calibrated probabilities or evidence that an answer is true.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

from app.config.models import RerankSettings

MODEL_REPO = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MODEL_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
MODEL_DIRECTORY = "mmarco-minilm-reranker"
MODEL_FILES = {
    "onnx/model_quint8_avx2.onnx": (
        "6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b"
    ),
    "tokenizer.json": "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626",
}


class EventSink(Protocol):
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


class PairScorer(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class Candidate:
    key: str
    text: str
    score: float
    rerank_score: float | None = None


def verify_model_files(model_dir: Path) -> None:
    for name, expected in MODEL_FILES.items():
        with (model_dir / name).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Reranker artifact checksum mismatch: {name}")


class LocalCrossEncoder:
    def __init__(self, model_dir: Path, settings: RerankSettings) -> None:
        self.model_dir = model_dir
        self.settings = settings
        self._session: Any = None
        self._tokenizer: Any = None

    def _load(self) -> None:
        if self._session is not None:
            return
        verify_model_files(self.model_dir)
        import onnxruntime as ort  # type: ignore[import-untyped]
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        tokenizer.no_truncation()
        tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = self.settings.cpu_threads
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(
            str(self.model_dir / "onnx/model_quint8_avx2.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer, self._session = tokenizer, session

    def score(self, query: str, passages: list[str]) -> list[float]:
        self._load()
        import onnxruntime as ort

        np = import_module("numpy")
        query_ids = self._tokenizer.encode(query, add_special_tokens=False).ids
        if len(query_ids) > self.settings.max_length // 4:
            raise ValueError(
                "Reranker query budget exceeded; preserve RRF without silent truncation"
            )
        short_query = query
        windows: list[str] = []
        owners: list[int] = []
        specials = self._tokenizer.num_special_tokens_to_add(is_pair=True)
        capacity = self.settings.max_length - len(query_ids) - specials
        for owner, passage in enumerate(passages):
            encoding = self._tokenizer.encode(passage, add_special_tokens=False)
            offsets = [(a, b) for a, b in encoding.offsets if b > a]
            if not offsets:
                windows.append(passage)
                owners.append(owner)
                continue
            start = 0
            count = 0
            while start < len(offsets):
                end = min(len(offsets), start + capacity)
                windows.append(passage[offsets[start][0] : offsets[end - 1][1]])
                owners.append(owner)
                count += 1
                if count > 32:
                    raise ValueError("Reranker window budget exceeded")
                if end == len(offsets):
                    break
                start = max(start + 1, end - min(32, capacity // 4))
        self.last_window_count = len(windows)
        deadline = time.monotonic() + self.settings.timeout_s
        scores: list[float] = []
        for offset in range(0, len(windows), self.settings.batch_size):
            batch = windows[offset : offset + self.settings.batch_size]
            encodings = self._tokenizer.encode_batch([(short_query, p) for p in batch])
            if any(len(e.ids) > self.settings.max_length for e in encodings):
                raise ValueError("Reranker pair exceeds token budget")
            arrays = {
                "input_ids": np.asarray([e.ids for e in encodings], dtype=np.int64),
                "attention_mask": np.asarray([e.attention_mask for e in encodings], dtype=np.int64),
                "token_type_ids": np.asarray([e.type_ids for e in encodings], dtype=np.int64),
            }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Reranker inference deadline exceeded")
            run_options = ort.RunOptions()
            timer = threading.Timer(
                remaining,
                lambda opts=run_options: setattr(opts, "terminate", True),
            )
            timer.daemon = True
            timer.start()
            try:
                outputs = self._session.run(
                    None,
                    {i.name: arrays[i.name] for i in self._session.get_inputs()},
                    run_options,
                )
            finally:
                timer.cancel()
            if time.monotonic() > deadline:
                raise TimeoutError("Reranker inference deadline exceeded")
            logits = np.asarray(outputs[0])
            if logits.shape != (len(batch), 1):
                raise ValueError("Expected one Cross-Encoder logit per pair")
            scores.extend(float(v) for v in logits[:, 0])
        aggregated = [float("-inf")] * len(passages)
        for owner, score in zip(owners, scores, strict=True):
            aggregated[owner] = max(aggregated[owner], score)
        return aggregated


class Reranker:
    def __init__(
        self,
        settings: RerankSettings,
        models_root: Path,
        *,
        scorer: PairScorer | None = None,
        events: EventSink | None = None,
    ) -> None:
        self.settings = settings
        self.scorer = scorer or LocalCrossEncoder(models_root / MODEL_DIRECTORY, settings)
        self.events = events
        self.last_error: str | None = None
        self.status = "not_run" if settings.enabled else "disabled"
        self._retry_at = 0.0
        self._lock = threading.Lock()

    def retrieval_limit(self, original: int) -> int:
        return max(original, self.settings.candidate_count) if self.settings.enabled else original

    def rank(self, query: str, candidates: list[Candidate]) -> list[Candidate]:
        if (
            not self.settings.enabled
            or len(candidates) < 2
            or not query.strip()
            or time.monotonic() < self._retry_at
        ):
            return candidates
        if not self._lock.acquire(blocking=False):
            return candidates
        started = time.monotonic()
        pool = candidates[: self.settings.candidate_count]
        try:
            scores = self.scorer.score(query, [c.text for c in pool])
            if len(scores) != len(pool) or not all(math.isfinite(s) for s in scores):
                raise ValueError("Invalid reranker scores")
            ranked = [replace(c, rerank_score=float(s)) for c, s in zip(pool, scores, strict=True)]
            ranked.sort(
                key=lambda c: c.rerank_score if c.rerank_score is not None else 0, reverse=True
            )
            self.last_error = None
            self.status = "ready"
            if self.events:
                self.events.emit(
                    "rag.rerank",
                    {
                        "candidates": len(pool),
                        "elapsed_ms": round((time.monotonic() - started) * 1000),
                        "model": MODEL_REPO,
                    },
                )
            return ranked + candidates[len(pool) :]
        except Exception as error:
            self.last_error = type(error).__name__
            self.status = "rrf_fallback"
            self._retry_at = time.monotonic() + 30
            if self.events:
                self.events.emit(
                    "rag.rerank_unavailable",
                    {
                        "error_type": self.last_error,
                        "fallback": "rrf",
                        "model": MODEL_REPO,
                    },
                )
            return candidates
        finally:
            self._lock.release()
