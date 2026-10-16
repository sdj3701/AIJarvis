"""Secure backup and restore tool for Jarvis operational data."""

# [파일 역할] DB·대화 원본·설정을 모아 .jbak 백업을 만들고 빈 폴더에 복원한다.
# 생성 흐름: main → create_backup → 임시 폴더에 복사 → 명세 작성 → ZIP → 암호화 → 저장.
# 복원 흐름: main → restore_backup → 태그 검증/복호화 → 압축 해제 → 파일·DB·로그 검사.
# 사용법만 보기: `python -m scripts.backup --help` (백업/복원 작업은 하지 않는다).
# 학습 포인트: str와 bytes, 슬라이스, 언패킹, SQLite, JSON, try/finally, 하위 명령.
#
# 아래 주석은 현재 구현을 설명한다. 자체 구성한 암호화나 테스트용 기본 암호를
# 일반적인 운영 보안 설계의 모범 코드로 받아들이지 말자. 학습용으로는 데이터가
# 어떻게 변환되고 검증되는지에 집중하면 된다. 이번 주석은 기존 동작을 바꾸지 않는다.
from __future__ import annotations

# argparse: CLI 입력 / hashlib: 해시·키 유도 / hmac: 키를 사용하는 인증 태그 계산.
# json: JSON 변환 / os: 무작위 bytes 생성 / shutil: 파일 복사·폴더 정리.
# sqlite3: 파일 기반 DB / struct: 정수와 바이너리 표현 변환 / sys: import 검색 경로.
# tempfile: 임시 경로 / zipfile: ZIP 압축·해제 / datetime, timezone: 시각 기록.
# Path: 파일 경로 객체 / Any: 타입 검사에서 어떤 타입이든 허용하는 힌트.
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

# __file__ 기준으로 프로젝트 루트를 찾는다. parents[0]은 scripts, [1]은 그 위 폴더다.
# 직접 파일 경로로 실행해도 app을 찾도록 모듈 검색 경로(sys.path) 앞에 루트를 추가한다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

# write_atomic: 최종 파일 저장을 맡는 프로젝트 함수.
# canonical_json: 같은 자료를 일정한 규칙의 JSON 바이트열로 직렬화하는 프로젝트 함수.
# noqa: E402는 위 경로 설정 뒤의 import를 코드 검사 도구가 허용하게 하는 주석이다.
from app.core.atomic import write_atomic  # noqa: E402
from app.core.canonical import canonical_json  # noqa: E402

# b 접두사는 문자열(str)이 아니라 바이트열(bytes)이다. 헤더는 파일 형식을 구분한다.
MAGIC_HEADER = b"JARVIS_BACKUP_V1"
# 숫자 중간의 _는 읽기 위한 구분자다. 100_000과 100000은 같은 정수다.
PBKDF2_ITERATIONS = 100_000
KEYRING_SERVICE = "jarvis"
KEYRING_USERNAME = "backup_key"
# 이 구현은 암호를 얻지 못하면 공개된 테스트용 기본값으로 되돌아간다.
# 이 값은 비밀이 아니므로 개인 운영 데이터를 보호할 암호로 간주할 수 없다.
DEFAULT_TEST_KEY = "jarvis-default-backup-key-v05"


def _derive_keys(password: str, salt: bytes) -> tuple[bytes, bytes]:
    """Derive 32-byte encryption key and 32-byte HMAC key using PBKDF2-HMAC-SHA256."""
    # password는 사람이 입력하는 문자열, salt는 백업마다 생성하는 무작위 바이트다.
    # PBKDF2는 암호에서 키를 만들며 반복 계산으로 암호 추측 한 번의 비용을 늘린다.
    # encode('utf-8')은 글자를 바이트로 바꾼다. dklen=64는 결과 길이가 64바이트라는 뜻.
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=64,
    )
    # 슬라이스 [시작:끝]에서 끝 인덱스는 포함하지 않는다.
    # [:32]는 앞 32바이트, [32:]는 그 뒤 32바이트다. 용도별 키를 나눠 사용한다.
    enc_key = key_material[:32]
    mac_key = key_material[32:]
    # 쉼표로 두 값을 반환하면 튜플이 된다. 호출부에서는 두 변수에 나눠 받을 수 있다.
    return enc_key, mac_key


