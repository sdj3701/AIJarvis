"""Explicitly import completed legacy JSONL conversations into semantic memory."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from app.config.defaults import DEFAULT_CONFIG_DIR  # noqa: E402
from app.config.loader import load_config  # noqa: E402
from app.config.models import PrivacyPolicy  # noqa: E402
from app.memory.store import RawRecord  # noqa: E402
from app.rag.semantic import SemanticMemory  # noqa: E402
from app.telemetry.masking import LogMasker  # noqa: E402


def import_conversations(
    raw_dir: Path,
    memory: SemanticMemory,
    privacy: PrivacyPolicy,
    *,
    now: datetime,
    apply: bool = False,
) -> dict[str, int]:
    """Read logs without changing them; never run implicitly at startup.

    Only unambiguous completed user/assistant pairs are eligible. Existing turns
    are left intact. Explicit reruns can retry vectors after an embedding outage.
    """
    if not memory.settings.enabled or not memory.settings.conversations_enabled:
        raise ValueError("대화 벡터 기억이 꺼져 있습니다.")
    if not raw_dir.is_dir():
        raise ValueError("원본 대화 로그 폴더를 찾을 수 없습니다.")
    counts: Counter[str] = Counter()
    groups: dict[tuple[str, str], list[RawRecord]] = defaultdict(list)
    for path in sorted(raw_dir.glob("*.jsonl")):
        counts["files"] += 1
        try:
            records = [
                RawRecord.from_mapping(json.loads(line))
                for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
        except (OSError, ValueError, TypeError):
            # Do not guess where a damaged file's completed turns end.
            counts["invalid_files"] += 1
            continue
        for record in records:
            groups[(record.session_id, record.turn_id)].append(record)

    existing: set[str] = set()
    if memory.path.exists():
        with closing(sqlite3.connect(
            memory.path.resolve().as_uri() + "?mode=ro", uri=True,
        )) as db:
            existing = {row[0] for row in db.execute("SELECT turn_id FROM conversation_turns")}
    masker = LogMasker.from_policy(privacy)
    blocked_markers = [
        privacy.mask.replacement.replace("{label}", detector.label)
        for detector in privacy.detectors if detector.action == "block"
    ]
    blocked_markers.append(privacy.mask.replacement.replace("{label}", "등록된 시크릿"))
    cutoff = now - timedelta(days=memory.settings.retention_days)
    pairs: list[tuple[RawRecord, RawRecord, str, str]] = []
    for records in groups.values():
        if len(records) != 2 or [r.role for r in records] != ["user", "assistant"]:
            counts["incomplete_or_ambiguous"] += 1
            continue
        question, answer = records
        if (question.request_id != answer.request_id or answer.ts < question.ts
                or any(r.untrusted or not r.content.strip() for r in records)
                or any((r.meta or {}).get("status") in {"error", "cancelled", "pending"}
                       for r in records)):
            counts["incomplete_or_ambiguous"] += 1
            continue
        text = question.content.strip()
        if text.startswith("/") and not text.startswith("/search "):
            counts["commands"] += 1
            continue
        if answer.ts < cutoff or answer.ts > now:
            counts["outside_retention"] += 1
            continue
        if answer.turn_id in existing:
            counts["existing"] += 1
            continue
        masked_q, q_findings = masker.mask_text(question.content)
        masked_a, a_findings = masker.mask_text(answer.content)
        if (any(f.action == "block" for f in (*q_findings, *a_findings))
                or any(marker in r.content for marker in blocked_markers for r in records)):
            counts["blocked"] += 1
            continue
        pairs.append((question, answer, masked_q, masked_a))

    counts["eligible"] = len(pairs)
    counts["imported"] = 0
    if apply:
        for question, answer, masked_q, masked_a in sorted(pairs, key=lambda p: p[1].ts):
            memory.remember_turn(
                session_id=question.session_id, turn_id=question.turn_id,
                question=masked_q, answer=masked_a, created_at=answer.ts,
                model=str((answer.meta or {}).get("model", "")),
            )
            counts["imported"] += 1
        memory.prune(now)
        memory.reindex()
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--apply", action="store_true", help="미리보기 결과를 실제 DB에 반영")
    args = parser.parse_args(argv)
    loaded = load_config(args.config_dir)
    root = loaded.settings.paths.data_root

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    memory = SemanticMemory(
        resolve(loaded.settings.paths.memory_db).with_name("semantic.sqlite3"),
        loaded.settings.rag.semantic,
    )
    now = datetime.now(UTC)
    backup = None
    if args.apply and memory.path.exists():
        backup = resolve(loaded.settings.paths.backups_dir) / (
            "semantic-before-conversation-import-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".sqlite3"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        with (
            closing(sqlite3.connect(
                memory.path.resolve().as_uri() + "?mode=ro", uri=True,
            )) as source,
            closing(sqlite3.connect(backup)) as destination,
        ):
            source.backup(destination)
    report = import_conversations(
        resolve(loaded.settings.paths.raw_dir), memory, loaded.policies.privacy,
        now=now, apply=args.apply,
    )
    print(json.dumps({
        "applied": args.apply, "database": str(memory.path),
        "backup": str(backup) if backup else None, "report": report,
        "semantic": memory.stats() if args.apply else None,
    }, ensure_ascii=False))
    return 1 if report.get("invalid_files") or memory.last_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
