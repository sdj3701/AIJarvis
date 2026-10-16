"""Install the pinned local reranker. Only this explicit setup step uses the network."""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config.defaults import DEFAULT_CONFIG_DIR
from app.config.loader import load_settings
from app.rag.reranker import MODEL_DIRECTORY, MODEL_FILES, MODEL_REPO, MODEL_REVISION


def install(models_root: Path) -> Path:
    target = models_root / MODEL_DIRECTORY
    for name, expected in MODEL_FILES.items():
        destination = target / name
        if destination.exists():
            with destination.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == expected:
                    continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}"
        print(f"Downloading {name}", flush=True)
        digest = hashlib.sha256()
        try:
            with (
                urllib.request.urlopen(url, timeout=60) as response,
                temporary.open("wb") as stream,
            ):
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    stream.write(block)
            if digest.hexdigest() != expected:
                raise ValueError(f"Reranker artifact checksum mismatch: {name}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args()
    settings = load_settings(args.config_dir / "settings.yaml")
    models_root = settings.paths.models_dir
    if not models_root.is_absolute():
        models_root = settings.paths.data_root / models_root
    print(install(models_root))


if __name__ == "__main__":
    main()
