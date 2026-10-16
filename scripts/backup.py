# 파이썬 공부 | scripts/backup.py
# 운영 데이터를 백업하고 백업 파일에서 복원합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

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

# 오른쪽 식을 계산한 값을 REPOSITORY_ROOT에 대입합니다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: str(REPOSITORY_ROOT) not in sys.path.
if str(REPOSITORY_ROOT) not in sys.path:
    # sys.path.insert()을 호출해 작업을 수행합니다.
    sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from app.config.defaults import DEFAULT_DATA_ROOT  # noqa: E402
from app.core.atomic import write_atomic  # noqa: E402
from app.core.canonical import canonical_json  # noqa: E402

# MAGIC_HEADER에 숫자 등 고정된 값을 대입합니다.
MAGIC_HEADER = b"JARVIS_BACKUP_V1"
# PBKDF2_ITERATIONS에 숫자 등 고정된 값을 대입합니다.
PBKDF2_ITERATIONS = 100_000
# KEYRING_SERVICE에 문자열을 대입합니다.
KEYRING_SERVICE = "jarvis"
# KEYRING_USERNAME에 문자열을 대입합니다.
KEYRING_USERNAME = "backup_key"
# DEFAULT_TEST_KEY에 문자열을 대입합니다.
DEFAULT_TEST_KEY = "jarvis-default-backup-key-v05"


# _derive_keys(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: password, salt.
# 반환 타입 힌트: tuple[bytes, bytes].
def _derive_keys(password: str, salt: bytes) -> tuple[bytes, bytes]:
    """Derive 32-byte encryption key and 32-byte HMAC key using PBKDF2-HMAC-SHA256."""
    # hashlib.pbkdf2_hmac()의 반환값을 key_material에 대입합니다.
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=64,
    )
    # 오른쪽 식을 계산한 값을 enc_key에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    enc_key = key_material[:32]
    # 오른쪽 식을 계산한 값을 mac_key에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    mac_key = key_material[32:]
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return enc_key, mac_key


# _keystream_sha256(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: key, nonce, length.
# 반환 타입 힌트: 바이트 데이터(bytes).
def _keystream_sha256(key: bytes, nonce: bytes, length: int) -> bytes:
    """Deterministic stream cipher based on HMAC-SHA256 in counter mode."""
    # blocks에 리스트(순서가 있고 수정 가능)을 대입합니다.
    blocks: list[bytes] = []
    # block_index에 숫자 등 고정된 값을 대입합니다.
    block_index = 0
    # generated에 숫자 등 고정된 값을 대입합니다.
    generated = 0
    # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
    while generated < length:
        # struct.pack()의 반환값을 counter_bytes에 대입합니다.
        counter_bytes = struct.pack(">Q", block_index)
        # 아래 함수()의 반환값을 block에 대입합니다.
        block = hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest()
        # 리스트 끝에 항목 하나를 추가합니다.
        blocks.append(block)
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        generated += len(block)
        # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
        block_index += 1
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    return b"".join(blocks)[:length]


# encrypt_payload(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: plaintext, password.
# 반환 타입 힌트: 바이트 데이터(bytes).
def encrypt_payload(plaintext: bytes, password: str) -> bytes:
    """Encrypt payload with PBKDF2-HMAC-SHA256, CTR keystream, and HMAC authentication tag."""
    # os.urandom()의 반환값을 salt에 대입합니다.
    salt = os.urandom(16)
    # os.urandom()의 반환값을 nonce에 대입합니다.
    nonce = os.urandom(16)
    # 언패킹: 오른쪽 결과를 순서대로 (enc_key, mac_key)에 나누어 담습니다.
    enc_key, mac_key = _derive_keys(password, salt)
    # _keystream_sha256()의 반환값을 keystream에 대입합니다.
    keystream = _keystream_sha256(enc_key, nonce, len(plaintext))
    # bytes()의 반환값을 ciphertext에 대입합니다.
    ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream, strict=True))
    # 아래 함수()의 반환값을 tag에 대입합니다.
    tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return MAGIC_HEADER + salt + nonce + tag + ciphertext


