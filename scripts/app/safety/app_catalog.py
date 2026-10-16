# 파이썬 공부 | scripts/app/safety/app_catalog.py
# Windows 시작 메뉴와 등록 경로에서 실행 가능한 앱을 찾습니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Bounded Windows Start Menu and App Paths discovery; no executable arguments."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path


# CatalogEntry: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
@dataclass(frozen=True)
class CatalogEntry:
    # name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    name: str
    # path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    path: Path
    # source: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    source: str

# discover_apps(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: limit.
# 반환 타입 힌트: list[CatalogEntry].
def discover_apps(limit: int = 2000) -> list[CatalogEntry]:
    # found에 리스트(순서가 있고 수정 가능)을 대입합니다.
    found: list[CatalogEntry] = []
    # for 반복문: 대상의 항목을 하나씩 hive에 대입하며 아래 블록을 실행합니다.
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        # for 반복문: 대상의 항목을 하나씩 view에 대입하며 아래 블록을 실행합니다.
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
            try:
                # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
                # 사용합니다.
                with winreg.OpenKey(
                    hive,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
                    0,
                    winreg.KEY_READ | view,
                ) as root:
                    # for 반복문: 대상의 항목을 하나씩 index에 대입하며 아래 블록을 실행합니다.
                    for index in range(min(winreg.QueryInfoKey(root)[0], limit)):
                        # winreg.EnumKey()의 반환값을 name에 대입합니다.
                        name = winreg.EnumKey(root, index)
                        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를
                        # 처리합니다.
                        try:
                            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린
                            # 자원을 사용합니다.
                            with winreg.OpenKey(root, name) as entry:
                                # 언패킹: 오른쪽 결과를 순서대로 (value, _)에 나누어 담습니다.
                                value, _ = winreg.QueryValueEx(entry, "")
                                # 리스트 끝에 항목 하나를 추가합니다.
                                found.append(CatalogEntry(
                                    Path(name).stem, Path(str(value).strip('"')), "App Paths"
                                ))
                        # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
                        except OSError:
                            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로
                            # 이동합니다.
                            continue
            # OSError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
            except OSError:
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
    # Fixed script only; names/paths from the user are never interpolated as code.
    # script에 문자열을 대입합니다.
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$shell = New-Object -ComObject WScript.Shell
$roots = @([Environment]::GetFolderPath('StartMenu'),
           [Environment]::GetFolderPath('CommonStartMenu'))
$rows = @(foreach ($root in $roots) {
  Get-ChildItem -LiteralPath $root -Filter *.lnk -Recurse -File -ErrorAction SilentlyContinue |
    Select-Object -First 2000 | ForEach-Object {
      try {
        if ($_.Length -gt 1048576) { return }
        $link = $shell.CreateShortcut($_.FullName)
        $header = [System.IO.File]::ReadAllBytes($_.FullName)
        $runAs = $header.Length -lt 24 -or
          (([BitConverter]::ToUInt32($header, 20) -band 0x2000) -ne 0)
        if (!$runAs -and !$link.Arguments -and $link.TargetPath.EndsWith('.exe')) {
          @{name=$_.BaseName; path=$link.TargetPath}
        }
      } catch {}
    }
})
ConvertTo-Json -InputObject $rows -Compress
"""
    # 아래 함수()의 반환값을 encoded에 대입합니다.
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # 오른쪽 식을 계산한 값을 powershell에 대입합니다.
    powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # subprocess.run()의 반환값을 result에 대입합니다.
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True,
        )
        # for 반복문: 대상의 항목을 하나씩 row에 대입하며 아래 블록을 실행합니다.
        for row in json.loads(result.stdout):
            # 리스트 끝에 항목 하나를 추가합니다.
            found.append(CatalogEntry(row["name"], Path(row["path"]), "Start Menu"))
    # 아래 종류의 예외를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        # 문법상 블록은 필요하지만 여기서는 아무 작업도 하지 않습니다.
        pass  # App Paths results remain usable when shortcut discovery is unavailable.
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 슬라이싱: [시작:끝] 범위를 꺼냅니다. 끝 위치의 원소는 포함하지 않습니다.
    return found[:limit]