def _keystream_sha256(key: bytes, nonce: bytes, length: int) -> bytes:
    """Deterministic stream cipher based on HMAC-SHA256 in counter mode."""
    # 이 함수는 키 + nonce + 증가하는 카운터를 이용해 필요한 길이의 바이트열을 만든다.
    # 같은 입력이면 같은 출력이 나온다. 암호화 때와 복호화 때 같은 수열을 재현한다.
    # 이는 이 프로젝트의 자체 구성이며, AES 같은 표준 암호 호출은 아니다.
    blocks: list[bytes] = []
    block_index = 0
    generated = 0
    while generated < length:
        # >는 빅 엔디언(큰 자리 바이트 먼저), Q는 부호 없는 8바이트 정수 형식이다.
        counter_bytes = struct.pack(">Q", block_index)
        # +는 bytes를 이어 붙인다. HMAC-SHA256의 digest는 32바이트다.
        block = hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest()
        blocks.append(block)
        # +=는 기존 값에 더해 다시 대입한다. 생성 길이와 카운터를 각각 증가시킨다.
        generated += len(block)
        block_index += 1
    # 블록을 연결한 뒤 요청한 길이까지만 자른다. 마지막 블록의 남는 부분을 버린다.
    return b"".join(blocks)[:length]


def encrypt_payload(plaintext: bytes, password: str) -> bytes:
    """Encrypt payload with PBKDF2-HMAC-SHA256, CTR keystream, and HMAC authentication tag."""
    # plaintext는 ZIP 파일 내용이다. os.urandom은 운영체제에서 무작위 바이트를 얻는다.
    # salt는 키 유도용, nonce는 키스트림 구분용이다. 둘은 암호문과 함께 저장한다.
    salt = os.urandom(16)
    nonce = os.urandom(16)
    enc_key, mac_key = _derive_keys(password, salt)
    keystream = _keystream_sha256(enc_key, nonce, len(plaintext))
    # bytes를 순회하면 각 항목은 0~255 정수다. zip은 두 바이트열을 한 쌍씩 묶는다.
    # ^는 거듭제곱(**)이 아니라 비트 XOR이다. (원문 ^ 키) ^ 키 = 원문이 된다.
    # strict=True는 두 입력 길이가 다르면 예외를 낸다. bytes(...)로 결과를 다시 묶는다.
    ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream, strict=True))
    # 인증 태그는 키를 이용해 데이터 변조 여부를 확인하는 값이며 복호화할 내용은 아니다.
    tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    # 파일 구조: [헤더][salt 16바이트][nonce 16바이트][태그 32바이트][암호문].
    # 복호화 함수는 바로 이 순서와 길이를 이용해 각 부분을 분리한다.
    return MAGIC_HEADER + salt + nonce + tag + ciphertext


