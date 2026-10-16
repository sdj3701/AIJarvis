"""Evaluate the actual DocumentIndexer path on an isolated document snapshot.

Unlike the historical retrieval benchmark this includes synchronization, service
candidate limits, per-document chunk caps and optional Cross-Encoder reranking.
It measures retrieval, not answer correctness or LLM generation latency.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Any

from app.config.loader import load_config
from app.core.ids import SystemIdFactory
from app.memory.migrations import initialize_database
from app.rag.benchmark.datasets import load_evaluation_queries
from app.rag.benchmark.metrics import percentile, quality_metrics
from app.rag.benchmark.models import EvaluationQuery, RetrievalResult
from app.rag.benchmark.provenance import source_fingerprints
from app.rag.indexer import DocumentIndexer
from app.rag.local_embedder import retrieval_identity
from app.rag.reranker import MODEL_REVISION, Reranker


def snapshot_documents(source: Path, target: Path) -> None:
    """Copy only document tables, never conversation history or operational state."""
    if source.resolve() == target.resolve() or target.exists():
        raise ValueError("Snapshot target must be a new, separate file")
    initialize_database(target)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        src.execute("BEGIN")
        with closing(sqlite3.connect(target)) as dst, dst:
            for table in ("documents", "doc_chunks"):
                cursor = src.execute(f"SELECT * FROM {table}")
                columns = [item[0] for item in cursor.description]
                marks = ",".join("?" for _ in columns)
                dst.executemany(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({marks})", cursor.fetchall()
                )


def validate_relevance(database: Path, queries: tuple[EvaluationQuery, ...]) -> None:
    with closing(sqlite3.connect(database)) as db:
        ids = {r[0] for r in db.execute("SELECT doc_id FROM documents")}
    unknown = {doc for query in queries for doc in query.relevant_document_ids} - ids
    if unknown:
        raise ValueError("Unknown relevance document IDs: " + ", ".join(sorted(unknown)))


def evaluate(config_dir: Path, dataset: Path, output: Path, repeats: int = 3) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    loaded = load_config(config_dir)
    settings = loaded.settings
    if not settings.rag.semantic.enabled or not settings.rag.rerank.enabled:
        raise ValueError("Current-pipeline evaluation requires embeddings and reranking enabled")
    root = settings.paths.data_root
    db_path = settings.paths.memory_db
    source = db_path if db_path.is_absolute() else root / db_path
    queries = load_evaluation_queries(dataset)
    validate_relevance(source, queries)
    output.mkdir(parents=True, exist_ok=True)
    snapshot = output / "indexes" / "documents.sqlite3"
    snapshot_documents(source, snapshot)
    models = settings.paths.models_dir
    models = models if models.is_absolute() else root / models
    indexer = DocumentIndexer(
        snapshot,
        output / "unused-docs",
        settings.rag,
        loaded.policies.privacy.api_transmission.documents,
        SystemIdFactory(),
        models_root=models,
    )
    started = perf_counter()
    indexer.sync_vectors()
    assert indexer.semantic is not None
    if indexer.semantic.last_error:
        raise RuntimeError("Embedding initialization failed: " + indexer.semantic.last_error)
    build_ms = (perf_counter() - started) * 1000
    baseline = replace(
        indexer,
        reranker=Reranker(
            settings.rag.rerank.model_copy(update={"enabled": False}),
            models,
        ),
    )
    pipelines = {"hybrid_rrf": baseline, "hybrid_rerank": indexer}
    order = list(queries)
    random.Random(42).shuffle(order)
    for pipeline in pipelines.values():
        for query in order[:5]:
            pipeline.search(query.query)
    records: list[dict[str, Any]] = []
    # Interleave variants per question to reduce systematic thermal/order bias.
    for number, query in enumerate(order, 1):
        for repeat in range(repeats):
            variants = list(pipelines.items())
            if (number + repeat) % 2:
                variants.reverse()
            for name, pipeline in variants:
                started = perf_counter()
                hits = pipeline.search(query.query)
                elapsed = (perf_counter() - started) * 1000
                if pipeline.semantic and pipeline.semantic.last_error:
                    raise RuntimeError("Embedding fallback during evaluation")
                if pipeline.reranker and pipeline.reranker.last_error:
                    raise RuntimeError("Reranker fallback during evaluation")
                results: list[RetrievalResult] = [
                    {
                        "document_id": h.doc_id,
                        "chunk_id": h.chunk_id,
                        "content": h.text,
                        "score": h.score,
                        "rank": rank,
                    }
                    for rank, h in enumerate(hits, 1)
                ]
                records.append(
                    {
                        "pipeline": name,
                        "query_id": query.query_id,
                        "query_type": query.query_type,
                        "repeat": repeat + 1,
                        "latency_ms": elapsed,
                        "retrieved_document_ids": [h.doc_id for h in hits],
                        **quality_metrics(results, query.relevant_document_ids),
                    }
                )
        if number % 20 == 0:
            print(f"retrieval {number}/{len(order)}", flush=True)
    summaries = []
    for name in pipelines:
        for kind in ("all", "keyword", "semantic", "hybrid"):
            rows = [
                r
                for r in records
                if r["pipeline"] == name and (kind == "all" or r["query_type"] == kind)
            ]
            if not rows:
                continue
            metrics = {
                key: fmean(r[key] for r in rows)
                for key in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr_at_5", "ndcg_at_5")
            }
            times = [r["latency_ms"] for r in rows]
            summaries.append(
                {
                    "pipeline": name,
                    "query_type": kind,
                    "query_count": len(rows) // repeats,
                    **metrics,
                    "latency_p50_ms": percentile(times, 50),
                    "latency_p95_ms": percentile(times, 95),
                }
            )
    with closing(sqlite3.connect(snapshot)) as db:
        corpus = db.execute("SELECT doc_id,content_hash FROM documents ORDER BY doc_id").fetchall()
    report = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source_sha256": source_fingerprints(),
        "scope": "DocumentIndexer retrieval only; no LLM generation or answer accuracy",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "corpus_sha256": hashlib.sha256(json.dumps(corpus).encode()).hexdigest(),
        "documents": len(corpus),
        "queries": len(queries),
        "repeats": repeats,
        "seed": 42,
        "warmup_queries_per_pipeline": min(5, len(queries)),
        "embedding_identity": retrieval_identity(indexer.semantic.embedder),
        "reranker_revision": MODEL_REVISION,
        "settings": settings.rag.model_dump(mode="json"),
        "initial_vector_build_ms": build_ms,
        "limitations": [
            "Demo corpus, not a representative enterprise dataset",
            "Document-level relevance, not sentence-level answer correctness",
            "Runtime chunk cap applies; no Recall@10 claim",
        ],
        "summaries": summaries,
        "records": records,
    }
    (output / "service_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output / "service_summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/evaluation_queries.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    evaluate(args.config_dir, args.dataset, args.output_dir, args.repeats)


if __name__ == "__main__":
    main()
