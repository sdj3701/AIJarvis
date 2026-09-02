# Phase 5 — 멀티스텝 에이전트 단계별(Step 1~6) 파이프라인 가이드

> 자비스(Jarvis)의 Phase 5 멀티스텝 에이전트 루프(`Decide → Validate → Act → Observe → Final`)에서 실행되는 **Step 1부터 Step 6까지의 전체 실행 흐름, 소스 코드 구현, 보안 및 상태 머신 명세**입니다.

---

## 1. 전체 파이프라인 개요

```
[사용자 요청]
      │
      ▼
┌────────────────────────────────────────────────────────┐
│ Agent Loop (app/orchestrator/agent.py)                 │
│                                                        │
│ 1. Step 1: web_search  (웹 검색 및 출처 URL 수집)       │
│      ▼                                                 │
│ 2. Step 2: fetch_url   (SSRF 방어 기반 웹 본문 추출)   │
│      ▼                                                 │
│ 3. Step 3: LLM Reason  (근거 기반 마크다운 요약 생성)  │
│      ▼                                                 │
│ 4. Step 4: create_file (승인 대기 및 원자적 파일 생성) │
│      ▼                                                 │
│ 5. Step 5: open_folder (안전한 탐색기/폴더 열기)       │
│      ▼                                                 │
│ 6. Step 6: Final Report(단계 현황 분류 및 Task 완료)   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Step 3: LLM 추론 및 근거 기반 요약 (Reason & Summarize)

### 2.1 개념 및 역할
Step 1(검색)과 Step 2(본문 추출)에서 얻은 `<untrusted_content>` 데이터를 프롬프트에 주입하고, LLM이 **출처 URL과 인용구에만 기반하여 사실(Fact)을 정리하고 마크다운 문서를 작성**하는 단계입니다.

### 2.2 구현 코드 (`app/orchestrator/agent.py`의 `_decide` 및 `_observe`)

```python
def _decide(
    self,
    goal: str,
    observations: Sequence[Message],
    *,
    ctx: RequestContext,
    timeout_s: float,
) -> Any:
    # 1. 토큰 및 비용 사전 체크
    estimated = estimate_llm_cost(
        self._settings.llm,
        prompt_tokens=self._settings.llm.context.max_input_tokens,
        max_output_tokens=self._settings.llm.max_output_tokens,
    )
    self._budget.check("llm", estimated, ctx=ctx)
    
    # 2. 도구 프롬프트 및 사용자 목표 구성
    tools_prompt = load_tools_prompt()
    agent_instruction = (
        f"사용자 목표: {goal}\n"
        "한 번에 하나의 도구만 호출하거나, 모든 단계가 끝났으면 최종 답변을 작성하세요."
    )
    
    # 3. 이전 단계의 도구 관찰 결과(Observation)를 누적 주입
    if observations:
        lines = [agent_instruction, "", "이전 단계 관찰:"]
        for message in observations:
            if message.role == "assistant":
                lines.append(message.content)
            elif message.role == "tool":
                label = message.name or "tool"
                lines.append(f"[{label} 결과]\n{message.content}")
        agent_instruction = "\n".join(lines)
        
    plan = self._prompt.build(
        current_user_text=agent_instruction,
        history=(),
        cancel=ctx.cancel,
        extra_system=(tools_prompt,),
    )
    
    # 4. LLM 호출 (도구 스펙 제공)
    tool_specs = self._registry.llm_tool_specs()
    response = self._llm.complete(
        messages=plan.messages,
        tools=tool_specs,
        timeout_s=timeout_s,
        ctx=ctx,
        temperature=self._settings.llm.temperature,
        max_output_tokens=self._settings.llm.max_output_tokens,
    )
    self._budget.record_llm(response.usage, ctx=ctx)
    return response
