# 파이썬 공부 | scripts/tests/unit/test_bootstrap.py
# bootstrap 관련 개별 기능을 검증하는 테스트입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from app.core.errors import ConfigError
from app.memory.migrations import REQUIRED_TABLES, REQUIRED_TRIGGERS, initialize_database
from scripts.bootstrap import CONFIG_COPIES, TREE_DIRECTORIES, bootstrap, create_tree, main

# 오른쪽 식을 계산한 값을 pytestmark에 대입합니다.
pytestmark = pytest.mark.phase0


# _config_source(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: tmp_path.
# 반환 타입 힌트: Path.
def _config_source(tmp_path: Path) -> Path:
    # 오른쪽 식을 계산한 값을 source에 대입합니다.
    source = tmp_path / "examples"
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    source.mkdir()
    # for 반복문: 대상의 항목을 하나씩 name에 대입하며 아래 블록을 실행합니다.
    for name in CONFIG_COPIES:
        # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
        (source / name).write_text(f"source: {name}\n", encoding="utf-8")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return source


# pytest가 test_create_tree_is_idempotent()을 실행해 아래 상황이 기대대로 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_create_tree_is_idempotent(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # create_tree()의 반환값을 first에 대입합니다.
    first = create_tree(root)
    # create_tree()의 반환값을 second에 대입합니다.
    second = create_tree(root)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert {action.status for action in first} == {"created"}
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert {action.status for action in second} == {"skipped"}
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert all((root / relative).is_dir() for relative in TREE_DIRECTORIES)


# pytest가 test_bootstrap_copies_configs_and_never_overwrites()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bootstrap_copies_configs_and_never_overwrites(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # _config_source()의 반환값을 source에 대입합니다.
    source = _config_source(tmp_path)
    # bootstrap()의 반환값을 first에 대입합니다.
    first = bootstrap(root, config_source=source, min_free_bytes=0)
    # 오른쪽 식을 계산한 값을 settings에 대입합니다.
    settings = root / "config" / "settings.yaml"
    # 문자열을 파일에 기록합니다. encoding 인자는 문자 저장 방식을 정합니다.
    settings.write_text("user: preserved\n", encoding="utf-8")

    # bootstrap()의 반환값을 second에 대입합니다.
    second = bootstrap(root, config_source=source, min_free_bytes=0)

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert first.database_path.is_file()
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert settings.read_text(encoding="utf-8") == "user: preserved\n"
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sum(action.status == "copied" for action in first.actions) == 3
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert sum(action.status == "skipped" for action in second.actions) >= 12
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert second.actions[-1].status == "verified"


# pytest가 test_bootstrap_rejects_insufficient_disk_space()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bootstrap_rejects_insufficient_disk_space(tmp_path: Path) -> None:
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError, match="저장 공간"):
        # bootstrap()을 호출해 작업을 수행합니다.
        bootstrap(
            tmp_path / "Jarvis",
            config_source=_config_source(tmp_path),
            min_free_bytes=10**30,
        )


# pytest가 test_bootstrap_cli_prints_korean_summary()을 실행해 아래 상황이 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path, capsys.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bootstrap_cli_prints_korean_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"
    # main()의 반환값을 exit_code에 대입합니다.
    exit_code = main(["--data-root", str(root), "--min-free-gb", "0"])

    # 오른쪽 식을 계산한 값을 output에 대입합니다.
    output = capsys.readouterr().out
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert exit_code == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[완료] directory" in output
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "남은 공간:" in output


