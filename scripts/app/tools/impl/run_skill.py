# 파이썬 공부 | scripts/app/tools/impl/run_skill.py
# 스킬 등록·해시 검사 골격입니다. 실제 실행은 아직 구현되지 않아 예외로 끝납니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""User skill runner skeleton — disabled until Phase 6 threat model review."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import PolicyDenied, ToolExecutionFailed
from app.tools.base import ToolContext, ToolResult, ToolSpec


# SkillManifestEntry: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class SkillManifestEntry:
    # skill_name: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    skill_name: str
    # path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    path: Path
    # sha256: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    sha256: str
    # capabilities: frozenset[str] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    capabilities: frozenset[str]


# RunSkillTool: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
@dataclass
class RunSkillTool:
    """Disabled-by-default skill runner with hash/manifest guard stubs."""

    # spec: ToolSpec 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    spec: ToolSpec
    # registry에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
    registry: tuple[SkillManifestEntry, ...] = ()

    # run(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: args, tctx.
    # 반환 타입 힌트: ToolResult.
    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        # 대상 이름·항목·속성을 삭제합니다. del은 객체의 메모리 해제를 직접 명령하는 문법은
        # 아닙니다.
        del tctx
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not self.spec.enabled.
        if not self.spec.enabled:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(
                "run_skill은 Phase 6 위협 모델 검토 전까지 비활성화되어 있습니다."
            )
        # str()의 반환값을 skill_name에 대입합니다.
        skill_name = str(args.get("skill_name", ""))
        # _find_skill()의 반환값을 entry에 대입합니다.
        entry = _find_skill(self.registry, skill_name)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: entry is None.
        if entry is None:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied(f"등록되지 않은 스킬입니다: {skill_name}")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not entry.path.is_file().
        if not entry.path.is_file():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ToolExecutionFailed("스킬 파일을 찾을 수 없습니다.", {"path": str(entry.path)})
        # _sha256_file()의 반환값을 digest에 대입합니다.
        digest = _sha256_file(entry.path)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: digest != entry.sha256.
        if digest != entry.sha256:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("스킬 파일 SHA-256이 manifest와 일치하지 않습니다.")
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ToolExecutionFailed(
            "run_skill 실행 골격만 준비되었습니다. Phase 6 이후 활성화됩니다.",
            {"skill_name": skill_name},
        )


# _find_skill(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: registry, skill_name.
# 반환 타입 힌트: SkillManifestEntry | None.
def _find_skill(
    registry: tuple[SkillManifestEntry, ...],
    skill_name: str,
) -> SkillManifestEntry | None:
    # for 반복문: 대상의 항목을 하나씩 entry에 대입하며 아래 블록을 실행합니다.
    for entry in registry:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: entry.skill_name == skill_name.
        if entry.skill_name == skill_name:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return entry
    # None을 반환하고 이 함수의 실행을 끝냅니다.
    return None


# _sha256_file(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: 문자열(str).
def _sha256_file(path: Path) -> str:
    # hashlib.sha256()의 반환값을 digest에 대입합니다.
    digest = hashlib.sha256()
    # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
    with path.open("rb") as handle:
        # for 반복문: 대상의 항목을 하나씩 chunk에 대입하며 아래 블록을 실행합니다.
        for chunk in iter(lambda: handle.read(65536), b""):
            # digest.update()을 호출해 작업을 수행합니다.
            digest.update(chunk)
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return digest.hexdigest()
