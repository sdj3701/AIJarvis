"""Jarvis SQLite3 데이터베이스 상태 점검 및 데이터 조회 유틸리티."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# 기본 DB 경로 설정
DEFAULT_DB = Path(r"D:\Jarvis-v2-dev\memory\jarvis.sqlite3")
V1_DB = Path(r"D:\Jarvis\memory\jarvis.sqlite3")


def inspect_db(db_path: Path) -> None:
    if not db_path.exists():
        print(f"[-] 파일이 존재하지 않습니다: {db_path}")
        return

    print("=" * 70)
    print(f"[*] 대상 데이터베이스: {db_path}")
    print(f"[*] 파일 크기: {db_path.stat().st_size:,} bytes")
    print("=" * 70)

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 1. 무결성 검사
        cursor.execute("PRAGMA integrity_check;")
        check_result = cursor.fetchall()
        integrity_ok = len(check_result) == 1 and check_result[0][0] == "ok"
        status_text = "정상 (OK)" if integrity_ok else f"경고: {check_result}"
        print(f"[1] 무결성 검사(integrity_check): {status_text}\n")

        # 2. 테이블 목록 및 행 수
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        tables = [row[0] for row in cursor.fetchall()]
        print(f"[2] 테이블 목록 (총 {len(tables)}개):")
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM [{table}];")
                cnt = cursor.fetchone()[0]
                print(f"    - {table:<25}: {cnt:>6,} 건")
            except Exception as e:
                print(f"    - {table:<25}: 오류 ({e})")

        # 3. 최근 세션 요약 (sessions 테이블 존재 시)
        if "sessions" in tables:
            print("\n[3] 최근 세션 (최대 5건):")
            cursor.execute(
                "SELECT session_id, started_at, end_reason, turn_count FROM sessions ORDER BY started_at DESC LIMIT 5;"
            )
            for row in cursor.fetchall():
                print(f"    - {row[0]} | 시작: {row[1]} | 종료: {row[2]} | 턴수: {row[3]}")

        # 4. 기억 레코드 샘플 (records 테이블 존재 시)
        if "records" in tables:
            print("\n[4] 기억 레코드 (최근 5건):")
            cursor.execute(
                "SELECT id, kind, key, value, created_at FROM records ORDER BY created_at DESC LIMIT 5;"
            )
            for row in cursor.fetchall():
                val_snippet = (row[3][:60] + "...") if row[3] and len(row[3]) > 60 else row[3]
                print(f"    - [{row[1]}] {row[2]}: {val_snippet}")

        # 5. 커맨드 예시 샘플 (command_examples 테이블 존재 시)
        if "command_examples" in tables:
            print("\n[5] 등록된 커맨드 예시 (command_examples):")
            cursor.execute(
                "SELECT id, phrase, app, provenance FROM command_examples LIMIT 5;"
            )
            for row in cursor.fetchall():
                print(f"    - [{row[2]}] \"{row[1]}\" ({row[3]})")

        conn.close()
        print("\n" + "=" * 70)
        print("[+] 조회가 성공적으로 완료되었습니다.")
        print("=" * 70)
    except Exception as e:
        print(f"[!] 데이터베이스 조회 중 오류 발생: {e}")


def main() -> None:
    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description="Jarvis SQLite3 DB 상태 및 내용 조회기")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB if DEFAULT_DB.exists() else V1_DB,
        help="조회할 sqlite3 파일 경로",
    )
    args = parser.parse_args()
    inspect_db(args.db)


if __name__ == "__main__":
    main()
