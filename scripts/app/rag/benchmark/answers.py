"""Local end-to-end regression of retrieval, generation and grounding.

Each case has a fresh temporary document/session DB. Only installed model files
are shared. Results contain synthetic fixtures, never the user's conversation DB.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Any
from unittest.mock import patch

import yaml

from app.config.loader import load_config
from app.llm.base import LLMResponse
from app.memory.migrations import initialize_database
from app.orchestrator.loop import ChatOrchestrator
from app.rag.benchmark.metrics import percentile
from app.rag.benchmark.provenance import source_fingerprints
from app.rag.reranker import Reranker
from app.tools.impl.web_search import DocSearchTool
from app.wiring import build
from scripts.bootstrap import create_tree

REPO = Path(__file__).resolve().parents[4]


def score_case(
    case: dict[str, Any],
    text: str,
    status: str | None,
    sources: tuple[str, ...],
    ok: bool,
    mode: str | None = None,
) -> dict[str, bool]:
    # No claims in the reference list count toward expected answer facts.
    answer = re.sub(r"\s+", "", text.split("\n\n근거:", 1)[0])
    facts_ok = all(
        any(re.sub(r"\s+", "", variant) in answer for variant in variants)
        for variants in case.get("required_facts", [])
    )
    forbidden_ok = not any(word in answer for word in case.get("forbidden", []))
    source_ok = (
        any(s.split("#chunk=", 1)[0] == case["source"] for s in sources)
        if case.get("source")
        else not sources
    )
    status_ok = status == case["expected_status"]
    mode_ok = "expected_mode" not in case or mode == case["expected_mode"]
    return {
        "status_ok": status_ok,
        "facts_ok": facts_ok,
        "source_ok": source_ok,
        "mode_ok": mode_ok,
        "forbidden_ok": forbidden_ok,
        "passed": ok and status_ok and facts_ok and source_ok and forbidden_ok and mode_ok,
    }


def evaluate_answers(
    config_dir: Path, dataset: Path, output: Path, limit: int | None = None
) -> dict[str, Any]:
    loaded = load_config(config_dir)
    models = loaded.settings.paths.models_dir
    models = models if models.is_absolute() else loaded.settings.paths.data_root / models
    ranker = Reranker(loaded.settings.rag.rerank, models)
    fixture = json.loads(dataset.read_text(encoding="utf-8"))
    cases = fixture["cases"][:limit]
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "scope": fixture["description"],
        "complete": False,
        "source_sha256": source_fingerprints(),
        "dataset_cases": len(fixture["cases"]),
        "requested_cases": len(cases),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "llm_model": loaded.settings.llm.model,
        "llm_digest": loaded.settings.llm.model_digest,
        "settings": loaded.settings.rag.model_dump(mode="json"),
        "records": [],
    }
    (output / "answer_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="jarvis-rag-eval-") as directory:
            root = Path(directory) / "data"
            create_tree(root)
            config = Path(directory) / "config"
            config.mkdir()
            for name in ("settings", "tools", "privacy"):
                doc = yaml.safe_load(
                    (REPO / "config" / f"{name}.example.yaml").read_text(
                        encoding="utf-8",
                    )
                )
                if name == "settings":
                    doc["paths"]["data_root"] = str(root)
                    doc["llm"] = loaded.settings.llm.model_dump(mode="json")
                    doc["llm"]["temperature"] = 0
                    doc["rag"] = loaded.settings.rag.model_dump(mode="json")
                    doc["rag"]["semantic"]["conversations_enabled"] = False
                elif name == "tools":
                    # Only the disposable fixture root is used, no PC/network tools.
                    doc["tools"] = [t for t in doc["tools"] if t["name"] == "doc_search"]
                    doc["sandbox"]["deny_paths"] = ["C:\\Windows", "C:\\Program Files"]
                (config / f"{name}.yaml").write_text(
                    yaml.safe_dump(doc, allow_unicode=True),
                    encoding="utf-8",
                )
            runtime = build(config)
            initialize_database(runtime.memory_db)
            indexer = replace(runtime.indexer, reranker=ranker)
            tool = runtime.tool_runner.registry.tools["doc_search"]
            assert isinstance(tool, DocSearchTool)
            tool.indexer = indexer
            for name, text in case["documents"].items():
                path = indexer.docs_root / name
                if not path.resolve().is_relative_to(indexer.docs_root.resolve()):
                    raise ValueError("Fixture path leaves document root")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            indexed = indexer.sync()
            if indexed.errors:
                raise RuntimeError(str(indexed.errors))
            chat = ChatOrchestrator(
                settings=runtime.config.settings,
                llm=runtime.llm,
                sessions=runtime.sessions,
                budget=runtime.budget,
                masker=runtime.masker,
                events=runtime.events,
                clock=runtime.clock,
                sleeper=runtime.sleeper,
                random=runtime.random,
                ids=runtime.ids,
                indexer=indexer,
                research=runtime.research,
                tool_runner=runtime.tool_runner,
                safety_gate=runtime.safety_gate,
                approval_store=runtime.approval_store,
                audit_writer=runtime.audit_writer,
            )
            chat.start()
            started = perf_counter()
            completions: list[str | None] = []
            complete = runtime.llm.complete

            def record_completion(
                _complete: Callable[..., LLMResponse] = complete,
                _outputs: list[str | None] = completions,
                **kwargs: Any,
            ) -> LLMResponse:
                response = _complete(**kwargs)
                _outputs.append(response.text)
                return response

            with patch.object(runtime.llm, "complete", side_effect=record_completion):
                for prior in case.get("history_queries", []):
                    chat.handle_turn(prior)
                result = chat.handle_turn(case["query"])
            elapsed = (perf_counter() - started) * 1000
            if indexer.semantic and indexer.semantic.last_error:
                raise RuntimeError("Embedding fallback during answer evaluation")
            if ranker.last_error:
                raise RuntimeError("Reranker fallback during answer evaluation")
            record = {
                "id": case["id"],
                "kind": case["kind"],
                "query": case["query"],
                "expected_status": case["expected_status"],
                "status": result.grounding_status,
                "reason": result.grounding_reason,
                "text": result.text,
                "answer_mode": result.answer_mode,
                "fallback_reason": result.fallback_reason,
                "history_queries": case.get("history_queries", []),
                "retrieval": dict(indexer.last_diagnostics),
                "sources": result.sources,
                "latency_ms": elapsed,
                "model_outputs": completions,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                **score_case(
                    case,
                    result.text,
                    result.grounding_status,
                    result.sources,
                    result.ok,
                    result.answer_mode,
                ),
            }
            report["records"].append(record)
            (output / "answer_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(
                f"{case['id']}: {result.grounding_status}, {result.grounding_reason}, "
                f"passed={record['passed']}, {elapsed:.0f}ms",
                flush=True,
            )
            gc.collect()
    records = report["records"]
    report["complete"] = True
    report["summary"] = {
        "cases": len(records),
        "passed": sum(r["passed"] for r in records),
        "by_kind": {
            kind: {"count": len(rows), "passed": sum(r["passed"] for r in rows)}
            for kind in sorted({r["kind"] for r in records})
            if (rows := [r for r in records if r["kind"] == kind])
        },
        "latency_avg_ms": fmean(r["latency_ms"] for r in records),
        "latency_p95_ms": percentile([r["latency_ms"] for r in records], 95),
        "limitations": "Synthetic small-set regression; fact matching is not semantic proof",
    }
    (output / "answer_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=Path("scripts/tests/data/rag_answers.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    evaluate_answers(args.config_dir, args.dataset, args.output_dir, args.limit)


if __name__ == "__main__":
    main()
