"""Exercise real PDF -> Markdown file/DB/vector publication without answer generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.config.loader import load_config
from app.core.ids import SystemIdFactory
from app.memory.migrations import initialize_database
from app.rag.benchmark.provenance import source_fingerprints
from app.rag.generations import GenerationIndex
from app.rag.indexer import DocumentIndexer
from app.rag.markdown_exports import export_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(r"D:\Jarvis-v2-dev\config"))
    parser.add_argument("--apply-runtime", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = load_config(args.config)
    data = config.settings.paths.data_root

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else data / path

    original = args.pdf.read_bytes()
    source_hash = hashlib.sha256(original).hexdigest()
    backup: str | None = None
    if args.apply_runtime:
        database = resolve(config.settings.paths.memory_db)
        docs = resolve(config.settings.paths.docs_dir)
        if not database.is_file():
            raise ValueError("Expected an existing runtime DB")
        backups = output / "backup"
        backups.mkdir()
        for path in (database, database.with_name("semantic.sqlite3")):
            if path.exists():
                with (
                    closing(sqlite3.connect(path)) as src,
                    closing(sqlite3.connect(backups / path.name)) as dest,
                ):
                    src.backup(dest)
        backup = str(backups)
    else:
        database = output / "memory" / "jarvis.sqlite3"
        docs = output / "docs"
        initialize_database(database)
    docs.mkdir(parents=True, exist_ok=True)
    registered = docs / args.pdf.name
    if registered.exists() and registered.read_bytes() != original:
        raise ValueError("Refusing to overwrite a different PDF")
    if not registered.exists():
        shutil.copy2(args.pdf, registered)
    ix = DocumentIndexer(
        database,
        docs,
        config.settings.rag,
        config.policies.privacy.api_transmission.documents,
        SystemIdFactory(),
        models_root=resolve(config.settings.paths.models_dir),
        auto_refresh=False,
    )
    store = GenerationIndex(ix)
    before = store.active()
    report = ix.sync()
    if report.errors:
        raise RuntimeError(report.errors)
    active = store.active()
    assert active is not None
    with ix._connection() as db:
        row = db.execute(
            """SELECT d.doc_id,c.markdown,c.metadata,e.path FROM documents d
            JOIN rag_document_content c USING(doc_id) JOIN rag_markdown_exports e USING(doc_id)
            WHERE d.path=?""",
            (args.pdf.name,),
        ).fetchone()
        assert row is not None
        md = export_root(database) / row["path"]
        metadata = json.loads(row["metadata"])
        chunks = [
            dict(r)
            for r in db.execute(
                """SELECT c.*,p.token_count FROM doc_chunks c
            JOIN rag_chunk_provenance p USING(chunk_id) WHERE c.doc_id=? ORDER BY c.ordinal""",
                (row["doc_id"],),
            )
        ]
        vectors = db.execute(
            """SELECT count(*) FROM rag_generation_vectors v
            JOIN doc_chunks c USING(chunk_id) WHERE c.doc_id=? AND v.generation=?""",
            (row["doc_id"], active["id"]),
        ).fetchone()[0]
        counts = {
            t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("documents", "doc_chunks", "rag_document_content", "rag_markdown_exports")
        }
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    assert md.read_bytes() == row["markdown"].encode("utf-8")
    assert vectors == len(chunks) and vectors > 0
    assert all(c["text"] == row["markdown"][c["start_char"] : c["end_char"]] for c in chunks)
    assert all(
        c["token_count"] is not None and c["token_count"] <= ix.settings.chunk_max_tokens
        for c in chunks
    )
    assert metadata["page_count"] == 6
    checks = [
        ("건축정책기본계획은 누가 몇 년마다 수립하나요?", "5년마다", 2),
        ("국가건축정책위원회는 위원장을 포함해 몇 명 이내로 구성하나요?", "30인", 3),
        ("국가건축정책위원회는 건축정책 보고서를 몇 년마다 누구에게 제출하나요?", "2년", 4),
    ]
    retrieval = []
    for question, needle, page in checks:
        hits = ix.search(question)
        rank = next(
            (
                i
                for i, h in enumerate(hits[:3], 1)
                if h.relative_path == args.pdf.name and needle in h.text and page in h.pages
            ),
            None,
        )
        retrieval.append(
            {
                "question": question,
                "expected_page": page,
                "rank": rank,
                "hits": [
                    {"source": h.relative_path, "pages": h.pages, "structure": h.structure}
                    for h in hits[:3]
                ],
            }
        )
        assert rank is not None
    mtime = md.stat().st_mtime_ns
    repeated = ix.sync()
    assert not repeated.errors and repeated.updated == 0
    assert store.active()["id"] == active["id"]
    assert md.stat().st_mtime_ns == mtime
    restored = None
    if not args.apply_runtime:
        md.unlink()
        restored = ix.sync()
        assert not restored.errors and restored.updated == 0
        assert md.read_bytes() == row["markdown"].encode("utf-8")
    assert args.pdf.read_bytes() == original and registered.read_bytes() == original
    assert integrity == "ok"
    result = {
        "passed": True,
        "tested_at": datetime.now().astimezone().isoformat(),
        "source": str(args.pdf),
        "source_sha256": source_hash,
        "source_fingerprints": source_fingerprints(),
        "backup": backup,
        "database": str(database),
        "markdown_file": str(md),
        "markdown_sha256": hashlib.sha256(md.read_bytes()).hexdigest(),
        "markdown_bytes": md.stat().st_size,
        "exact_db_match": True,
        "pages": metadata["page_count"],
        "removed_margin_lines": len(metadata["removed"]),
        "pdf_chunks": len(chunks),
        "pdf_vectors": vectors,
        "max_tokens": max(c["token_count"] for c in chunks),
        "counts": counts,
        "integrity": integrity,
        "initial_sync": asdict(report),
        "repeat_sync": asdict(repeated),
        "restored_sync": asdict(restored) if restored else None,
        "previous_generation": before["id"] if before else None,
        "active_generation": active["id"],
        "retrieval": retrieval,
        "scope": "Export, DB, embeddings, three retrieval checks; no answer-generation evaluation",
    }
    (output / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "passed",
                    "markdown_file",
                    "pdf_chunks",
                    "pdf_vectors",
                    "max_tokens",
                    "counts",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