```

---

## 3. Step 4: 파일 저장 도구 (`create_file` & 승인 인터럽트)

### 3.1 개념 및 역할
LLM이 생성한 요약문을 `notes/` 등 지정된 샌드박스 폴더에 안전하게 저장합니다. 파일 쓰기는 **부작용(Side-effect)**을 수반하므로:
1. 사용자 의도(Intent)에 "저장/파일"이 포함되어 있는지 검증.
2. `Medium` 위험도 작업으로 분류되어 **사용자 승인 대기(`TurnOutcome.pending_approval`)로 루프 일시 중단**.
3. 승인 완료 후 티켓(`ApprovalTicket`)을 검증하고 `write_atomic`으로 안전하게 생성.

### 3.2 구현 코드 (`app/tools/impl/create_file.py`)

```python
"""Create text files under allowed sandbox roots."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.atomic import write_atomic
from app.core.errors import ToolExecutionFailed
from app.tools.base import ToolContext, ToolResult, ToolSpec


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


@dataclass
class CreateFileTool:
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        normalized = tctx.normalized_args or {}
        target = Path(str(normalized.get("path", "")))
        content = str(normalized.get("content", ""))
        overwrite = bool(normalized.get("overwrite", False))
        
        if not target:
            return ToolResult(
                ok=False,
                output="대상 경로가 없습니다.",
                data=None,
                error="missing_path",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
            
        if target.exists() and not overwrite:
            return ToolResult(
                ok=False,
                output="파일이 이미 존재합니다.",
                data=None,
                error="exists",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
            
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # 원자적 쓰기 (임시 파일 생성 후 atomic rename)
            write_atomic(target, content.encode("utf-8"))
        except OSError as error:
            raise ToolExecutionFailed(
                "파일을 생성하지 못했습니다.",
                {"path": str(target), "error": str(error)},
            ) from error
            
        return ToolResult(
            ok=True,
            output=f"파일을 생성했습니다: {target}",
            data={"path": str(target), "overwrite": overwrite},
            error=None,
            changed_paths=(str(target),),
            duration_ms=_ms(start),
            truncated=False,
            untrusted=False,
        )
```

---

## 4. Step 5: 폴더 열기 도구 (`open_folder`)

### 4.1 개념 및 역할
파일 저장이 완료된 후 사용자가 결과물을 바로 확인할 수 있도록 Windows 탐색기(`os.startfile`)를 통해 해당 디렉터리를 엽니다.
- `Low` 위험도로 분류되어 정책 허용 범위 내에서 자동 실행됩니다.
- 경로 탐색(`..` Traversal)이나 시스템 영역 접근은 Canonical Path 검증으로 사전 차단됩니다.

### 4.2 구현 코드 (`app/tools/impl/open_folder.py`)

```python
"""Open an existing folder under an allowed sandbox root."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from app.core.errors import ToolExecutionFailed
from app.tools.base import ToolContext, ToolResult, ToolSpec


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


@dataclass
class OpenFolderTool:
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        normalized = tctx.normalized_args or {}
        folder = str(normalized.get("path", ""))
        
        if not folder:
            return ToolResult(
                ok=False,
                output="폴더 경로가 없습니다.",
                data=None,
                error="missing_path",
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
            
        try:
            if os.name == "nt":
                os.startfile(folder)
                pid = None
            else:
                proc = subprocess.Popen(
                    ["xdg-open", folder],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                pid = proc.pid
        except OSError as error:
            raise ToolExecutionFailed(
                "폴더를 열지 못했습니다.",
                {"path": folder, "error": str(error)},
            ) from error
            
        return ToolResult(
            ok=True,
            output=f"폴더를 열었습니다: {folder}",
            data={"path": folder, "pid": pid},
            error=None,
            changed_paths=(),
            duration_ms=_ms(start),
            truncated=False,
            untrusted=False,
        )
```

---

## 5. Step 6: 최종 결과 및 단계 현황 보고 (Final Reporting)

### 5.1 개념 및 역할
에이전트가 모든 단계를 마쳤을 때, `Task` 상태를 `succeeded`로 전이하고 사용자에게 최종 답변과 함께 **완료/실패/취소/미실행 단계 목록**을 명확하게 포맷팅하여 투명하게 전달합니다.

### 5.2 구현 코드 (`app/orchestrator/agent.py`의 `format_step_breakdown`)

```python
def format_step_breakdown(steps: Sequence[StepRecord], *, max_steps: int) -> str:
    """완료, 실패, 취소, 미실행 단계를 투명하게 구분하여 마크다운으로 포맷팅."""
    completed = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "succeeded"]
    failed = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "failed"]
    cancelled = [str(s.step_no) + "." + s.tool_name for s in steps if s.state == "cancelled"]
    executed = {s.step_no for s in steps}
    not_run = [
        str(number)
        for number in range(1, max_steps + 1)
        if number not in executed
    ]
    
    lines = ["## 단계 현황"]
    lines.append("완료: " + (", ".join(completed) if completed else "없음"))
    lines.append("실패: " + (", ".join(failed) if failed else "없음"))
    if cancelled:
        lines.append("취소: " + ", ".join(cancelled))
    lines.append("미실행: " + (", ".join(not_run) if not_run else "없음"))
    return "\n".join(lines)
```

---

## 6. 전체 실행 및 상태 모델 요약

| 단계 | 도구 / 동작 | 위험도 | 멱등성 / 재시도 | 승인 필요 여부 |
| :--- | :--- | :--- | :--- | :--- |
| **Step 1** | `web_search` | Low | Idempotent / 자동 재시도 2회 | X (자동 실행) |
| **Step 2** | `fetch_url` | Low | Idempotent / 일시 오류 1회 | X (자동 실행) |
| **Step 3** | `_decide` (LLM) | - | 컨텍스트 추론 | X |
| **Step 4** | `create_file` | Medium | Non-idempotent / 재시도 금지 | **O (승인 후 실행)** |
| **Step 5** | `open_folder` | Low | Non-idempotent / 재시도 금지 | X (자동 실행) |
| **Step 6** | `Final Report` | - | DB 상태 `succeeded` 커밋 | X |