# decrypt_payload(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: encrypted, password.
# 반환 타입 힌트: 바이트 데이터(bytes).
def decrypt_payload(encrypted: bytes, password: str) -> bytes:
    """Verify HMAC authentication tag and decrypt payload."""
    # len()의 반환값을 header_len에 대입합니다.
    header_len = len(MAGIC_HEADER)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not encrypted.startswith(MAGIC_HEADER).
    if not encrypted.startswith(MAGIC_HEADER):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("유효한 Jarvis 백업 아카이브 헤더가 아닙니다.")
    # 오른쪽 식을 계산한 값을 offset에 대입합니다.
    offset = header_len
    # 오른쪽 식을 계산한 값을 salt에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    salt = encrypted[offset : offset + 16]
    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
    offset += 16
    # 오른쪽 식을 계산한 값을 nonce에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    nonce = encrypted[offset : offset + 16]
    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
    offset += 16
    # 오른쪽 식을 계산한 값을 expected_tag에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    expected_tag = encrypted[offset : offset + 32]
    # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
    offset += 32
    # 오른쪽 식을 계산한 값을 ciphertext에 대입합니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    ciphertext = encrypted[offset:]

    # 언패킹: 오른쪽 결과를 순서대로 (enc_key, mac_key)에 나누어 담습니다.
    enc_key, mac_key = _derive_keys(password, salt)
    # 아래 함수()의 반환값을 actual_tag에 대입합니다.
    actual_tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not hmac.compare_digest(expected_tag,
    # actual_tag).
    if not hmac.compare_digest(expected_tag, actual_tag):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("백업 아카이브 암호화 태그 검증 실패: 암호가 틀렸거나 데이터가 변조되었습니다.")

    # _keystream_sha256()의 반환값을 keystream에 대입합니다.
    keystream = _keystream_sha256(enc_key, nonce, len(ciphertext))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return bytes(c ^ k for c, k in zip(ciphertext, keystream, strict=True))


# _get_backup_password(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: explicit.
# 반환 타입 힌트: 문자열(str).
def _get_backup_password(explicit: str | None) -> str:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: explicit.
    if explicit:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return explicit
    import keyring

    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # keyring.get_password()의 반환값을 stored에 대입합니다.
        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: stored.
        if stored:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return stored
    # Exception를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except Exception:
        # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
        pass
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return DEFAULT_TEST_KEY


# _sha256_file(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 문자열(str).
def _sha256_file(path: Path) -> str:
    # hashlib.sha256()의 반환값을 hasher에 대입합니다.
    hasher = hashlib.sha256()
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with path.open("rb") as stream:
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while chunk := stream.read(65536):
            # hasher.update()을 호출해 작업을 수행합니다.
            hasher.update(chunk)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return hasher.hexdigest()


# create_backup(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: data_root, target_dir, password.
# 반환 타입 힌트: Path.
def create_backup(
    data_root: Path,
    target_dir: Path,
    password: str | None = None,
) -> Path:
    """Create an encrypted backup of data_root to target_dir using atomic steps."""
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    target_dir.mkdir(parents=True, exist_ok=True)
    # _get_backup_password()의 반환값을 resolved_password에 대입합니다.
    resolved_password = _get_backup_password(password)

    # Path()의 반환값을 staging_dir에 대입합니다.
    staging_dir = Path(tempfile.mkdtemp(prefix="jarvis_backup_staging_"))
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # manifest_files에 딕셔너리(키와 값의 쌍)을 대입합니다.
        manifest_files: dict[str, dict[str, Any]] = {}

        # Snapshot both the primary DB and the local vector/conversation DB.
        for filename in ("jarvis.sqlite3", "semantic.sqlite3"):
            db_path = data_root / "memory" / filename
            if not db_path.exists():
                continue
            staging_db_dir = staging_dir / "memory"
            staging_db_dir.mkdir(parents=True, exist_ok=True)
            staging_db = staging_db_dir / filename
            with sqlite3.connect(db_path) as src_conn, sqlite3.connect(staging_db) as dst_conn:
                src_conn.backup(dst_conn)
            manifest_files[f"memory/{filename}"] = {
                "size": staging_db.stat().st_size,
                "sha256": _sha256_file(staging_db),
            }

        # 2. Copy raw logs
        # 오른쪽 식을 계산한 값을 raw_dir에 대입합니다.
        raw_dir = data_root / "memory" / "raw"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: raw_dir.exists().
        if raw_dir.exists():
            # 오른쪽 식을 계산한 값을 staging_raw에 대입합니다.
            staging_raw = staging_dir / "memory" / "raw"
            # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
            staging_raw.mkdir(parents=True, exist_ok=True)
            # for 반복문: 대상의 항목을 하나씩 raw_file에 대입하며 아래 블록을 실행합니다.
            for raw_file in raw_dir.glob("*.jsonl"):
                # 오른쪽 식을 계산한 값을 dst_file에 대입합니다.
                dst_file = staging_raw / raw_file.name
                # shutil.copyfile()을 호출해 작업을 수행합니다.
                shutil.copyfile(raw_file, dst_file)
                # manifest_files[f'memory/raw/{raw_file.name}']에 딕셔너리(키와 값의 쌍)을
                # 대입합니다.
                manifest_files[f"memory/raw/{raw_file.name}"] = {
                    "size": dst_file.stat().st_size,
                    "sha256": _sha256_file(dst_file),
                }

        # 3. Copy config
        # 오른쪽 식을 계산한 값을 config_dir에 대입합니다.
        config_dir = data_root / "config"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: config_dir.exists().
        if config_dir.exists():
            # 오른쪽 식을 계산한 값을 staging_config에 대입합니다.
            staging_config = staging_dir / "config"
            # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
            staging_config.mkdir(parents=True, exist_ok=True)
            # for 반복문: 대상의 항목을 하나씩 cfg_file에 대입하며 아래 블록을 실행합니다.
            for cfg_file in config_dir.glob("*.yaml"):
                # 오른쪽 식을 계산한 값을 dst_file에 대입합니다.
                dst_file = staging_config / cfg_file.name
                # shutil.copyfile()을 호출해 작업을 수행합니다.
                shutil.copyfile(cfg_file, dst_file)
                # manifest_files[f'config/{cfg_file.name}']에 딕셔너리(키와 값의 쌍)을 대입합니다.
                manifest_files[f"config/{cfg_file.name}"] = {
                    "size": dst_file.stat().st_size,
                    "sha256": _sha256_file(dst_file),
                }

        # 4. Write manifest
        # manifest_data에 딕셔너리(키와 값의 쌍)을 대입합니다.
        manifest_data = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_data_root": str(data_root),
            "files": manifest_files,
        }
        # 오른쪽 식을 계산한 값을 manifest_path에 대입합니다.
        manifest_path = staging_dir / "manifest.json"
        # 바이트 데이터를 파일에 기록합니다.
        manifest_path.write_bytes(canonical_json(manifest_data) + b"\n")

        # 5. Build ZIP payload in-memory or tempfile
        # Path()의 반환값을 zip_temp에 대입합니다.
        zip_temp = Path(tempfile.mktemp(prefix="jarvis_zip_"))
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with zipfile.ZipFile(zip_temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            # for 반복문: 대상의 항목을 하나씩 file_path에 대입하며 아래 블록을 실행합니다.
            for file_path in staging_dir.rglob("*"):
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: file_path.is_file().
                if file_path.is_file():
                    # file_path.relative_to(staging_dir).as_posix()의 반환값을 rel_path에
                    # 대입합니다.
                    rel_path = file_path.relative_to(staging_dir).as_posix()
                    # 열린 출력 대상에 데이터를 기록합니다.
                    archive.write(file_path, arcname=rel_path)

        # zip_temp.read_bytes()의 반환값을 zip_bytes에 대입합니다.
        zip_bytes = zip_temp.read_bytes()
        # 지정한 파일 또는 링크를 삭제합니다.
        zip_temp.unlink(missing_ok=True)

        # 6. Encrypt payload
        # encrypt_payload()의 반환값을 encrypted_bytes에 대입합니다.
        encrypted_bytes = encrypt_payload(zip_bytes, resolved_password)

        # 7. Write to target archive
        # datetime.now().strftime()의 반환값을 timestamp_str에 대입합니다.
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 오른쪽 식을 계산한 값을 archive_name에 대입합니다.
        # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
        archive_name = f"backup-{timestamp_str}.jbak"
        # 오른쪽 식을 계산한 값을 final_archive_path에 대입합니다.
        final_archive_path = target_dir / archive_name
        # write_atomic()을 호출해 작업을 수행합니다.
        write_atomic(final_archive_path, encrypted_bytes)

        # 8. Verify hash of written target
        # _sha256_file()의 반환값을 final_sha256에 대입합니다.
        final_sha256 = _sha256_file(final_archive_path)
        # hashlib.sha256(encrypted_bytes).hexdigest()의 반환값을 expected_sha256에 대입합니다.
        expected_sha256 = hashlib.sha256(encrypted_bytes).hexdigest()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: final_sha256 != expected_sha256.
        if final_sha256 != expected_sha256:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise IOError("대상 위치의 백업 아카이브 해시 검증 실패")

        # 값을 텍스트로 출력합니다.
        print(f"[OK] 암호화 백업 완료: {final_archive_path} (크기: {len(encrypted_bytes)} bytes)")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return final_archive_path
    # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
    finally:
        # 9. Clean up staging folder completely
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: staging_dir.exists().
        if staging_dir.exists():
            # shutil.rmtree()을 호출해 작업을 수행합니다.
            shutil.rmtree(staging_dir, ignore_errors=True)


# restore_backup(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: archive_path, target_dir, password, verify_retrieval.
# 반환 타입 힌트: 참/거짓(bool).
def restore_backup(
    archive_path: Path,
    target_dir: Path,
    password: str | None = None,
    verify_retrieval: bool = True,
) -> bool:
    """Restore an encrypted backup into an empty target_dir and verify integrity."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: target_dir.exists() and
    # any(target_dir.iterdir()).
    if target_dir.exists() and any(target_dir.iterdir()):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError(
            f"복원 대상 디렉터리가 비어 있지 않습니다: {target_dir}. "
            "운영 데이터 손상을 방지하기 위해 빈 디렉터리에만 복원할 수 있습니다."
        )

    # _get_backup_password()의 반환값을 resolved_password에 대입합니다.
    resolved_password = _get_backup_password(password)
    # archive_path.read_bytes()의 반환값을 encrypted_bytes에 대입합니다.
    encrypted_bytes = archive_path.read_bytes()

    # 1. Decrypt
    # decrypt_payload()의 반환값을 decrypted_bytes에 대입합니다.
    decrypted_bytes = decrypt_payload(encrypted_bytes, resolved_password)

    # 2. Unzip into target_dir
    # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
    target_dir.mkdir(parents=True, exist_ok=True)
    # Path()의 반환값을 temp_zip에 대입합니다.
    temp_zip = Path(tempfile.mktemp(prefix="jarvis_restore_zip_"))
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 바이트 데이터를 파일에 기록합니다.
        temp_zip.write_bytes(decrypted_bytes)
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with zipfile.ZipFile(temp_zip, "r") as archive:
            # archive.extractall()을 호출해 작업을 수행합니다.
            archive.extractall(target_dir)
    # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
    finally:
        # 지정한 파일 또는 링크를 삭제합니다.
        temp_zip.unlink(missing_ok=True)

    # 3. Verify manifest
    # 오른쪽 식을 계산한 값을 manifest_path에 대입합니다.
    manifest_path = target_dir / "manifest.json"
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not manifest_path.exists().
    if not manifest_path.exists():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("복원된 파일에 manifest.json이 없습니다.")
    # json.loads()의 반환값을 manifest_data에 대입합니다.
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    # manifest_data.get()의 반환값을 files에 대입합니다.
    files: dict[str, dict[str, Any]] = manifest_data.get("files", {})

    # for 반복문: 대상의 항목을 하나씩 (rel_path, meta)에 대입하며 아래 블록을 실행합니다.
    for rel_path, meta in files.items():
        # 오른쪽 식을 계산한 값을 restored_file에 대입합니다.
        restored_file = target_dir / rel_path
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not restored_file.exists().
        if not restored_file.exists():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"복원 실패: 파일이 누락되었습니다 -> {rel_path}")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: restored_file.stat().st_size !=
        # meta['size'].
        if restored_file.stat().st_size != meta["size"]:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"복원 실패: 파일 크기 불일치 -> {rel_path}")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: _sha256_file(restored_file) !=
        # meta['sha256'].
        if _sha256_file(restored_file) != meta["sha256"]:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError(f"복원 실패: SHA-256 해시 불일치 -> {rel_path}")

    # 4. SQLite Integrity Check
    # 오른쪽 식을 계산한 값을 restored_db에 대입합니다.
    restored_db = target_dir / "memory" / "jarvis.sqlite3"
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: restored_db.exists().
    if restored_db.exists():
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with sqlite3.connect(restored_db) as conn:
            # conn.cursor()의 반환값을 cursor에 대입합니다.
            cursor = conn.cursor()
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            cursor.execute("PRAGMA integrity_check;")
            # cursor.fetchone()의 반환값을 row에 대입합니다.
            row = cursor.fetchone()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not row or row[0] != 'ok'.
            if not row or row[0] != "ok":
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise ValueError(f"SQLite integrity check 실패: {row}")

    # 5. Raw JSONL validation
    # 오른쪽 식을 계산한 값을 raw_dir에 대입합니다.
    raw_dir = target_dir / "memory" / "raw"
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: raw_dir.exists().
    if raw_dir.exists():
        # for 반복문: 대상의 항목을 하나씩 jsonl에 대입하며 아래 블록을 실행합니다.
        for jsonl in raw_dir.glob("*.jsonl"):
            # for 반복문: 대상의 항목을 하나씩 (line_no, line)에 대입하며 아래 블록을 실행합니다.
            for line_no, line in enumerate(jsonl.read_text(encoding="utf-8").splitlines(), start=1):
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: line.strip().
                if line.strip():
                    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                    # 처리합니다.
                    try:
                        # json.loads()을 호출해 작업을 수행합니다.
                        json.loads(line)
                    # json.JSONDecodeError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가
                    # 담깁니다.
                    except json.JSONDecodeError as err:
                        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                        # 이동합니다.
                        raise ValueError(f"Raw 로그 JSON 파싱 실패 ({jsonl.name}:{line_no}): {err}") from err

    # 6. Memory retrieval test in restored environment
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: verify_retrieval and restored_db.exists().
    if verify_retrieval and restored_db.exists():
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with sqlite3.connect(restored_db) as conn:
            # conn.cursor()의 반환값을 cursor에 대입합니다.
            cursor = conn.cursor()
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            cursor.execute("SELECT COUNT(*) FROM records WHERE status='confirmed'")
            # 오른쪽 식을 계산한 값을 count에 대입합니다.
            count = cursor.fetchone()[0]
            # 값을 텍스트로 출력합니다.
            print(f"[OK] 복원된 기억 레코드 확인: {count}건")

    # 값을 텍스트로 출력합니다.
    print(f"[OK] 백업 복원 및 무결성 검증 성공: {target_dir}")
    # True을 반환하고 이 함수의 실행을 끝냅니다.
    return True


# _parser(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 반환 타입 힌트: argparse.ArgumentParser.
def _parser() -> argparse.ArgumentParser:
    # argparse.ArgumentParser()의 반환값을 parser에 대입합니다.
    parser = argparse.ArgumentParser(description="Jarvis 백업 및 복원 도구")
    # parser.add_subparsers()의 반환값을 subparsers에 대입합니다.
    subparsers = parser.add_subparsers(dest="command", required=True)

    # subparsers.add_parser()의 반환값을 create_p에 대입합니다.
    create_p = subparsers.add_parser("create", help="암호화 백업 생성")
    # create_p.add_argument()을 호출해 작업을 수행합니다.
    create_p.add_argument(
        "--data-root", type=Path, default=DEFAULT_DATA_ROOT, help="백업할 운영 데이터 루트"
    )
    # create_p.add_argument()을 호출해 작업을 수행합니다.
    create_p.add_argument("--target", type=Path, default=Path(r"D:\JarvisBackups"), help="백업 저장 대상 디렉터리")
    # create_p.add_argument()을 호출해 작업을 수행합니다.
    create_p.add_argument("--password", type=str, default=None, help="백업 암호 (생략 시 Credential Manager 사용)")

    # subparsers.add_parser()의 반환값을 restore_p에 대입합니다.
    restore_p = subparsers.add_parser("restore", help="백업 복원 및 검증")
    # restore_p.add_argument()을 호출해 작업을 수행합니다.
    restore_p.add_argument("--archive", type=Path, required=True, help="복원할 백업 아카이브 파일 경로")
    # restore_p.add_argument()을 호출해 작업을 수행합니다.
    restore_p.add_argument("--target", type=Path, required=True, help="복원 대상 빈 디렉터리 경로")
    # restore_p.add_argument()을 호출해 작업을 수행합니다.
    restore_p.add_argument("--password", type=str, default=None, help="백업 암호")
    # restore_p.add_argument()을 호출해 작업을 수행합니다.
    restore_p.add_argument("--no-verify-retrieval", action="store_true", help="기억 검색 검증 건너뛰기")

    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return parser


# main(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: argv.
# 반환 타입 힌트: 정수(int).
def main(argv: list[str] | None = None) -> int:
    # _parser().parse_args()의 반환값을 args에 대입합니다.
    args = _parser().parse_args(argv)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.command == 'create'.
    if args.command == "create":
        # create_backup()을 호출해 작업을 수행합니다.
        create_backup(data_root=args.data_root, target_dir=args.target, password=args.password)
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: args.command == 'restore'.
    if args.command == "restore":
        # restore_backup()을 호출해 작업을 수행합니다.
        restore_backup(
            archive_path=args.archive,
            target_dir=args.target,
            password=args.password,
            verify_retrieval=not args.no_verify_retrieval,
        )
        # 0을 반환하고 이 함수의 실행을 끝냅니다.
        return 0
    # 1을 반환하고 이 함수의 실행을 끝냅니다.
    return 1


# 이 파일을 실행 진입점으로 사용할 때만 아래 코드를 실행합니다. import할 때는 실행하지 않습니다.
if __name__ == "__main__":
    # SystemExit 예외로 프로그램 종료를 요청합니다. 전달한 값은 종료 상태를 나타냅니다.
    raise SystemExit(main())
