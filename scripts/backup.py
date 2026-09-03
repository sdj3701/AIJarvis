"""Secure backup and restore tool for Jarvis operational data."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.core.atomic import write_atomic  # noqa: E402
from app.core.canonical import canonical_json  # noqa: E402

MAGIC_HEADER = b"JARVIS_BACKUP_V1"
PBKDF2_ITERATIONS = 100_000
KEYRING_SERVICE = "jarvis"
KEYRING_USERNAME = "backup_key"
DEFAULT_TEST_KEY = "jarvis-default-backup-key-v05"


def _derive_keys(password: str, salt: bytes) -> tuple[bytes, bytes]:
    """Derive 32-byte encryption key and 32-byte HMAC key using PBKDF2-HMAC-SHA256."""
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=64,
    )
    enc_key = key_material[:32]
    mac_key = key_material[32:]
    return enc_key, mac_key


def _keystream_sha256(key: bytes, nonce: bytes, length: int) -> bytes:
    """Deterministic stream cipher based on HMAC-SHA256 in counter mode."""
    blocks: list[bytes] = []
    block_index = 0
    generated = 0
    while generated < length:
        counter_bytes = struct.pack(">Q", block_index)
        block = hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest()
        blocks.append(block)
        generated += len(block)
        block_index += 1
    return b"".join(blocks)[:length]


def encrypt_payload(plaintext: bytes, password: str) -> bytes:
    """Encrypt payload with PBKDF2-HMAC-SHA256, CTR keystream, and HMAC authentication tag."""
    salt = os.urandom(16)
    nonce = os.urandom(16)
    enc_key, mac_key = _derive_keys(password, salt)
    keystream = _keystream_sha256(enc_key, nonce, len(plaintext))
    ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream, strict=True))
    tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    return MAGIC_HEADER + salt + nonce + tag + ciphertext


def decrypt_payload(encrypted: bytes, password: str) -> bytes:
    """Verify HMAC authentication tag and decrypt payload."""
    header_len = len(MAGIC_HEADER)
    if not encrypted.startswith(MAGIC_HEADER):
        raise ValueError("유효한 Jarvis 백업 아카이브 헤더가 아닙니다.")
    offset = header_len
    salt = encrypted[offset : offset + 16]
    offset += 16
    nonce = encrypted[offset : offset + 16]
    offset += 16
    expected_tag = encrypted[offset : offset + 32]
    offset += 32
    ciphertext = encrypted[offset:]

    enc_key, mac_key = _derive_keys(password, salt)
    actual_tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_tag, actual_tag):
        raise ValueError("백업 아카이브 암호화 태그 검증 실패: 암호가 틀렸거나 데이터가 변조되었습니다.")

    keystream = _keystream_sha256(enc_key, nonce, len(ciphertext))
    return bytes(c ^ k for c, k in zip(ciphertext, keystream, strict=True))


def _get_backup_password(explicit: str | None) -> str:
    if explicit:
        return explicit
    import keyring

    try:
        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if stored:
            return stored
    except Exception:
        pass
    return DEFAULT_TEST_KEY


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def create_backup(
    data_root: Path,
    target_dir: Path,
    password: str | None = None,
) -> Path:
    """Create an encrypted backup of data_root to target_dir using atomic steps."""
    target_dir.mkdir(parents=True, exist_ok=True)
    resolved_password = _get_backup_password(password)

    staging_dir = Path(tempfile.mkdtemp(prefix="jarvis_backup_staging_"))
    try:
        manifest_files: dict[str, dict[str, Any]] = {}

        # 1. SQLite Online Backup
        db_path = data_root / "memory" / "jarvis.sqlite3"
        if db_path.exists():
            staging_db_dir = staging_dir / "memory"
            staging_db_dir.mkdir(parents=True, exist_ok=True)
            staging_db = staging_db_dir / "jarvis.sqlite3"
            with sqlite3.connect(db_path) as src_conn, sqlite3.connect(staging_db) as dst_conn:
                src_conn.backup(dst_conn)
            manifest_files["memory/jarvis.sqlite3"] = {
                "size": staging_db.stat().st_size,
                "sha256": _sha256_file(staging_db),
            }

        # 2. Copy raw logs
        raw_dir = data_root / "memory" / "raw"
        if raw_dir.exists():
            staging_raw = staging_dir / "memory" / "raw"
            staging_raw.mkdir(parents=True, exist_ok=True)
            for raw_file in raw_dir.glob("*.jsonl"):
                dst_file = staging_raw / raw_file.name
                shutil.copyfile(raw_file, dst_file)
                manifest_files[f"memory/raw/{raw_file.name}"] = {
                    "size": dst_file.stat().st_size,
                    "sha256": _sha256_file(dst_file),
                }

        # 3. Copy config
        config_dir = data_root / "config"
        if config_dir.exists():
            staging_config = staging_dir / "config"
            staging_config.mkdir(parents=True, exist_ok=True)
            for cfg_file in config_dir.glob("*.yaml"):
                dst_file = staging_config / cfg_file.name
                shutil.copyfile(cfg_file, dst_file)
                manifest_files[f"config/{cfg_file.name}"] = {
                    "size": dst_file.stat().st_size,
                    "sha256": _sha256_file(dst_file),
                }

        # 4. Write manifest
        manifest_data = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_data_root": str(data_root),
            "files": manifest_files,
        }
        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_bytes(canonical_json(manifest_data) + b"\n")

        # 5. Build ZIP payload in-memory or tempfile
        zip_temp = Path(tempfile.mktemp(prefix="jarvis_zip_"))
        with zipfile.ZipFile(zip_temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file():
                    rel_path = file_path.relative_to(staging_dir).as_posix()
                    archive.write(file_path, arcname=rel_path)

        zip_bytes = zip_temp.read_bytes()
        zip_temp.unlink(missing_ok=True)

        # 6. Encrypt payload
        encrypted_bytes = encrypt_payload(zip_bytes, resolved_password)

        # 7. Write to target archive
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"backup-{timestamp_str}.jbak"
        final_archive_path = target_dir / archive_name
        write_atomic(final_archive_path, encrypted_bytes)

        # 8. Verify hash of written target
        final_sha256 = _sha256_file(final_archive_path)
        expected_sha256 = hashlib.sha256(encrypted_bytes).hexdigest()
        if final_sha256 != expected_sha256:
            raise IOError("대상 위치의 백업 아카이브 해시 검증 실패")

        print(f"[OK] 암호화 백업 완료: {final_archive_path} (크기: {len(encrypted_bytes)} bytes)")
        return final_archive_path
    finally:
        # 9. Clean up staging folder completely
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def restore_backup(
    archive_path: Path,
    target_dir: Path,
    password: str | None = None,
    verify_retrieval: bool = True,
) -> bool:
    """Restore an encrypted backup into an empty target_dir and verify integrity."""
    if target_dir.exists() and any(target_dir.iterdir()):
        raise ValueError(
            f"복원 대상 디렉터리가 비어 있지 않습니다: {target_dir}. "
            "운영 데이터 손상을 방지하기 위해 빈 디렉터리에만 복원할 수 있습니다."
        )

    resolved_password = _get_backup_password(password)
    encrypted_bytes = archive_path.read_bytes()

    # 1. Decrypt
    decrypted_bytes = decrypt_payload(encrypted_bytes, resolved_password)

    # 2. Unzip into target_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_zip = Path(tempfile.mktemp(prefix="jarvis_restore_zip_"))
    try:
        temp_zip.write_bytes(decrypted_bytes)
        with zipfile.ZipFile(temp_zip, "r") as archive:
            archive.extractall(target_dir)
    finally:
        temp_zip.unlink(missing_ok=True)

    # 3. Verify manifest
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("복원된 파일에 manifest.json이 없습니다.")
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: dict[str, dict[str, Any]] = manifest_data.get("files", {})

    for rel_path, meta in files.items():
        restored_file = target_dir / rel_path
        if not restored_file.exists():
            raise ValueError(f"복원 실패: 파일이 누락되었습니다 -> {rel_path}")
        if restored_file.stat().st_size != meta["size"]:
            raise ValueError(f"복원 실패: 파일 크기 불일치 -> {rel_path}")
        if _sha256_file(restored_file) != meta["sha256"]:
            raise ValueError(f"복원 실패: SHA-256 해시 불일치 -> {rel_path}")

    # 4. SQLite Integrity Check
    restored_db = target_dir / "memory" / "jarvis.sqlite3"
    if restored_db.exists():
        with sqlite3.connect(restored_db) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            row = cursor.fetchone()
            if not row or row[0] != "ok":
                raise ValueError(f"SQLite integrity check 실패: {row}")

    # 5. Raw JSONL validation
    raw_dir = target_dir / "memory" / "raw"
    if raw_dir.exists():
        for jsonl in raw_dir.glob("*.jsonl"):
            for line_no, line in enumerate(jsonl.read_text(encoding="utf-8").splitlines(), start=1):
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as err:
                        raise ValueError(f"Raw 로그 JSON 파싱 실패 ({jsonl.name}:{line_no}): {err}") from err

    # 6. Memory retrieval test in restored environment
    if verify_retrieval and restored_db.exists():
        with sqlite3.connect(restored_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM records WHERE status='confirmed'")
            count = cursor.fetchone()[0]
            print(f"[OK] 복원된 기억 레코드 확인: {count}건")

    print(f"[OK] 백업 복원 및 무결성 검증 성공: {target_dir}")
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis 백업 및 복원 도구")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_p = subparsers.add_parser("create", help="암호화 백업 생성")
    create_p.add_argument("--data-root", type=Path, default=Path(r"D:\Jarvis"), help="백업할 운영 데이터 루트")
    create_p.add_argument("--target", type=Path, default=Path(r"D:\JarvisBackups"), help="백업 저장 대상 디렉터리")
    create_p.add_argument("--password", type=str, default=None, help="백업 암호 (생략 시 Credential Manager 사용)")

    restore_p = subparsers.add_parser("restore", help="백업 복원 및 검증")
    restore_p.add_argument("--archive", type=Path, required=True, help="복원할 백업 아카이브 파일 경로")
    restore_p.add_argument("--target", type=Path, required=True, help="복원 대상 빈 디렉터리 경로")
    restore_p.add_argument("--password", type=str, default=None, help="백업 암호")
    restore_p.add_argument("--no-verify-retrieval", action="store_true", help="기억 검색 검증 건너뛰기")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "create":
        create_backup(data_root=args.data_root, target_dir=args.target, password=args.password)
        return 0
    if args.command == "restore":
        restore_backup(
            archive_path=args.archive,
            target_dir=args.target,
            password=args.password,
            verify_retrieval=not args.no_verify_retrieval,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