def decrypt_payload(encrypted: bytes, password: str) -> bytes:
    """Verify HMAC authentication tag and decrypt payload."""
    # 먼저 이 도구가 만든 형식인지 확인한다. 헤더만 맞는다고 올바른 암호문인 것은 아니다.
    header_len = len(MAGIC_HEADER)
    if not encrypted.startswith(MAGIC_HEADER):
        raise ValueError("유효한 Jarvis 백업 아카이브 헤더가 아닙니다.")
    # offset은 현재 읽을 위치를 뜻한다. 고정 길이 항목을 읽을 때마다 그만큼 이동한다.
    offset = header_len
    salt = encrypted[offset : offset + 16]
    offset += 16
    nonce = encrypted[offset : offset + 16]
    offset += 16
    expected_tag = encrypted[offset : offset + 32]
    offset += 32
    # 나머지 전체가 암호문이다. 문자열과 마찬가지로 bytes에도 슬라이싱을 쓸 수 있다.
    ciphertext = encrypted[offset:]

    enc_key, mac_key = _derive_keys(password, salt)
    actual_tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    # compare_digest는 태그 비교에 맞는 함수다. 일반 == 비교의 타이밍 누출을 줄인다.
    # 태그가 맞지 않으면 암호가 틀렸거나 파일이 바뀐 것이므로 복호화 전에 중단한다.
    if not hmac.compare_digest(expected_tag, actual_tag):
        raise ValueError("백업 아카이브 암호화 태그 검증 실패: 암호가 틀렸거나 데이터가 변조되었습니다.")

    keystream = _keystream_sha256(enc_key, nonce, len(ciphertext))
    # 암호화 때와 같은 키스트림으로 XOR하면 원래 ZIP 바이트열을 되찾는다.
    return bytes(c ^ k for c, k in zip(ciphertext, keystream, strict=True))


def _get_backup_password(explicit: str | None) -> str:
    # 우선순위: 직접 받은 비어 있지 않은 암호 → keyring 저장값 → 테스트 기본값.
    # if explicit은 None뿐 아니라 빈 문자열 ''도 False로 취급한다.
    if explicit:
        return explicit
    # 필요해진 시점에 import한다. 이 import는 아래 try 밖이므로 패키지가 아예 없으면
    # ImportError가 그대로 전파된다. 아래 except가 모든 상황을 처리하는 것은 아니다.
    import keyring

    try:
        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if stored:
            return stored
    except Exception:
        # pass는 아무것도 하지 않는 문장이다. 조회 실패를 무시하고 기본값으로 진행한다.
        pass
    return DEFAULT_TEST_KEY


def _sha256_file(path: Path) -> str:
    # 해시는 파일을 복원하는 정보가 아니라 내용이 동일한지 비교하는 요약값이다.
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        # with가 파일을 닫는다. :=는 읽은 조각을 저장하며, 빈 bytes를 만나면 종료한다.
        # 65536바이트씩 처리해 큰 파일을 한 번에 메모리에 올리지 않는다.
        while chunk := stream.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


