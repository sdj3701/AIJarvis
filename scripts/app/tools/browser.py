# 파이썬 공부 | scripts/app/tools/browser.py
# 브라우저를 통해 URL을 여는 기능을 제공합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Safe browser URL opening without shell injection."""

from __future__ import annotations

import os
import sys
import webbrowser


# open_url_with_browser(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: url.
# 반환 타입 힌트: 별도 결과 없음(None).
def open_url_with_browser(url: str) -> None:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: sys.platform == 'win32'.
    if sys.platform == "win32":
        # os.startfile()을 호출해 작업을 수행합니다.
        os.startfile(url)
    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
    else:
        # webbrowser.open()을 호출해 작업을 수행합니다.
        webbrowser.open(url, new=2, autoraise=True)
