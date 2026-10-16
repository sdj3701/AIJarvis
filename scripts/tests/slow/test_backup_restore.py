# 파이썬 공부 | scripts/tests/slow/test_backup_restore.py
# backup_restore 관련 시간이 걸리는 복구·반복 실행을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# pytestmark에 리스트(순서가 있고 수정 가능)을 대입합니다.
pytestmark = [pytest.mark.phase6, pytest.mark.slow, pytest.mark.security]


# pytest가 test_backup_and_restore_cycle()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_backup_and_restore_cycle(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 data_root에 대입합니다.
    data_root = tmp_path / "data_root"
    # 오른쪽 식을 계산한 값을 target_backup_dir에 대입합니다.
    target_backup_dir = tmp_path / "backups"
    # 오른쪽 식을 계산한 값을 restore_target_dir에 대입합니다.
    restore_target_dir = tmp_path / "restore_test"

    # 오른쪽 식을 계산한 값을 memory_dir에 대입합니다.
    memory_dir = data_root / "memory"
    # 오른쪽 식을 계산한 값을 raw_dir에 대입합니다.
    raw_dir = memory_dir / "raw"
    # 오른쪽 식을 계산한 값을 config_dir에 대입합니다.
    config_dir = data_root / "config"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    raw_dir.mkdir(parents=True, exist_ok=True)
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    config_dir.mkdir(parents=True, exist_ok=True)

    # 1. Initialize SQLite database and insert dummy confirmed record
    # 오른쪽 식을 계산한 값을 db_path에 대입합니다.
    db_path = memory_dir / "jarvis.sqlite3"
    # datetime.now()의 반환값을 now에 대입합니다.
    now = datetime.now(timezone.utc)
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(db_path, created_at=now)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(db_path) as conn:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
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
        # 데이터베이스 변경 내용을 확정합니다.
        conn.commit()

    # 2. Add raw log file
    # 오른쪽 식을 계산한 값을 raw_log에 대입합니다.
    raw_log = raw_dir / "ses_test.jsonl"
    # raw_record에 딕셔너리(키와 값의 쌍)을 대입합니다.
    raw_record = {"event": "chat.message", "role": "user", "content": "김치찌개 좋아해"}
    # write_atomic()을 호출해 작업을 수행합니다.
    write_atomic(raw_log, (json.dumps(raw_record) + "\n").encode("utf-8"))

    # 3. Add config file
    # 오른쪽 식을 계산한 값을 config_file에 대입합니다.
    config_file = config_dir / "settings.yaml"
    # write_atomic()을 호출해 작업을 수행합니다.
    write_atomic(config_file, b"app:\n  language: ko\n")

    # 4. Create backup with custom password
    # password에 문자열을 대입합니다.
    password = "SuperSecretPassword123!"
    # create_backup()의 반환값을 archive_path에 대입합니다.
    archive_path = create_backup(
        data_root=data_root,
        target_dir=target_backup_dir,
        password=password,
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert archive_path.exists()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert archive_path.stat().st_size > 0

    # 5. Verify restore fails with wrong password
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="태그 검증 실패|암호가 틀렸거나"):
        # restore_backup()을 호출해 작업을 수행합니다.
        restore_backup(
            archive_path=archive_path,
            target_dir=restore_target_dir,
            password="WrongPassword!",
        )

    # 6. Verify restore fails when target directory is not empty
    # 오른쪽 식을 계산한 값을 non_empty_target에 대입합니다.
    non_empty_target = tmp_path / "non_empty"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    non_empty_target.mkdir()
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    (non_empty_target / "existing.txt").write_text("stay", encoding="utf-8")
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="비어 있지 않습니다"):
        # restore_backup()을 호출해 작업을 수행합니다.
        restore_backup(
            archive_path=archive_path,
            target_dir=non_empty_target,
            password=password,
        )

    # 7. Verify restore fails when archive is tampered
    # 오른쪽 식을 계산한 값을 tampered_archive에 대입합니다.
    tampered_archive = tmp_path / "tampered.jbak"
    # bytearray()의 반환값을 archive_bytes에 대입합니다.
    archive_bytes = bytearray(archive_path.read_bytes())
    # 복합 대입: 기존 값에 오른쪽 값을 연산한 결과를 다시 저장합니다.
    archive_bytes[-10] ^= 0xFF  # Flip bits in ciphertext
    # 바이트 데이터를 파일에 기록합니다.
    tampered_archive.write_bytes(bytes(archive_bytes))
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ValueError, match="태그 검증 실패|변조"):
        # restore_backup()을 호출해 작업을 수행합니다.
        restore_backup(
            archive_path=tampered_archive,
            target_dir=restore_target_dir,
            password=password,
        )

    # 8. Clean restore to restore_target_dir
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    restore_target_dir.mkdir(parents=True, exist_ok=True)
    # Ensure empty directory
    # for 반복문: 대상의 항목을 하나씩 item에 대입하며 아래 블록을 실행합니다.
    for item in restore_target_dir.iterdir():
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: item.is_file().
        if item.is_file():
            # 지정한 파일 또는 링크를 삭제합니다.
            item.unlink()
    # 오른쪽 식을 계산한 값을 shutil_rm에 대입합니다.
    shutil_rm = restore_target_dir / "sub"
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: shutil_rm.exists().
    if shutil_rm.exists():
        import shutil
        # shutil.rmtree()을 호출해 작업을 수행합니다.
        shutil.rmtree(shutil_rm)

    # Recreate as completely clean empty dir
    import shutil
    # shutil.rmtree()을 호출해 작업을 수행합니다.
    shutil.rmtree(restore_target_dir)

    # restore_backup()의 반환값을 success에 대입합니다.
    success = restore_backup(
        archive_path=archive_path,
        target_dir=restore_target_dir,
        password=password,
        verify_retrieval=True,
    )
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert success is True

    # 9. Check restored database integrity and record
    # 오른쪽 식을 계산한 값을 restored_db에 대입합니다.
    restored_db = restore_target_dir / "memory" / "jarvis.sqlite3"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert restored_db.exists()
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with sqlite3.connect(restored_db) as conn:
        # conn.cursor()의 반환값을 cursor에 대입합니다.
        cursor = conn.cursor()
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        cursor.execute("PRAGMA integrity_check;")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert cursor.fetchone()[0] == "ok"

        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        cursor.execute("SELECT key, value FROM records WHERE id='rec_01TEST00000000000000000001'")
        # cursor.fetchone()의 반환값을 row에 대입합니다.
        row = cursor.fetchone()
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert row is not None
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert row[0] == "pref.food"
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert row[1] == "사용자는 김치찌개를 선호함"

    # 10. Check raw log
    # 오른쪽 식을 계산한 값을 restored_raw에 대입합니다.
    restored_raw = restore_target_dir / "memory" / "raw" / "ses_test.jsonl"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert restored_raw.exists()
    # json.loads()의 반환값을 raw_data에 대입합니다.
    raw_data = json.loads(restored_raw.read_text(encoding="utf-8").strip())
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert raw_data["content"] == "김치찌개 좋아해"