# Path 입력은 원본 데이터 루트와 백업 저장 폴더다. 반환값은 완성된 백업 파일의 Path다.
# password: str | None = None은 암호를 생략하면 None을 전달한다는 뜻이다.
def create_backup(
    data_root: Path,
    target_dir: Path,
    password: str | None = None,
) -> Path:
    """Create an encrypted backup of data_root to target_dir using atomic steps."""
    # parents=True는 상위 폴더도 생성, exist_ok=True는 기존 폴더 허용이다.
    target_dir.mkdir(parents=True, exist_ok=True)
    resolved_password = _get_backup_password(password)

    # 원본을 직접 압축하기 전에 임시 작업 폴더(staging)에 필요한 파일들을 모은다.
    # mkdtemp는 폴더를 실제 생성하며, 이 함수에서는 아래 finally에서 정리한다.
    staging_dir = Path(tempfile.mkdtemp(prefix="jarvis_backup_staging_"))
    try:
        # {상대 경로: {'size': 크기, 'sha256': 해시}} 구조의 중첩 dict다.
        manifest_files: dict[str, dict[str, Any]] = {}

        # 1. SQLite Online Backup
        # 사용 중인 DB 파일을 단순 복사하는 대신 SQLite의 백업 API로 DB 사본을 만든다.
        db_path = data_root / "memory" / "jarvis.sqlite3"
        if db_path.exists():
            staging_db_dir = staging_dir / "memory"
            staging_db_dir.mkdir(parents=True, exist_ok=True)
            staging_db = staging_db_dir / "jarvis.sqlite3"
            with sqlite3.connect(db_path) as src_conn, sqlite3.connect(staging_db) as dst_conn:
                # sqlite3 연결의 with는 트랜잭션 완료/롤백을 관리한다.
                # 일반 파일의 with와 달리, 이것만으로 연결을 명시적으로 close하지는 않는다.
                src_conn.backup(dst_conn)
            manifest_files["memory/jarvis.sqlite3"] = {
                "size": staging_db.stat().st_size,
                "sha256": _sha256_file(staging_db),
            }

        # 2. Copy raw logs
        # JSONL은 한 줄마다 JSON 객체 등을 하나씩 저장하는 형식이다.
        # glob('*.jsonl')은 이 폴더 바로 아래의 해당 확장자 파일을 찾는다.
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
        # .yaml 설정 파일만 복사한다. data_root의 모든 파일을 통째로 백업하는 것은 아니다.
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
        # manifest는 복원 시 파일명·크기·내용을 확인하기 위한 백업 명세서다.
        # UTC 시각을 ISO 문자열로 기록하고 Path는 JSON에 넣기 위해 str로 바꾼다.
        manifest_data = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_data_root": str(data_root),
            "files": manifest_files,
        }
        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_bytes(canonical_json(manifest_data) + b"\n")

        # 5. Build ZIP payload in-memory or tempfile
        # mktemp는 이름만 돌려주며 파일을 확보하지 않는다. 이 코드는 그 경로를 ZIP으로
        # 나중에 연다. 새 코드를 작성할 때는 파일을 함께 생성하는 임시 파일 API를 고려한다.
        zip_temp = Path(tempfile.mktemp(prefix="jarvis_zip_"))
        with zipfile.ZipFile(zip_temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            # rglob은 하위 폴더까지 재귀적으로 탐색한다. 파일만 ZIP에 추가한다.
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file():
                    # 임시 폴더의 절대 경로 대신 상대 경로를 저장해 다른 폴더에 복원할 수 있다.
                    # as_posix는 경로 구분자를 /로 통일한다.
                    rel_path = file_path.relative_to(staging_dir).as_posix()
                    archive.write(file_path, arcname=rel_path)

        # 이 단계는 ZIP 전체를 메모리에 읽는다. 위의 분할 해시 읽기와는 방식이 다르다.
        zip_bytes = zip_temp.read_bytes()
        zip_temp.unlink(missing_ok=True)

        # 6. Encrypt payload
        # 압축된 내용 전체를 암호화 함수에 넘긴다. 결과에는 헤더와 인증 태그도 들어 있다.
        encrypted_bytes = encrypt_payload(zip_bytes, resolved_password)

        # 7. Write to target archive
        # strftime 서식: 연월일_시분초. 여기서는 시간대를 지정하지 않은 시스템 로컬 시각이다.
        # 파일명이 초 단위라 같은 초에 생성한 백업은 같은 대상 경로를 사용할 수 있다.
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"backup-{timestamp_str}.jbak"
        final_archive_path = target_dir / archive_name
        write_atomic(final_archive_path, encrypted_bytes)

        # 8. Verify hash of written target
        # 메모리의 암호문 해시와 실제 저장 파일의 해시가 같은지 확인한다.
        # 이것은 저장 확인이며, 복원 함수까지 실제 실행하는 복원 테스트는 아니다.
        final_sha256 = _sha256_file(final_archive_path)
        expected_sha256 = hashlib.sha256(encrypted_bytes).hexdigest()
        if final_sha256 != expected_sha256:
            raise IOError("대상 위치의 백업 아카이브 해시 검증 실패")

        print(f"[OK] 암호화 백업 완료: {final_archive_path} (크기: {len(encrypted_bytes)} bytes)")
        return final_archive_path
    finally:
        # 9. Clean up staging folder completely
        # finally는 return이나 예외가 있어도 실행된다. 작업용 사본을 정리하기 위한 구문이다.
        # ignore_errors=True이므로 삭제에 실패해도 예외를 다시 내지는 않는다.
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def restore_backup(
    archive_path: Path,
    target_dir: Path,
    password: str | None = None,
    verify_retrieval: bool = True,
) -> bool:
    """Restore an encrypted backup into an empty target_dir and verify integrity."""
    # and는 왼쪽이 False이면 오른쪽을 평가하지 않는다(단락 평가).
    # 폴더가 없을 때 iterdir()를 호출하지 않도록 하고, 있으면 any로 내용 유무를 확인한다.
    if target_dir.exists() and any(target_dir.iterdir()):
        raise ValueError(
            f"복원 대상 디렉터리가 비어 있지 않습니다: {target_dir}. "
            "운영 데이터 손상을 방지하기 위해 빈 디렉터리에만 복원할 수 있습니다."
        )

    resolved_password = _get_backup_password(password)
    encrypted_bytes = archive_path.read_bytes()

    # 1. Decrypt
    # 태그 검증에 통과한 경우에만 복호화된 ZIP을 얻는다.
    decrypted_bytes = decrypt_payload(encrypted_bytes, resolved_password)

    # 2. Unzip into target_dir
    # 이 구현은 ZIP을 임시 파일에 쓴 다음 extractall로 푼다.
    # setup_voice.py의 _safe_extract처럼 모든 항목의 경로를 별도 검사하는 코드는 없다.
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_zip = Path(tempfile.mktemp(prefix="jarvis_restore_zip_"))
    try:
        temp_zip.write_bytes(decrypted_bytes)
        with zipfile.ZipFile(temp_zip, "r") as archive:
            archive.extractall(target_dir)
    finally:
        # 임시 ZIP을 정리한다. 뒤의 검증이 실패해도 이미 복원한 파일을 되돌리는 코드는 없다.
        temp_zip.unlink(missing_ok=True)

    # 3. Verify manifest
    # read_text → 문자열, json.loads → dict로 변환해 생성 때 기록한 값과 대조한다.
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("복원된 파일에 manifest.json이 없습니다.")
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: dict[str, dict[str, Any]] = manifest_data.get("files", {})

    # items()는 (키, 값) 쌍을 만든다. 경로와 메타데이터를 두 변수에 나눠 받는다.
    # 이 반복문은 manifest에 나열된 파일을 검사하며, 나열되지 않은 추가 파일은 검사하지 않는다.
    for rel_path, meta in files.items():
        restored_file = target_dir / rel_path
        if not restored_file.exists():
            raise ValueError(f"복원 실패: 파일이 누락되었습니다 -> {rel_path}")
        if restored_file.stat().st_size != meta["size"]:
            raise ValueError(f"복원 실패: 파일 크기 불일치 -> {rel_path}")
        if _sha256_file(restored_file) != meta["sha256"]:
            raise ValueError(f"복원 실패: SHA-256 해시 불일치 -> {rel_path}")

    # 4. SQLite Integrity Check
    # DB 파일 내부 구조가 일관적인지 SQLite 자체 검사 명령을 실행한다.
    # cursor는 SQL 실행/결과 읽기 객체다. fetchone은 한 행을 튜플 등으로 받거나 None을 준다.
    restored_db = target_dir / "memory" / "jarvis.sqlite3"
    if restored_db.exists():
        with sqlite3.connect(restored_db) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            row = cursor.fetchone()
            # 결과 행이 없으면 row[0]을 읽지 않는다. 있으면 첫 열의 값이 'ok'인지 본다.
            if not row or row[0] != "ok":
                raise ValueError(f"SQLite integrity check 실패: {row}")

    # 5. Raw JSONL validation
    # enumerate(..., start=1)는 각 줄에 1부터 번호를 붙여 오류 위치를 표시하게 한다.
    raw_dir = target_dir / "memory" / "raw"
    if raw_dir.exists():
        for jsonl in raw_dir.glob("*.jsonl"):
            for line_no, line in enumerate(jsonl.read_text(encoding="utf-8").splitlines(), start=1):
                if line.strip():
                    # 공백뿐인 줄은 건너뛰고 내용이 있는 줄만 올바른 JSON인지 확인한다.
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as err:
                        # from err로 원래 파싱 오류를 새 ValueError의 원인으로 연결한다.
                        raise ValueError(f"Raw 로그 JSON 파싱 실패 ({jsonl.name}:{line_no}): {err}") from err

    # 6. Memory retrieval test in restored environment
    # 현재 구현에서 이 확인은 confirmed 레코드 수를 SQL로 조회하는 것이다.
    # 자연어 검색이나 검색 품질 평가를 실행하는 것은 아니다.
    if verify_retrieval and restored_db.exists():
        with sqlite3.connect(restored_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM records WHERE status='confirmed'")
            # COUNT(*)의 결과 한 행에서 첫 번째 열을 꺼낸다. 레코드가 없으면 값은 0이다.
            count = cursor.fetchone()[0]
            print(f"[OK] 복원된 기억 레코드 확인: {count}건")

    print(f"[OK] 백업 복원 및 무결성 검증 성공: {target_dir}")
    return True


def _parser() -> argparse.ArgumentParser:
    # 하위 명령(subcommand)으로 서로 다른 동작과 각자의 옵션을 구분한다.
    # 예: backup create ... / backup restore ... . 여기서는 둘 중 하나가 필수다.
    parser = argparse.ArgumentParser(description="Jarvis 백업 및 복원 도구")
    # dest='command'는 선택한 명령 이름을 args.command에 저장하라는 뜻이다.
    subparsers = parser.add_subparsers(dest="command", required=True)

    # type=Path는 입력 문자열을 Path로 바꾼다. r'...'는 역슬래시를 그대로 쓰는 문자열이다.
    # 아래 기본값은 운영 데이터 경로를 가리키므로 학습 실행 시에는 입력 경로를 확인하자.
    create_p = subparsers.add_parser("create", help="암호화 백업 생성")
    create_p.add_argument("--data-root", type=Path, default=Path(r"D:\Jarvis"), help="백업할 운영 데이터 루트")
    create_p.add_argument("--target", type=Path, default=Path(r"D:\JarvisBackups"), help="백업 저장 대상 디렉터리")
    create_p.add_argument("--password", type=str, default=None, help="백업 암호 (생략 시 Credential Manager 사용)")

    # 복원은 아카이브와 빈 대상 폴더를 required=True로 반드시 입력받는다.
    restore_p = subparsers.add_parser("restore", help="백업 복원 및 검증")
    restore_p.add_argument("--archive", type=Path, required=True, help="복원할 백업 아카이브 파일 경로")
    restore_p.add_argument("--target", type=Path, required=True, help="복원 대상 빈 디렉터리 경로")
    restore_p.add_argument("--password", type=str, default=None, help="백업 암호")
    restore_p.add_argument("--no-verify-retrieval", action="store_true", help="기억 검색 검증 건너뛰기")

    return parser


def main(argv: list[str] | None = None) -> int:
    # None이면 터미널 인수를 사용한다. 테스트에서는 ['create', ...] 같은 목록도 전달 가능.
    args = _parser().parse_args(argv)
    if args.command == "create":
        # 키워드 인수는 어떤 입력을 넘기는지 이름으로 명시한다. 성공 시 종료 코드 0 반환.
        create_backup(data_root=args.data_root, target_dir=args.target, password=args.password)
        return 0
    if args.command == "restore":
        restore_backup(
            archive_path=args.archive,
            target_dir=args.target,
            password=args.password,
            # CLI는 '검증 생략 여부', 함수는 '검증할지 여부'이므로 not으로 의미를 뒤집는다.
            verify_retrieval=not args.no_verify_retrieval,
        )
        return 0
    return 1


# import할 때는 백업/복원을 실행하지 않는다. 직접 실행할 때만 main으로 진입한다.
# main에서 처리하지 않은 오류는 호출 스택과 함께 실패로 전파된다.
if __name__ == "__main__":
    raise SystemExit(main())
