from __future__ import annotations

import pytest

from app.rag.local_embedder import LocalOllamaEmbedder, normalized_vector

pytestmark = pytest.mark.phase3
REAL_REQUEST = LocalOllamaEmbedder._request


@pytest.mark.parametrize("value", [[], [0, 0], [float("nan"), 1], [float("inf")], [True], ["x"]])
def test_invalid_vectors_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        normalized_vector(value)


def test_embedder_uses_digest_and_refuses_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = LocalOllamaEmbedder()
    requests = []

    def request(endpoint: str, payload: object = None) -> object:
        requests.append((endpoint, payload))
        if endpoint == "tags":
            return {"models": [{"name": "embeddinggemma:latest", "digest": "revision"}]}
        return {"embeddings": [[3.0, 4.0]]}

    monkeypatch.setattr(embedder, "_request", request)
    assert embedder.embed("질문") == [0.6, 0.8]
    assert embedder.identity == "embeddinggemma:revision:raw-v1"
    assert requests[-1][1]["truncate"] is False


def test_cloud_model_metadata_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = LocalOllamaEmbedder()
    monkeypatch.setattr(
        embedder,
        "_request",
        lambda *args: {
            "models": [{"name": "embeddinggemma:latest", "digest": "x", "remote_host": "cloud"}]
        },
    )
    with pytest.raises(ValueError):
        embedder.embed("private")


def test_retrieval_roles_preserve_legacy_identity_and_cache_token_usage(monkeypatch):
    model = LocalOllamaEmbedder()
    seen = []

    def request(endpoint, payload=None):
        if endpoint == "tags":
            return {"models": [{"name": "embeddinggemma", "digest": "d1"}]}
        seen.append(payload["input"])
        return {"embeddings": [[3.0, 4.0]], "prompt_eval_count": 17}

    monkeypatch.setattr(model, "_request", request)
    assert model.count_document_tokens("원문", "규정") == 17
    model.embed_document("원문", "규정")
    model.embed_query("질문")
    assert seen == ["title: 규정 | text: 원문", "task: search result | query: 질문"]
    assert "raw-v1" in model.identity
    assert "search-v1" in model.retrieval_identity


def test_tag_revision_change_invalidates_cached_vectors(monkeypatch):
    model = LocalOllamaEmbedder()
    state = {"digest": "old", "vector": [1.0, 0.0]}

    def request(endpoint, payload=None):
        if endpoint == "tags":
            return {"models": [{"name": "embeddinggemma", "digest": state["digest"]}]}
        return {"embeddings": [state["vector"]], "prompt_eval_count": 10}

    monkeypatch.setattr(model, "_request", request)
    assert model.embed_query("질문") == [1.0, 0.0]
    state.update(digest="new", vector=[0.0, 1.0])
    model.refresh_identity()
    assert ":new:" in model.retrieval_identity
    assert model.embed_query("질문") == [0.0, 1.0]


def test_long_question_keeps_all_conditions_and_never_uses_document_prompt(monkeypatch):
    model = LocalOllamaEmbedder()
    seen = []

    def request(endpoint, payload=None):
        if endpoint == "tags":
            return {"models": [{"name": "embeddinggemma", "digest": "d1"}]}
        seen.append(payload)
        return {"embeddings": [[1.0, 0.0]], "prompt_eval_count": 900}

    monkeypatch.setattr(model, "_request", request)
    question = "출장비 규정을 알려줘. " * 100 + "단, 임원에게만 적용되는 항목은 제외해."
    model.embed_query(question)
    assert len(seen) == 1
    assert seen[0]["input"] == "task: search result | query: " + question
    assert seen[0]["truncate"] is False


@pytest.mark.parametrize("overflow", [True, False])
def test_only_model_context_overflow_has_a_distinct_error(monkeypatch, overflow):
    import io
    import urllib.error
    import urllib.request

    from app.rag.local_embedder import EmbeddingInputTooLong

    detail = "the input length exceeds the context length" if overflow else "invalid model"

    class Opener:
        def open(self, *args, **kwargs):
            raise urllib.error.HTTPError(
                "http://127.0.0.1",
                400,
                "Bad Request",
                {},
                io.BytesIO(('{"error":"' + detail + '"}').encode()),
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    # conftest blocks live requests; restore the real method only against our fake opener.
    monkeypatch.setattr(LocalOllamaEmbedder, "_request", REAL_REQUEST)
    model = LocalOllamaEmbedder()
    model._identity = "embeddinggemma:test:raw-v1"
    with pytest.raises(EmbeddingInputTooLong if overflow else urllib.error.HTTPError):
        model.embed_query("keep the whole question")
