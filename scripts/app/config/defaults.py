# 파이썬 공부 | scripts/app/config/defaults.py
# 설정 파일과 데이터 폴더의 기본 경로를 정합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Branch-local filesystem defaults for the v2 rebuild."""

from __future__ import annotations

from pathlib import Path

# Path()의 반환값을 PROTOTYPE_DATA_ROOT에 대입합니다.
PROTOTYPE_DATA_ROOT = Path(r"D:\Jarvis")
# Path()의 반환값을 DEFAULT_DATA_ROOT에 대입합니다.
DEFAULT_DATA_ROOT = Path(r"D:\Jarvis-v2-dev")
# 오른쪽 식을 계산한 값을 DEFAULT_CONFIG_DIR에 대입합니다.
DEFAULT_CONFIG_DIR = DEFAULT_DATA_ROOT / "config"
