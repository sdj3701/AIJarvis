"""Fingerprint uncommitted source as well as committed versions for local evaluations."""

import hashlib
from pathlib import Path


def source_fingerprints() -> dict[str, str]:
    root = Path(__file__).resolve().parents[4]
    paths = (
        "scripts/app/rag/indexer.py",
        "scripts/app/rag/semantic.py",
        "scripts/app/rag/reranker.py",
        "scripts/app/rag/generations.py",
        "scripts/app/rag/markdown_exports.py",
        "scripts/app/rag/chunker.py",
        "scripts/app/rag/document_parser.py",
        "scripts/app/rag/document_context.py",
        "scripts/app/rag/structured_answers.py",
        "scripts/app/rag/passages.py",
        "scripts/app/rag/models.py",
        "scripts/app/tools/impl/web_search.py",
        "scripts/app/orchestrator/query_plan.py",
        "scripts/app/orchestrator/response_presenter.py",
        "scripts/app/config/models.py",
        "scripts/app/rag/grounding.py",
        "scripts/app/rag/local_embedder.py",
        "scripts/app/orchestrator/loop.py",
        "scripts/app/orchestrator/research.py",
        "scripts/app/orchestrator/prompt.py",
        "scripts/app/orchestrator/envelope.py",
        "scripts/app/llm/ollama_client.py",
        "scripts/app/rag/benchmark/service.py",
        "scripts/app/rag/benchmark/answers.py",
        "scripts/app/rag/benchmark/redesign.py",
        "scripts/app/orchestrator/prompts/system_tools.md",
        "scripts/app/orchestrator/prompts/response_rulebook.md",
    )
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
