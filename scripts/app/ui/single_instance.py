# 파이썬 공부 | scripts/app/ui/single_instance.py
# 앱이 동시에 여러 번 실행되지 않도록 Windows 잠금을 사용합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Windows process-wide single-instance lock."""

from __future__ import annotations

import msvcrt
import os
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from app.core.errors import JarvisError


# AlreadyRunningError: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# 부모 클래스의 기능을 물려받습니다: JarvisError.
class AlreadyRunningError(JarvisError):
    """Another Jarvis process owns the state lock."""


# SingleInstanceLock: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class SingleInstanceLock:
    """Hold an exclusive byte-range lock for the lifetime of the application."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: lock_path.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, lock_path: Path) -> None:
        # Path()의 반환값을 self._path에 대입합니다.
        self._path = Path(lock_path)
        # self._file을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._file: BinaryIO | None = None

    # acquired(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 참/거짓(bool).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def acquired(self) -> bool:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._file is not None

    # acquire(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def acquire(self) -> None:
        """Take a non-blocking byte lock so a second process fails immediately."""
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._file is not None.
        if self._file is not None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise RuntimeError("single-instance lock is already acquired")
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # self._path.open()의 반환값을 lock_file에 대입합니다.
            lock_file = self._path.open("a+b")
        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OSError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise JarvisError(
                "단일 인스턴스 잠금 파일을 열 수 없습니다.",
                {"error_type": type(error).__name__},
            ) from error

        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # lock_file.seek()을 호출해 작업을 수행합니다.
            lock_file.seek(0, os.SEEK_END)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lock_file.tell() == 0.
            if lock_file.tell() == 0:
                # 열린 출력 대상에 데이터를 기록합니다.
                lock_file.write(b"\0")
                # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
                lock_file.flush()
            # lock_file.seek()을 호출해 작업을 수행합니다.
            lock_file.seek(0)
            # msvcrt.locking()을 호출해 작업을 수행합니다.
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except OSError as error:
            # 사용하던 연결이나 자원을 닫습니다.
            lock_file.close()
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise AlreadyRunningError(
                "Jarvis가 이미 실행 중입니다.", {"lock_file": self._path.name}
            ) from error
        # 오른쪽 식을 계산한 값을 self._file에 대입합니다.
        self._file = lock_file

    # release(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def release(self) -> None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._file is None.
        if self._file is None:
            # 이 함수를 여기서 끝냅니다. 값을 쓰지 않은 return은 None을 반환합니다.
            return
        # 오른쪽 식을 계산한 값을 lock_file에 대입합니다.
        lock_file = self._file
        # self._file을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._file = None
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # lock_file.seek()을 호출해 작업을 수행합니다.
            lock_file.seek(0)
            # msvcrt.locking()을 호출해 작업을 수행합니다.
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        # 정상 종료·예외·return 여부와 관계없이 블록을 벗어날 때 정리 작업을 실행합니다.
        finally:
            # 사용하던 연결이나 자원을 닫습니다.
            lock_file.close()

    # __enter__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: SingleInstanceLock.
    def __enter__(self) -> SingleInstanceLock:
        # self.acquire()을 호출해 작업을 수행합니다.
        self.acquire()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self

    # __exit__(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: exc_type, exc_value, traceback.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # self.release()을 호출해 작업을 수행합니다.
        self.release()
