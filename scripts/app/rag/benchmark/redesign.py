"""Synthetic R3 chunk-budget sweep and raw/role embedding ablation.

Creates fresh indexes under the requested output directory. Never opens the
user's document or conversation DB. Shares only installed local models.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Any

from app.config.loader import load_config
from app.core.ids import SystemIdFactory
from app.llm.base import Message
from app.memory.migrations import initialize_database
from app.orchestrator.query_plan import plan_query
from app.rag.benchmark.provenance import source_fingerprints
from app.rag.benchmark.retrievers import VectorSearchRetriever, load_indexed_chunks
from app.rag.indexer import DocumentIndexer
from app.rag.local_embedder import LocalOllamaEmbedder


class RawEmbedder:
    """Expose the old raw input contract over the same installed model."""

    def __init__(self, model: LocalOllamaEmbedder):
        self.model = model

    @property
    def identity(self) -> str:
        return self.model.identity

    def embed(self, text: str) -> list[float]:
        return self.model.embed(text)


def evaluate(config_dir: Path, dataset: Path, output: Path) -> dict[str, Any]:
    loaded = load_config(config_dir)
    fixture = json.loads(dataset.read_text(encoding="utf-8"))
    # Each answerable case is independently namespaced in a combined corpus.
    # Cases sharing policy wording intentionally make this a harder retrieval set.
    cases = [c for c in fixture["cases"] if c.get("source")]
    corpus = output / "fixtures"
    if output.exists():
        raise ValueError("Use a new output directory to preserve prior evaluations")
    corpus.mkdir(parents=True)
    queries: list[dict[str, Any]] = []
    stress = "장문 작업자는 장비 상태를 확인하고 오류 발생 시 담당 부서에 보고합니다. " * 100
    (corpus / "token_stress.md").write_text(
        "# 정밀 점검\n\n" + stress + "\n\n정밀 점검 확인 번호는 86420입니다.", encoding="utf-8"
    )
    queries.append(
        {
            "id": "token_stress",
            "query": "정밀 점검 확인 번호는 무엇인가요?",
            "relevant": ["token_stress.md"],
        }
    )
    for c in cases:
        for name, body in c["documents"].items():
            p = corpus / c["id"] / name
            if not p.resolve().is_relative_to(corpus.resolve()):
                raise ValueError("Fixture leaves corpus root")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        # Repeated policy documents are all relevant if their source is identical.
        relevant = [
            other["id"] + "/" + name
            for other in cases
            for name, body in other["documents"].items()
            if body == c["documents"][c["source"]]
        ]
        relevant.append(c["id"] + "/" + c["source"])
        plan = plan_query(c["query"], [Message("user", h) for h in c.get("history_queries", [])])
        queries.append({"id": c["id"], "query": plan.search_query, "relevant": relevant})
    models = loaded.settings.paths.models_dir
    if not models.is_absolute():
        models = loaded.settings.paths.data_root / models
    report: dict[str, Any] = {
        "schema_version": 1,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "source_sha256": source_fingerprints(),
        "queries": queries,
        "chunk_sweep": [],
        "embedding_ablation": [],
        "limitations": "Small synthetic sample; duplicate policy wording; not a tuning optimum. "
        "Chunk sweep changes token cap only; raw/role ablation uses identical 384-token chunks "
        "and filename titles (not heading hierarchy).",
    }
    role = LocalOllamaEmbedder(timeout=loaded.settings.rag.semantic.timeout_s)
    for token_cap in (256, 384, 512):
        database = output / f"chunks-{token_cap}" / "jarvis.sqlite3"
        initialize_database(database)
        settings = loaded.settings.rag.model_copy(update={"chunk_max_tokens": token_cap})
        ix = DocumentIndexer(
            database,
            corpus,
            settings,
            loaded.policies.privacy.api_transmission.documents,
            SystemIdFactory(),
            models_root=models,
            auto_refresh=False,
        )
        assert ix.semantic is not None
        ix.semantic.embedder = role
        started = perf_counter()
        indexed = ix.sync()
        if indexed.errors:
            raise RuntimeError(str(indexed.errors))
        build_ms = (perf_counter() - started) * 1000
        rows: list[dict[str, Any]] = []
        for q in queries:
            started = perf_counter()
            hits = ix.search(q["query"])
            if ix.semantic.last_error or (ix.reranker and ix.reranker.last_error):
                raise RuntimeError("Model fallback during measured retrieval")
            paths = [Path(h.relative_path).as_posix() for h in hits]
            rows.append(
                {
                    "id": q["id"],
                    "paths": paths,
                    "hit_at_1": bool(set(paths[:1]) & set(q["relevant"])),
                    "hit_at_5": bool(set(paths[:5]) & set(q["relevant"])),
                    "latency_ms": (perf_counter() - started) * 1000,
                }
            )
        with ix._connection() as db:
            chunk_count = db.execute("SELECT count(*) FROM doc_chunks").fetchone()[0]
            maximum = db.execute("SELECT max(token_count) FROM rag_chunk_provenance").fetchone()[0]
        report["chunk_sweep"].append(
            {
                "token_cap": token_cap,
                "chunks": chunk_count,
                "max_measured_tokens": maximum,
                "build_ms": build_ms,
                "hit_at_1": fmean(r["hit_at_1"] for r in rows),
                "hit_at_5": fmean(r["hit_at_5"] for r in rows),
                "records": rows,
            }
        )
        print(f"chunk cap {token_cap}: {chunk_count} chunks", flush=True)
        if token_cap == 384:
            chunks = load_indexed_chunks(database)
            by_id = {c.document_id: Path(c.source_path).as_posix() for c in chunks}
            for label, embedder in (("raw-v1", RawEmbedder(role)), ("search-v1", role)):
                engine = VectorSearchRetriever(
                    chunks,
                    artifact_dir=output / label,
                    embedder=embedder,
                )
                measured: list[dict[str, Any]] = []
                for q in queries:
                    vector_hits = engine.search(q["query"])
                    paths = [by_id[h["document_id"]] for h in vector_hits]
                    measured.append(
                        {
                            "id": q["id"],
                            "paths": paths,
                            "hit_at_1": bool(set(paths[:1]) & set(q["relevant"])),
                            "hit_at_5": bool(set(paths[:5]) & set(q["relevant"])),
                        }
                    )
                report["embedding_ablation"].append(
                    {
                        "input_format": label,
                        "records": measured,
                        "hit_at_1": fmean(r["hit_at_1"] for r in measured),
                        "hit_at_5": fmean(r["hit_at_5"] for r in measured),
                    }
                )
    report["model_identity"] = role.retrieval_identity
    report["complete"] = True
    (output / "retrieval_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument(
        "--dataset", type=Path, default=Path("scripts/tests/data/rag_r3_answers.json")
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.config_dir, args.dataset, args.output_dir)


if __name__ == "__main__":
    main()
