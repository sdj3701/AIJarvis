"""Repeatable local RAG runtime checks without touching document/conversation data."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config.loader import load_config
from app.llm.launcher import OllamaLauncher
from app.llm.ollama_client import OllamaClient
from app.rag.local_embedder import LocalOllamaEmbedder
from app.rag.reranker import MODEL_DIRECTORY, LocalCrossEncoder, verify_model_files


def check_runtime(config_dir: Path, *, start_ollama: bool = False) -> dict[str, Any]:
    loaded = load_config(config_dir)
    settings = loaded.settings
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(), "python": sys.version.split()[0],
        "checks": {}, "ok": False,
        "scope": "Local embedding inference, reranker inference, SQLite and answer-model identity",
    }
    checks = report["checks"]
    launcher = OllamaLauncher()
    healthy = launcher.is_healthy()
    started = False
    if not healthy and start_ollama:
        launcher.ensure_running()
        started = True
        healthy = launcher.is_healthy()
    checks["ollama"] = {"ok": healthy, "started_by_check": started}
    try:
        info = OllamaClient(settings.llm).verify_model()
        checks["answer_model"] = {"ok": True, **asdict(info)}
    except Exception as error:
        checks["answer_model"] = {"ok": False, "error": type(error).__name__}
    try:
        embedder = LocalOllamaEmbedder(settings.rag.semantic.model, settings.rag.semantic.timeout_s)
        vector = embedder.embed("로컬 임베딩 동작 확인")
        checks["embedding"] = {"ok": True, "dimensions": len(vector),
                               "identity": embedder.identity}
    except Exception as error:
        checks["embedding"] = {"ok": False, "error": type(error).__name__}
    try:
        import sqlite_vec  # type: ignore[import-untyped]
        connection = sqlite3.connect(":memory:")
        try:
            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            version = connection.execute("SELECT vec_version()").fetchone()[0]
            connection.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(text)")
        finally:
            connection.close()
        checks["sqlite"] = {"ok": True, "sqlite_version": sqlite3.sqlite_version,
                            "sqlite_vec_version": version, "fts5": True}
    except Exception as error:
        checks["sqlite"] = {"ok": False, "error": type(error).__name__}
    try:
        models = settings.paths.models_dir
        models = models if models.is_absolute() else settings.paths.data_root / models
        directory = models / MODEL_DIRECTORY
        verify_model_files(directory)
        scorer = LocalCrossEncoder(directory, settings.rag.rerank)
        scores = scorer.score("휴가 신청 방법", ["연차 휴가는 인사 포털에서 신청합니다.",
                                              "파스타는 면을 삶아 만듭니다."])
        checks["reranker"] = {"ok": scores[0] > scores[1], "scores": scores,
                              "checksums_verified": True}
    except Exception as error:
        checks["reranker"] = {"ok": False, "error": type(error).__name__}
    report["versions"] = {}
    for package in ("sqlite-vec", "onnxruntime", "tokenizers", "pydantic"):
        try:
            report["versions"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["versions"][package] = None
    report["ok"] = all(item["ok"] for item in checks.values())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--start-ollama", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = check_runtime(args.config_dir, start_ollama=args.start_ollama)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
