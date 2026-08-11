from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.core.errors import ConfigError
from app.memory.migrations import REQUIRED_TABLES, REQUIRED_TRIGGERS, initialize_database
from scripts.bootstrap import CONFIG_COPIES, TREE_DIRECTORIES, bootstrap, create_tree, main


def _config_source(tmp_path: Path) -> Path:
    source = tmp_path / "examples"
    source.mkdir()
    for name in CONFIG_COPIES:
        (source / name).write_text(f"source: {name}\n", encoding="utf-8")
    return source


def test_create_tree_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "Jarvis"
    first = create_tree(root)
    second = create_tree(root)

    assert {action.status for action in first} == {"created"}
    assert {action.status for action in second} == {"skipped"}
    assert all((root / relative).is_dir() for relative in TREE_DIRECTORIES)


def test_bootstrap_copies_configs_and_never_overwrites(tmp_path: Path) -> None:
    root = tmp_path / "Jarvis"
    source = _config_source(tmp_path)
    first = bootstrap(root, config_source=source, min_free_bytes=0)
    settings = root / "config" / "settings.yaml"
    settings.write_text("user: preserved\n", encoding="utf-8")

    second = bootstrap(root, config_source=source, min_free_bytes=0)

    assert first.database_path.is_file()
    assert settings.read_text(encoding="utf-8") == "user: preserved\n"
    assert sum(action.status == "copied" for action in first.actions) == 3
    assert sum(action.status == "skipped" for action in second.actions) >= 12
    assert second.actions[-1].status == "verified"


def test_bootstrap_rejects_insufficient_disk_space(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="저장 공간"):
        bootstrap(
            tmp_path / "Jarvis",
            config_source=_config_source(tmp_path),
            min_free_bytes=10**30,
        )


def test_bootstrap_cli_prints_korean_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Jarvis"
    exit_code = main(["--data-root", str(root), "--min-free-gb", "0"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[완료] directory" in output
    assert "남은 공간:" in output


def test_database_has_documented_schema_and_pragmas(tmp_path: Path) -> None:
    database = tmp_path / "jarvis.sqlite3"
    initialize_database(database)

    with closing(sqlite3.connect(database)) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        triggers = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        meta = dict(connection.execute("SELECT key, value FROM meta"))
        assert tables >= REQUIRED_TABLES
        assert triggers >= REQUIRED_TRIGGERS
        assert meta["schema_version"] == "1"
        assert meta["audit_seq"] == "0"
        assert meta["created_at"]
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_old_sqlite_and_newer_database_are_rejected(tmp_path: Path) -> None:
    database = tmp_path / "jarvis.sqlite3"
    with pytest.raises(ConfigError, match=r"3\.34"):
        initialize_database(database, sqlite_version_info=(3, 33, 9))

    initialize_database(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        connection.commit()
    with pytest.raises(ConfigError, match="새로운 스키마"):
        initialize_database(database)


def test_record_state_churn_keeps_fts_and_embedding_consistent(tmp_path: Path) -> None:
    database = tmp_path / "jarvis.sqlite3"
    initialize_database(database)

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        values = (
            "rec_1",
            1,
            "fact",
            "pref.language",
            "한국어로 대답",
            "candidate",
            "user_explicit",
            "2026-08-11T10:00:00+09:00",
            "2026-08-11T10:00:00+09:00",
        )
        connection.execute(
            """INSERT INTO records(
                   id, schema_version, kind, key, value, status, source_kind,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        connection.execute(
            "INSERT INTO embeddings VALUES (?, ?, ?, ?, ?)",
            ("rec_1", "test", 1, b"1234", "2026-08-11T10:00:00+09:00"),
        )
        connection.execute("UPDATE records SET status='confirmed' WHERE id='rec_1'")
        assert (
            connection.execute(
                "SELECT count(*) FROM records_fts WHERE records_fts MATCH '한국어'"
            ).fetchone()[0]
            == 1
        )
        connection.execute("UPDATE records SET status='superseded' WHERE id='rec_1'")
        connection.execute("UPDATE records SET status='deleted' WHERE id='rec_1'")

        assert connection.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM records_fts WHERE records_fts MATCH '한국어'"
            ).fetchone()[0]
            == 0
        )
        connection.execute("INSERT INTO records_fts(records_fts) VALUES('integrity-check')")


def test_confirmed_key_and_task_idempotency_are_unique(tmp_path: Path) -> None:
    database = tmp_path / "jarvis.sqlite3"
    initialize_database(database)
    now = "2026-08-11T10:00:00+09:00"

    with closing(sqlite3.connect(database)) as connection:
        base = (1, "fact", "same", "value", "confirmed", "user_explicit", now, now)
        connection.execute(
            """INSERT INTO records(
                   id, schema_version, kind, key, value, status, source_kind,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("rec_1", *base),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO records(
                       id, schema_version, kind, key, value, status, source_kind,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("rec_2", *base),
            )

        connection.execute(
            "INSERT INTO sessions(session_id, started_at, raw_path) VALUES (?, ?, ?)",
            ("ses_1", now, "memory/raw/ses_1.jsonl"),
        )
        connection.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("task_1", "ses_1", "req_1", "goal", "running", now, now, 8),
        )
        step = ("task_1", 1, "tool", "hash", "idem-1", "pending")
        connection.execute(
            """INSERT INTO task_steps(
                   task_id, step_no, tool_name, args_hash, idempotency_key, state
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            step,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO task_steps(
                       task_id, step_no, tool_name, args_hash, idempotency_key, state
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                ("task_1", 2, "tool", "hash", "idem-1", "pending"),
            )


def test_document_delete_cascades_to_chunks_and_fts(tmp_path: Path) -> None:
    database = tmp_path / "jarvis.sqlite3"
    initialize_database(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("doc_1", "notes/a.md", "hash", "local_only", "now", 10, 1),
        )
        connection.execute(
            "INSERT INTO doc_chunks VALUES (?, ?, ?, ?, ?, ?)",
            ("chunk_1", "doc_1", 0, "검색 가능한 본문", 0, 9),
        )
        connection.execute("DELETE FROM documents WHERE doc_id='doc_1'")

        assert connection.execute("SELECT count(*) FROM doc_chunks").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM doc_chunks_fts WHERE doc_chunks_fts MATCH '검색'"
            ).fetchone()[0]
            == 0
        )
        connection.execute("INSERT INTO doc_chunks_fts(doc_chunks_fts) VALUES('integrity-check')")
