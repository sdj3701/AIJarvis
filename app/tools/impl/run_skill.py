"""User skill runner skeleton — disabled until Phase 6 threat model review."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import PolicyDenied, ToolExecutionFailed
from app.tools.base import ToolContext, ToolResult, ToolSpec


@dataclass(frozen=True, slots=True)
class SkillManifestEntry:
    skill_name: str
    path: Path
    sha256: str
    capabilities: frozenset[str]


@dataclass
class RunSkillTool:
    """Disabled-by-default skill runner with hash/manifest guard stubs."""

    spec: ToolSpec
    registry: tuple[SkillManifestEntry, ...] = ()

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        del tctx
        if not self.spec.enabled:
            raise PolicyDenied(
                "run_skill은 Phase 6 위협 모델 검토 전까지 비활성화되어 있습니다."
            )
        skill_name = str(args.get("skill_name", ""))
        entry = _find_skill(self.registry, skill_name)
        if entry is None:
            raise PolicyDenied(f"등록되지 않은 스킬입니다: {skill_name}")
        if not entry.path.is_file():
            raise ToolExecutionFailed("스킬 파일을 찾을 수 없습니다.", {"path": str(entry.path)})
        digest = _sha256_file(entry.path)
        if digest != entry.sha256:
            raise PolicyDenied("스킬 파일 SHA-256이 manifest와 일치하지 않습니다.")
        raise ToolExecutionFailed(
            "run_skill 실행 골격만 준비되었습니다. Phase 6 이후 활성화됩니다.",
            {"skill_name": skill_name},
        )


def _find_skill(
    registry: tuple[SkillManifestEntry, ...],
    skill_name: str,
) -> SkillManifestEntry | None:
    for entry in registry:
        if entry.skill_name == skill_name:
            return entry
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
