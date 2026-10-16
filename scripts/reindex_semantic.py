"""Build the local learned document index without starting chat or web search."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from app.config.defaults import DEFAULT_CONFIG_DIR  # noqa: E402
from app.config.loader import load_config  # noqa: E402
from app.core.ids import SystemIdFactory  # noqa: E402
from app.memory.migrations import initialize_database  # noqa: E402
from app.rag.indexer import DocumentIndexer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args()
    loaded = load_config(args.config_dir)
    root = loaded.settings.paths.data_root

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    db = resolve(loaded.settings.paths.memory_db)
    initialize_database(db)
    indexer = DocumentIndexer(
        database_path=db,
        docs_root=resolve(loaded.settings.paths.docs_dir),
        models_root=resolve(loaded.settings.paths.models_dir),
        settings=loaded.settings.rag,
        document_policy=loaded.policies.privacy.api_transmission.documents,
        ids=SystemIdFactory(),
    )
    if indexer.semantic is None:
        parser.error("rag.semantic.enabled=true가 필요합니다.")
    report = indexer.sync()
    indexer.semantic.reindex()
    print(
        json.dumps(
            {
                "indexed": report.indexed,
                "updated": report.updated,
                "removed": report.removed,
                "errors": report.errors,
                "semantic": indexer.semantic.stats(),
            },
            ensure_ascii=False,
        )
    )
    return 1 if report.errors or indexer.semantic.last_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
