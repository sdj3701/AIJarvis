# 파이썬 공부 | scripts/app/privacy/__init__.py
# scripts/app/privacy 폴더를 패키지로 구성하는 파일입니다. 공개할 이름을 모아 둘 수도 있습니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.

"""Privacy gate helpers for memory writes and summarizer input."""

from app.privacy.gate import PrivacyGate
from app.telemetry.masking import Finding

# __all__에 리스트(순서가 있고 수정 가능)을 대입합니다.
__all__ = ["Finding", "PrivacyGate"]
