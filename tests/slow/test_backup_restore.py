"""Slow test verifying secure backup creation and isolated restore."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.atomic import write_atomic
from app.memory.migrations import initialize_database
from scripts.backup import create_backup, restore_backup

pytestmark = [pytest.mark.phase6, pytest.mark.slow, pytest.mark.security]


def test_backup_and_restore_cycle(tmp_path: Path) -> None:
    data_root = tmp_path / "data_root"
    target_backup_dir = tmp_path / "backups"
    restore_target_dir = tmp_path / "restore_test"

    memory_dir = data_root / "memory"
    raw_dir = memory_dir / "raw"
    config_dir = data_root / "config"
    raw_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    # 1. Initialize SQLite database and insert dummy confirmed record
    db_path = memory_dir / "jarvis.sqlite3"
    now = datetime.now(timezone.utc)
    initialize_database(db_path, created_at=now)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO records (id, schema_version, kind, key, value, status, sensitivity, source_kind, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rec_01TEST00000000000000000001",
                1,
                "fact",
                "pref.food",
                "사용자는 김치찌개를 선호함",
                "confirmed",
                "normal",
                "user_explicit",
                now.isoformat(),
                now.isoformat(),
            ),
        )
        conn.commit()

    # 2. Add raw log file
    raw_log = raw_dir / "ses_test.jsonl"
    raw_record = {"event": "chat.message", "role": "user", "content": "김치찌개 좋아해"}
    write_atomic(raw_log, (json.dumps(raw_record) + "\n").encode("utf-8"))

    # 3. Add config file
    config_file = config_dir / "settings.yaml"
    write_atomic(config_file, b"app:\n  language: ko\n")

    # 4. Create backup with custom password
    password = "SuperSecretPassword123!"
    archive_path = create_backup(
        data_root=data_root,
        target_dir=target_backup_dir,
        password=password,
    )
    assert archive_path.exists()
    assert archive_path.stat().st_size > 0

    # 5. Verify restore fails with wrong password
    with pytest.raises(ValueError, match="태그 검증 실패|암호가 틀렸거나"):
        restore_backup(
            archive_path=archive_path,
            target_dir=restore_target_dir,
            password="WrongPassword!",
        )

    # 6. Verify restore fails when target directory is not empty
    non_empty_target = tmp_path / "non_empty"
    non_empty_target.mkdir()
    (non_empty_target / "existing.txt").write_text("stay", encoding="utf-8")
    with pytest.raises(ValueError, match="비어 있지 않습니다"):
        restore_backup(
            archive_path=archive_path,
            target_dir=non_empty_target,
            password=password,
        )

    # 7. Verify restore fails when archive is tampered
    tampered_archive = tmp_path / "tampered.jbak"
    archive_bytes = bytearray(archive_path.read_bytes())
    archive_bytes[-10] ^= 0xFF  # Flip bits in ciphertext
    tampered_archive.write_bytes(bytes(archive_bytes))
    with pytest.raises(ValueError, match="태그 검증 실패|변조"):
        restore_backup(
            archive_path=tampered_archive,
            target_dir=restore_target_dir,
            password=password,
        )

    # 8. Clean restore to restore_target_dir
    restore_target_dir.mkdir(parents=True, exist_ok=True)
    # Ensure empty directory
    for item in restore_target_dir.iterdir():
        if item.is_file():
            item.unlink()
    shutil_rm = restore_target_dir / "sub"
    if shutil_rm.exists():
        import shutil
        shutil.rmtree(shutil_rm)

    # Recreate as completely clean empty dir
    import shutil
    shutil.rmtree(restore_target_dir)

    success = restore_backup(
        archive_path=archive_path,
        target_dir=restore_target_dir,
        password=password,
        verify_retrieval=True,
    )
    assert success is True

    # 9. Check restored database integrity and record
    restored_db = restore_target_dir / "memory" / "jarvis.sqlite3"
    assert restored_db.exists()
    with sqlite3.connect(restored_db) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        assert cursor.fetchone()[0] == "ok"

        cursor.execute("SELECT key, value FROM records WHERE id='rec_01TEST00000000000000000001'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "pref.food"
        assert row[1] == "사용자는 김치찌개를 선호함"

    # 10. Check raw log
    restored_raw = restore_target_dir / "memory" / "raw" / "ses_test.jsonl"
    assert restored_raw.exists()
    raw_data = json.loads(restored_raw.read_text(encoding="utf-8").strip())
    assert raw_data["content"] == "김치찌개 좋아해"
