"""Learned embeddings through local Ollama only; no hash or remote fallback."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any, Protocol


class Embedder(Protocol):
    @property
    def identity(self) -> str: ...

    def embed(self, text: str) -> list[float]: ...


class EmbeddingInputTooLong(ValueError):
    """The tokenizer cannot accept this complete input; never silently truncate."""


def normalized_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8192:
        raise ValueError("Invalid embedding dimension")
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) for x in value):
        raise ValueError("Invalid embedding values")
    vector = [float(x) for x in value]
    if not all(math.isfinite(x) for x in vector):
        raise ValueError("Non-finite embedding")
    norm = math.sqrt(sum(x * x for x in vector))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("Zero or invalid embedding")
    return [x / norm for x in vector]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class LocalOllamaEmbedder:
    def __init__(self, model: str = "embeddinggemma", timeout: float = 30) -> None:
        if model != "embeddinggemma":
            raise ValueError("Only the local embeddinggemma model is supported")
        self.model = model
        self.timeout = timeout
        self._identity: str | None = None
        self._cache: OrderedDict[str, tuple[list[float], int | None]] = OrderedDict()

    @property
    def retrieval_identity(self) -> str:
        return self.identity.removesuffix("raw-v1") + "search-v1:tokenizer-model:l2:768"

    def refresh_identity(self) -> None:
        """Recheck mutable Ollama tags on index refresh, not every query vector."""
        previous = self._identity
        self._identity = None
        try:
            current = self.identity
        except Exception:
            self._identity = previous
            raise
        if current != previous:
            self._cache.clear()

    @staticmethod
    def document_input(text: str, title: str = "none") -> str:
        return f"title: {title or 'none'} | text: {text}"

    @staticmethod
    def query_input(text: str) -> str:
        """Keep the whole question, including exclusions and follow-up context.

        Query inputs never use document chunk budgets. The model tokenizes this
        complete input; truncate=False makes overlong queries fail explicitly.
        """
        return f"task: search result | query: {text}"

    def embed_query(self, text: str) -> list[float]:
        return self.embed(self.query_input(text))

    def embed_document(self, text: str, title: str = "none") -> list[float]:
        return self.embed(self.document_input(text, title))

    def count_document_tokens(self, text: str, title: str = "none") -> int:
        """Use the installed model's tokenizer, including document prompt overhead.

        Ollama exposes token usage through embedding inference. Cache that vector
        for publication; no separate tokenizer download or guessed character ratio.
        """
        formatted = self.document_input(text, title)
        self.embed(formatted)
        count = self._cache[formatted][1]
        if count is None:
            raise ValueError("Embedding endpoint omitted prompt_eval_count")
        return count

    def _request(self, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/" + endpoint,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if endpoint == "embed" and error.code == 400:
                detail = error.read(4096).decode("utf-8", errors="replace")
                if "input length exceeds the context length" in detail:
                    raise EmbeddingInputTooLong("Embedding input exceeds model context") from error
            raise

    @property
    def identity(self) -> str:
        if self._identity is None:
            models = self._request("tags")["models"]
            model = next(
                (m for m in models if m.get("name") in {self.model, self.model + ":latest"}), None
            )
            if not model or not model.get("digest") or model.get("remote_host"):
                raise ValueError("로컬 embeddinggemma가 필요합니다: ollama pull embeddinggemma")
            self._identity = f"{self.model}:{model['digest']}:raw-v1"
        return self._identity

    def embed(self, text: str) -> list[float]:
        _ = self.identity
        if text in self._cache:
            self._cache.move_to_end(text)
            return list(self._cache[text][0])
        result = self._request(
            "embed",
            {
                "model": self.model,
                "input": text,
                "truncate": False,
                "keep_alive": "5m",
            },
        )
        if result.get("remote_host") or len(result.get("embeddings", [])) != 1:
            raise ValueError("Invalid local embedding response")
        vector = normalized_vector(result["embeddings"][0])
        count = result.get("prompt_eval_count")
        if count is not None and (type(count) is not int or count < 1):
            raise ValueError("Invalid embedding token count")
        self._cache[text] = (vector, count)
        if len(self._cache) > 256:
            self._cache.popitem(last=False)
        return list(vector)


def retrieval_identity(embedder: Embedder) -> str:
    return getattr(embedder, "retrieval_identity", embedder.identity)


def embed_query(embedder: Embedder, text: str) -> list[float]:
    method = getattr(embedder, "embed_query", embedder.embed)
    return normalized_vector(method(text))


def embed_document(embedder: Embedder, text: str, title: str = "none") -> list[float]:
    method = getattr(embedder, "embed_document", None)
    return normalized_vector(method(text, title) if method else embedder.embed(text))
