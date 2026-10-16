# 파이썬 공부 | scripts/app/core/atomic.py
# 임시 파일에 먼저 기록한 뒤 교체하여 파일이 반만 저장되는 문제를 줄입니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Crash-safe replacement of complete files.

Partial-file quarantine on startup lives in ``app.core.recovery``.
"""

from __future__ import annotations

import os
from pathlib import Path


# 임시 파일 쓰기 → 버퍼 비우기 → 디스크 동기화 → 대상 파일 교체 순서입니다.
# 쓰기 도중 중단되어도 기존 파일을 바로 덮어쓰지 않도록 설계했습니다.
# 입력: path, data.
# 반환 타입 힌트: 별도 결과 없음(None).
def write_atomic(path: Path, data: bytes) -> None:
    """Write bytes through a durable temporary file and atomically replace the target."""
    # Path()의 반환값을 target에 대입합니다.
    target = Path(path)
    # target.with_suffix()의 반환값을 temporary에 대입합니다.
    temporary = target.with_suffix(target.suffix + ".tmp")
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with temporary.open("wb") as output:
        # 열린 출력 대상에 데이터를 기록합니다.
        output.write(data)
        # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
        output.flush()
        # 운영체제에 파일 내용을 저장 장치로 동기화하도록 요청합니다.
        os.fsync(output.fileno())
    # os.replace()을 호출해 작업을 수행합니다.
    os.replace(temporary, target)
    # _fsync_dir()을 호출해 작업을 수행합니다.
    _fsync_dir(target.parent)


# 지원되는 운영체제에서는 파일 이름 교체가 디렉터리에도 반영되도록 동기화합니다.
# 입력: directory.
# 반환 타입 힌트: 별도 결과 없음(None).
def _fsync_dir(directory: Path) -> None:
    """Persist the directory entry where supported; Windows has no equivalent."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: os.name == 'nt'.
    if os.name == "nt":
        # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
        return
    # os.open()의 반환값을 descriptor에 대입합니다.
    descriptor = os.open(directory, os.O_RDONLY)
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 운영체제에 파일 내용을 저장 장치로 동기화하도록 요청합니다.
        os.fsync(descriptor)
    # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
    finally:
        # 사용하던 연결이나 자원을 닫습니다.
        os.close(descriptor)