# pytest가 test_bootstrap_script_runs_directly_from_documented_command()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_bootstrap_script_runs_directly_from_documented_command(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 root에 대입합니다.
    root = tmp_path / "Jarvis"

    # subprocess.run()의 반환값을 result에 대입합니다.
    result = subprocess.run(
        [
            sys.executable,
            "scripts/bootstrap.py",
            "--data-root",
            str(root),
            "--min-free-gb",
            "0",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert result.returncode == 0
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert "[완료] directory" in result.stdout
    # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
    assert (root / "memory" / "jarvis.sqlite3").is_file()


# pytest가 test_database_has_documented_schema_and_pragmas()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_database_has_documented_schema_and_pragmas(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = tmp_path / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection:
        # 오른쪽 식을 계산한 값을 tables에 대입합니다.
        # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # 오른쪽 식을 계산한 값을 triggers에 대입합니다.
        # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
        triggers = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        # dict()의 반환값을 meta에 대입합니다.
        meta = dict(connection.execute("SELECT key, value FROM meta"))
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert tables >= REQUIRED_TABLES
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert triggers >= REQUIRED_TRIGGERS
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert meta["schema_version"] == "1"
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert meta["audit_seq"] == "0"
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert meta["created_at"]
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("PRAGMA foreign_keys = ON")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


# pytest가 test_old_sqlite_and_newer_database_are_rejected()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_old_sqlite_and_newer_database_are_rejected(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = tmp_path / "jarvis.sqlite3"
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError, match=r"3\.34"):
        # initialize_database()을 호출해 작업을 수행합니다.
        initialize_database(database, sqlite_version_info=(3, 33, 9))

    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        # 데이터베이스 변경 내용을 확정합니다.
        connection.commit()
    # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
    with pytest.raises(ConfigError, match="새로운 스키마"):
        # initialize_database()을 호출해 작업을 수행합니다.
        initialize_database(database)


# pytest가 test_record_state_churn_keeps_fts_and_embedding_consistent()을 실행해 아래 상황이
# 기대대로 동작하는지
# 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_record_state_churn_keeps_fts_and_embedding_consistent(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = tmp_path / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database)

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("PRAGMA foreign_keys = ON")
        # values에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
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
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            """INSERT INTO records(
                   id, schema_version, kind, key, value, status, source_kind,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "INSERT INTO embeddings VALUES (?, ?, ?, ?, ?)",
            ("rec_1", "test", 1, b"1234", "2026-08-11T10:00:00+09:00"),
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("UPDATE records SET status='confirmed' WHERE id='rec_1'")
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert (
            connection.execute(
                "SELECT count(*) FROM records_fts WHERE records_fts MATCH '한국어'"
            ).fetchone()[0]
            == 1
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("UPDATE records SET status='superseded' WHERE id='rec_1'")
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("UPDATE records SET status='deleted' WHERE id='rec_1'")

        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert connection.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 0
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert (
            connection.execute(
                "SELECT count(*) FROM records_fts WHERE records_fts MATCH '한국어'"
            ).fetchone()[0]
            == 0
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("INSERT INTO records_fts(records_fts) VALUES('integrity-check')")


# pytest가 test_confirmed_key_and_task_idempotency_are_unique()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_confirmed_key_and_task_idempotency_are_unique(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = tmp_path / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database)
    # now에 문자열을 대입합니다.
    now = "2026-08-11T10:00:00+09:00"

    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection:
        # base에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        base = (1, "fact", "same", "value", "confirmed", "user_explicit", now, now)
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            """INSERT INTO records(
                   id, schema_version, kind, key, value, status, source_kind,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("rec_1", *base),
        )
        # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
        with pytest.raises(sqlite3.IntegrityError):
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """INSERT INTO records(
                       id, schema_version, kind, key, value, status, source_kind,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("rec_2", *base),
            )

        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "INSERT INTO sessions(session_id, started_at, raw_path) VALUES (?, ?, ?)",
            ("ses_1", now, "memory/raw/ses_1.jsonl"),
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("task_1", "ses_1", "req_1", "goal", "running", now, now, 8),
        )
        # step에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        step = ("task_1", 1, "tool", "hash", "idem-1", "pending")
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            """INSERT INTO task_steps(
                   task_id, step_no, tool_name, args_hash, idempotency_key, state
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            step,
        )
        # 이 블록에서 지정한 예외가 발생해야 테스트가 통과합니다. 예외가 없으면 실패합니다.
        with pytest.raises(sqlite3.IntegrityError):
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            connection.execute(
                """INSERT INTO task_steps(
                       task_id, step_no, tool_name, args_hash, idempotency_key, state
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                ("task_1", 2, "tool", "hash", "idem-1", "pending"),
            )


# pytest가 test_document_delete_cascades_to_chunks_and_fts()을 실행해 아래 상황이 기대대로
# 동작하는지 확인합니다.
# 입력: tmp_path.
# 반환 타입 힌트: 별도 결과 없음(None).
def test_document_delete_cascades_to_chunks_and_fts(tmp_path: Path) -> None:
    # 오른쪽 식을 계산한 값을 database에 대입합니다.
    database = tmp_path / "jarvis.sqlite3"
    # initialize_database()을 호출해 작업을 수행합니다.
    initialize_database(database)
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with closing(sqlite3.connect(database)) as connection:
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("PRAGMA foreign_keys = ON")
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("doc_1", "notes/a.md", "hash", "local_only", "now", 10, 1),
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute(
            "INSERT INTO doc_chunks VALUES (?, ?, ?, ?, ?, ?)",
            ("chunk_1", "doc_1", 0, "검색 가능한 본문", 0, 9),
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("DELETE FROM documents WHERE doc_id='doc_1'")

        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert connection.execute("SELECT count(*) FROM doc_chunks").fetchone()[0] == 0
        # assert 뒤의 조건이 참인지 검사합니다. 거짓이면 AssertionError가 발생합니다.
        assert (
            connection.execute(
                "SELECT count(*) FROM doc_chunks_fts WHERE doc_chunks_fts MATCH '검색'"
            ).fetchone()[0]
            == 0
        )
        # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
        connection.execute("INSERT INTO doc_chunks_fts(doc_chunks_fts) VALUES('integrity-check')")
