# 기능 제안서: 화이트리스트 기반 애플리케이션 종료 도구 (`close_app`)

> **문서 상태**: 제안됨 (Proposed / Post-v1 또는 Phase 4 확장 백로그)  
> **관련 Phase**: [Phase 4 PC 도구](../phase-04-tools/README.md) · [Post-v1](../post-v1/README.md)  
> **위험도 등급**: `medium` (사용자 y/n 명시적 승인 필수)

---

## 1. 개요 및 목적

사용자가 자비스에게 음성이나 텍스트로 *"메모장 꺼줘"*, *"크롬 닫아줘"* 같은 프로세스 제어 명령을 내렸을 때, **사전에 허용된(Allowlisted) 애플리케이션에 한하여 안전하게 프로그램을 종료**하는 도구(`close_app`)를 추가합니다.

---

## 2. 해결하려는 문제 & 사용자 가치

* **해결하려는 문제**: 현재 자비스는 `open_app`(프로그램 실행)만 지원하며 실행된 프로그램을 닫거나 제어하는 도구가 없어, 사용자가 수동으로 창을 닫아야 함.
* **사용자 가치**: PC 핸즈프리 제어 및 작업 환경 정리 자동화 지원.

---

## 3. 보안 원칙 및 위협 모델 검토

1. **임의 프로세스 종료(Arbitrary Kill) 영구 차단**:
   - `taskkill`이나 PID 기반의 무제한 종료를 허용할 경우, Windows 핵심 시스템 프로세스(`csrss.exe`, `explorer.exe`, `svchost.exe`)나 자비스 자체 DB/프로세스가 강제 종료될 위험이 있음.
   - **방어**: `tools.yaml`의 `app_map`에 등록된 이름(Enum)만 지정 가능하도록 강제.
2. **저장되지 않은 작업 데이터 보호 (승인 필수)**:
   - 실수로 작업 중인 프로그램이 꺼지는 것을 방지하기 위해 기본 위험도를 **`medium`**으로 지정.
   - 사용자에게 **"OOO(프로그램명)을 종료하시겠습니까? (y/n)"** 확인창을 띄우고 승인 티켓이 발급된 경우에만 실행.
3. **명령어 인젝션 방지**:
   - `shell=True`를 절대 사용하지 않고, `subprocess.run(["taskkill", "/IM", exe_name, "/T", "/F"], shell=False)`로 인자 배열만 전달.

---

## 4. 상세 설계 및 인터페이스

### 4.1 설정 정의 (`config/tools.yaml`)

```yaml
  - name: close_app
    enabled: true
    phase: 4
    risk: medium                    # 실행 전 (y/n) 승인 필수
    capabilities: [proc_spawn]
    execution_mode: in_process
    idempotent: false
    untrusted_output: false
    timeout_s: 10
    description: "허용 목록에 등록된 애플리케이션 프로세스를 종료합니다."
    app_map:
      notepad: "notepad.exe"
      calc: "CalculatorApp.exe"
      chrome: "chrome.exe"
      vscode: "Code.exe"
```

### 4.2 도구 구현체 (`app/tools/impl/close_app.py`)

```python
"""Allowlisted application termination tool."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any

from app.tools.base import ToolContext, ToolResult, ToolSpec


@dataclass
class CloseAppTool:
    spec: ToolSpec

    def run(self, args: dict[str, Any], tctx: ToolContext) -> ToolResult:
        start = time.monotonic()
        normalized = tctx.normalized_args or {}
        exe_name = str(normalized.get("exe_name", "")).strip()
        app_name = str(normalized.get("app", exe_name))

        if not exe_name:
            return ToolResult(
                ok=False,
                output="종료할 애플리케이션 대상이 지정되지 않았습니다.",
                error="missing_exe_name",
                data=None,
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )

        try:
            # shell=False로 taskkill 실행 (/T: 자식 트리 프로세스 포함, /F: 강제)
            proc = subprocess.run(
                ["taskkill", "/IM", exe_name, "/T", "/F"],
                capture_output=True,
                text=True,
                shell=False,
                timeout=self.spec.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False,
                output="프로그램 종료 작업 시간이 초과되었습니다.",
                error="timeout",
                data=None,
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )
        except Exception as error:
            return ToolResult(
                ok=False,
                output=f"프로세스 종료 중 오류가 발생했습니다: {error}",
                error=str(error),
                data=None,
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )

        if proc.returncode == 0:
            return ToolResult(
                ok=True,
                output=f"[{app_name}] 애플리케이션을 종료했습니다.",
                error=None,
                data={"app": app_name, "exe_name": exe_name},
                changed_paths=(),
                duration_ms=_ms(start),
                truncated=False,
                untrusted=False,
            )

        return ToolResult(
            ok=False,
            output=f"[{app_name}] 프로그램이 실행 중이지 않거나 종료할 수 없습니다.",
            error=proc.stderr.strip() or "process_not_found",
            data=None,
            changed_paths=(),
            duration_ms=_ms(start),
            truncated=False,
            untrusted=False,
        )


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
```

---

## 5. 작업 순서 (Checklist)

- [ ] **1. 설정 반영**: `config/tools.example.yaml` 및 `tools.yaml`에 `close_app` 스키마 및 `app_map` 등록
- [ ] **2. 도구 구현**: `app/tools/impl/close_app.py` 작성
- [ ] **3. Safety Gate 정규화**: `app/safety/gate.py`에서 `close_app` 인자 검증 및 `exe_name` 바인딩
- [ ] **4. 레지스트리 등록**: `app/tools/registry.py`에 `close_app` 매핑
- [ ] **5. 감사 로그 연동**: `app/telemetry/audit.py`에 intent/result 정상 기록 확인
- [ ] **6. 단위 및 보안 테스트**:
  - `tests/unit/test_close_app.py` (비등록 앱 거부, 정상 프로세스 종료)
  - `tests/security/test_close_app_security.py` (인젝션 공격 시도 차단, 시스템 프로세스 보호)

---

## 6. 롤백 (Rollback) 방안

* 설정 파일(`tools.yaml`)에서 `close_app` 항목의 `enabled: false`로 변경하거나 삭제하면 즉시 비활성화되어 이전 상태로 복구됩니다.
