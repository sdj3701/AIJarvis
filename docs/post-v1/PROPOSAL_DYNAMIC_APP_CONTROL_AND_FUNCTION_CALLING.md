# 기능 제안서: LLM 도구 호출과 동적 애플리케이션 제어

> **문서 상태**: 제안됨 (Proposed / Post-v1 우산 제안)
>
> **검토 기준일**: 2026-09-07
>
> **관련 Phase**: [Phase 1 대화](../phase-01-chat/README.md) · [Phase 4 PC 도구](../phase-04-tools/README.md) · [Phase 5 에이전트](../phase-05-agent/README.md)
>
> **대체하는 제안**: [화이트리스트 기반 애플리케이션 종료 도구](PROPOSAL_CLOSE_APP.md) (레거시 `/IM` 강제 종료 설계)
>
> **위험 분류**: 실행은 `low` / `medium` / `high`, 보호 대상은 `forbidden` 결정
> **결정 ID**: 미정. 도구 호출, 동적 탐색 권한, 프로세스 종료 정책을 각각 결정 기록으로 등록해야 함

---

## 1. 제안 요약

이 제안은 조건부로 추진한다. 먼저 Ollama의 네이티브 도구 호출을 기존 `ToolSpec`과 `ToolCall` 계약에 연결하고, 실제 모델 평가를 통과한 뒤 동적 애플리케이션 탐색을 추가한다. 프로세스 종료는 마지막 단계로 분리한다. 세 단계는 각각 별도 브랜치, 결정 기록, 테스트 게이트로 배포한다.

동적 탐색은 실행 권한을 자동으로 부여하는 기능이 아니다. 시작 메뉴와 레지스트리에서 찾은 항목은 후보일 뿐이며, `default: deny`, Safety Gate, 승인 티켓, 감사 로그를 그대로 거쳐야 한다. 기존 `app_map`은 신뢰된 앱과 별칭을 명시하는 정책으로 유지한다.

프로그램 종료는 창 닫기 요청을 기본 동작으로 사용한다. 프로세스 강제 종료는 사용자가 명시적으로 요청한 경우에만 `high` 위험으로 처리한다. 이미지 이름만으로 여러 프로세스를 한꺼번에 종료하는 `taskkill /IM ... /T /F` 방식은 **정적·동적 종료 경로 모두에서 금지**한다.

Gate C의 구현을 시작하기 전에 기존 `close_app`의 `/IM ... /T /F` 경로를 기본 비활성화하고, 설정의 `close_app.app_map`에서 `explorer`를 제거하며, Safety Gate가 정적 별칭으로도 `explorer.exe` 종료를 거부해야 한다. 이 선행 완화가 배포되기 전에는 이 제안의 종료 기능을 활성화하지 않는다.

| 항목 | 제안 결론 |
|------|-----------|
| 자연어 도구 선택 | Ollama 네이티브 도구 호출을 사용하되 모델 출력은 계속 불신하고 검증한다 |
| 명시적 명령 | `/open_app` 같은 슬래시 명령은 복구 및 진단 경로로 유지한다 |
| 한국어 정규식 파서 | 평가 게이트 통과 전까지 폴백으로 유지하고 이후 제거한다 |
| 앱 탐색 | 로컬의 시작 메뉴와 App Paths를 결정론적으로 스캔한다 |
| 앱 권한 | `app_map`과 자동 탐색 모두 최초 실행 승인을 요구하며 SID·경로·해시가 같은 앱의 허용만 재사용한다 |
| 앱 종료 | 동일 사용자·동일 세션의 대화형 앱만 대상으로 삼고 먼저 정상 종료를 시도한다 |
| 강제 종료 | 별도 `high` 위험 동작으로 분리하고 정확한 프로세스 식별자에 승인 티켓을 묶는다 |

---

## 2. 현재 구현과 해결할 문제

현재 코드는 도구 실행 기반을 이미 갖추고 있다. 문제는 `close_app` 도구가 없어서가 아니라, 실제 Ollama 클라이언트와 자연어 경로가 그 기반을 충분히 사용하지 못하고 앱 식별이 정적 목록에 묶여 있다는 점이다.

| 위치 | 현재 상태 | 영향 |
|------|-----------|------|
| `scripts/app/llm/base.py` | `ToolCall`, `LLMResponse.tool_calls`, `Message(role="tool")` 계약이 존재한다 | 제공자 중립 계약은 대부분 준비되어 있다 |
| `scripts/app/tools/registry.py` | 활성 도구의 JSON Schema를 만들고 LLM용 명세를 제공한다 | 스키마 생성 기반을 재사용할 수 있다 |
| `scripts/app/orchestrator/agent.py` | 에이전트 단계가 `registry.llm_tool_specs()`를 LLM에 전달한다 | Ollama 클라이언트의 차단 때문에 실제 로컬 모델에서는 사용할 수 없다 |
| `scripts/app/orchestrator/loop.py` | 일반 대화 호출에는 도구 명세를 전달하지 않지만 반환된 `tool_calls` 처리 분기는 존재한다 | 자연어 단일 도구 요청이 네이티브 도구 호출로 진입하지 못한다 |
| `scripts/app/llm/ollama_client.py` | `tools`, `tool` 역할 메시지, 응답의 `message.tool_calls`를 명시적으로 거부한다 | Ollama 도구 호출이 봉인되어 있다 |
| `scripts/app/orchestrator/tool_commands.py` | 메모장과 계산기 실행만 한국어 정규식으로 처리한다 | 표현과 앱을 추가할 때 코드 변경이 필요하다 |
| `open_app`과 `close_app` | 두 도구 모두 구현되어 있고 `app_map` 열거값만 허용한다 | 안전하지만 새 앱을 찾지 못한다 |
| `close_app` 구현 | `taskkill /IM <exe> /T /F`로 같은 이미지 이름의 프로세스 트리를 강제 종료한다 | 동적 대상에 그대로 적용하면 오종료와 데이터 손실 범위가 커진다 |

`app_map`의 절대 경로 검증은 단순한 하드코딩 결함이 아니라 현재 보안 경계다. 동적 탐색을 도입할 때 이 경계를 삭제하지 말고, 발견과 권한 부여를 분리해야 한다.

---

## 3. 사용자 가치와 범위

### 3.1 사용자 가치

- 사용자는 정해진 두세 가지 문장 대신 자연스러운 한국어로 도구를 요청할 수 있다.
- 새 애플리케이션을 설치한 뒤 소스코드를 고치지 않고 실행 후보를 찾을 수 있다.
- 앱 종료 시 대상과 종료 방식이 승인 화면에 명확하게 표시된다.
- 도구 선택 실패와 정책 거부를 구분해 원인을 안내할 수 있다.

### 3.2 포함 범위

- Ollama `/api/chat`의 단일 도구 호출 요청과 응답 변환
- 도구 결과를 후속 LLM 호출에 전달하는 제공자 중립 메시지 계약
- 사용자 및 공용 시작 메뉴와 Windows App Paths 기반 앱 카탈로그
- 한국어와 영어 별칭, 정확 일치, 제한된 유사도 검색
- 동일 사용자·동일 세션의 대화형 애플리케이션 정상 종료
- 사용자가 명시적으로 요청한 정확한 PID의 강제 종료
- 단계별 기능 플래그, 감사 로그, 롤백 경로

### 3.3 제외 범위

- LLM이 셸 명령, 실행 파일 경로, PID를 직접 생성하는 기능
- 설치된 모든 프로그램에 자동으로 저위험 실행 권한을 부여하는 기능
- Windows 서비스, 드라이버, 다른 사용자 세션, 보안 프로세스 제어
- 창 최소화, 버튼 클릭, 범용 GUI 자동화
- 관리자 권한 상승과 UAC 자동 승인
- 한 단계에서 여러 도구를 병렬 실행하는 기능
- 모델 교체와 다중 모델 라우팅

---

## 4. 릴리스 분리 원칙

이 문서는 공통 구조를 설명하는 우산 제안서다. [Post-v1 분리 원칙](README.md)에 따라 아래 게이트를 한 릴리스에 묶지 않는다.

```text
Gate A  Ollama 네이티브 도구 호출
  ↓ 실제 모델 평가와 기존 회귀 테스트 통과
Gate B  동적 애플리케이션 탐색과 실행
  ↓ 앱 식별 및 최초 실행 승인 평가 통과
Gate C  동적 애플리케이션 정상 종료
  ↓ 보호 프로세스와 오종료 보안 평가 통과
선택 Gate D  강제 종료
```

Gate D는 Gate C와 별도 결정으로 승인할 수 있다. 강제 종료를 승인하지 않아도 정상 종료 기능은 배포 가능해야 한다. Gate C를 끄는 롤백은 레거시 `/IM` 강제 종료를 되살리는 수단이 아니다.

---

## 5. Gate A 설계

### 5.1 Ollama 요청 변환

`ToolSpec`을 Ollama 전송 형식으로 바꾸는 어댑터를 `scripts/app/llm/ollama_client.py` 내부에 둔다. 오케스트레이터와 도구 구현은 Ollama 전용 구조를 알지 않는다.

```json
{
  "type": "function",
  "function": {
    "name": "open_app",
    "description": "애플리케이션을 검색하고 정책 검증 후 실행한다.",
    "parameters": {
      "type": "object",
      "additionalProperties": false,
      "required": ["app"],
      "properties": {
        "app": {
          "type": "string",
          "maxLength": 128
        }
      }
    }
  }
}
```

Ollama 공식 형식의 `tools[].function.parameters`에 현재 `ToolSpec.json_schema`를 넣는다. 활성화되지 않은 도구와 현재 Phase보다 높은 도구는 전송하지 않는다.

### 5.2 응답 검증

`message.tool_calls`가 있으면 각 항목의 `function.name`과 `function.arguments`를 검증한 뒤 내부 `ToolCall`로 변환한다.

- Ollama 응답에는 호출 ID가 없을 수 있으므로 `request_id`와 호출 순번으로 내부 ID를 만든다. 이 ID는 승인·감사·메모리용 내부 식별자이며 Ollama 요청에는 `tool_call_id` 필드로 전송하지 않는다.
- 도구 호출이 있으면 빈 `message.content`를 허용하고 `finish_reason="tool_calls"`로 정규화한다.
- 등록되지 않은 도구, 객체가 아닌 인자, 알 수 없는 필드, 제어문자, 길이 초과는 실행 전에 거부한다.
- Phase 5의 한 단계 한 도구 규칙에 따라 한 응답에 호출이 둘 이상이면 모두 실행하지 않고 응답 오류로 처리한다.
- 모델이 일반 텍스트와 도구 호출을 함께 반환하면 도구 호출만 검증 대상으로 삼고, 텍스트를 승인 근거로 사용하지 않는다.

### 5.3 도구 결과 메시지와 이력

도구를 실행한 뒤의 후속 요청은 다음 순서를 **그대로** 보존한다. 도구 호출이 포함된 assistant 메시지를 텍스트 요약이나 `"[step] 도구명"`으로 대체하면 안 된다.

```text
user      원래 사용자 요청
assistant content + tool_calls  첫 Ollama 응답의 검증된 도구 호출 이력
tool      tool_name + 제한·Privacy Gate 처리된 도구 결과
assistant 최종 답변 또는 다음 한 개의 도구 호출
```

Ollama 어댑터는 후속 요청의 도구 결과를 `role="tool"`, `tool_name`, `content` 형식으로 전송한다. 제공자 중립 `Message`에는 assistant 역할의 `tool_calls: tuple[ToolCall, ...]`를 추가한다. `Message.tool_call_id`는 내부 감사·메모리 결합용으로 유지하되 Ollama 직렬화 시에는 내보내지 않는다. 이 계약과 [DESIGN 5.1 LLM](../DESIGN.md)의 타입을 먼저 함께 수정한다.

도구 결과의 원문을 무제한으로 다시 보내지 않는다. 기존 출력 크기 제한과 `untrusted` 봉투를 유지하고, 민감정보는 Privacy Gate를 통과시킨다.

### 5.4 오케스트레이터 연결

- 일반 대화의 첫 LLM 호출에 `registry.llm_tool_specs()`를 전달한다.
- 일반 대화에서 도구 호출을 받으면 `response.tool_calls[0]`을 실행하고 바로 반환하는 경로를 제거한다. 단일 도구도 5.3의 assistant·tool 이력을 포함한 후속 호출을 반드시 수행한다.
- `AgentRunner`에는 `ToolCall` 하나가 아니라 최초 `LLMResponse` 또는 동등한 assistant 메시지 이력을 전달한다. 따라서 최초 호출의 `content`와 `tool_calls`를 보존한 뒤 관찰 결과를 추가할 수 있다.
- 검색 결과를 답변으로 합성하는 호출에는 도구 명세를 전달하지 않는다. 외부 콘텐츠가 새 도구 목표를 만들지 못하게 하기 위해서다.
- 모델이 제안한 호출은 항상 `ToolRunner → JSON Schema → Safety Gate → 승인 → 감사 → 실행` 순서를 따른다.
- 여러 단계가 필요한 작업은 기존 AgentRunner에 넘기고 `max_steps`, timeout, 멱등성 규칙을 유지한다. Ollama 파서, 일반 대화 루프, AgentRunner의 세 경로 모두에서 다중 호출은 실행 전에 전체 거부한다.

### 5.5 정규식 폴백

`parse_tool_command`의 슬래시 명령은 유지한다. `parse_simple_korean_intent`는 Gate A 평가가 통과하고 한 릴리스 동안 회귀가 없을 때 제거한다. 기능 플래그를 끄면 즉시 정규식 폴백으로 돌아갈 수 있어야 한다.

---

## 6. Gate B 설계

### 6.1 앱 카탈로그

앱 카탈로그는 다음 소스를 읽는다.

- 사용자 시작 메뉴의 `.lnk`
- 공용 시작 메뉴의 `.lnk`
- `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths`
- `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths`
- 필요한 경우 32비트와 64비트 레지스트리 뷰

첫 버전은 대상 실행 파일을 검증할 수 없는 바로가기, URL, 스크립트, 명령 셸, 제거 프로그램, 관리자 도구를 후보에서 제외한다. Microsoft Store 앱과 AppUserModelID 실행은 별도 제안으로 남긴다.

카탈로그 레코드는 최소한 다음 값을 가진다.

```text
app_id
display_name
normalized_names
source
shortcut_path 또는 app_path_key
canonical_executable_path
file_identity
last_verified_at
```

`app_id`는 표시 이름이 아니라 정규화된 출처와 실행 파일 식별자로 만든다. 같은 이름의 앱이 여러 개 있을 수 있기 때문이다. `file_identity`는 가능하면 Windows 볼륨 일련번호와 파일 ID로 구성한다.

### 6.1.1 설정 경계

동적 탐색은 `ToolDefinition`의 명시적인 `dynamic_discovery_enabled` 플래그가 `true`일 때만 켠다. 카탈로그 TTL, 최대 후보 수, 정확 일치·유사도 최소 점수와 1·2위 최소 점수 차이도 같은 설정 계약에 둔다. 이 플래그가 `false`이면 현재의 `app_map` enum 스키마와 정적 정규화를 그대로 사용한다.

설정 검증도 이 두 모드를 구분한다. 정적 모드는 비어 있지 않은 `app_map`을 요구하고, 동적 모드는 `app_map`이 비어 있어도 되지만 카탈로그 정책과 해석 한도가 모두 있어야 한다. `app_map`이 함께 있으면 신뢰된 별칭 정책으로 유지한다. 즉 `app_map`이 없다는 이유만으로 동적 모드를 막거나, 동적 모드라는 이유로 정적 별칭의 검증을 약화해서는 안 된다.

### 6.2 캐시와 갱신

- 기본 캐시는 메모리에 두고 시작 시 한 번 스캔한다.
- 검색 실패나 TTL 만료 시 한 번 갱신한다.
- 디스크 캐시가 필요하면 `state` 아래에 버전이 있는 JSON으로 원자 저장한다.
- 실행 직전에는 경로와 파일 식별자를 다시 확인한다.
- 캐시에는 명령행, 창 제목, 사용자 문서 경로를 저장하지 않는다.

### 6.3 이름 해석

LLM은 사용자가 말한 `app` 문자열만 전달한다. 실제 후보 선택은 LLM이 아니라 로컬 해석기가 다음 순서로 수행한다.

1. `app_map`의 명시적 별칭 정확 일치
2. 카탈로그 표시 이름과 실행 파일 기본 이름의 정확 일치
3. 토큰 또는 접두사 일치
4. 승인된 최소 점수와 1위·2위 점수 차이를 모두 만족하는 유사도 일치

후보가 없거나 둘 이상이 비슷하면 실행하지 않고 후보를 사용자에게 보여준다. `카톡 → KakaoTalk`은 프로세스 이름의 부분 일치가 아니라 명시적 별칭 또는 카탈로그 이름 일치로 처리한다.

모호성 해소는 별도 사용자 선택 흐름으로 정의한다. 해석기는 화면에 표시할 제한된 후보와 일회성 `candidate_ticket_id`를 만들고, UI/CLI는 그 티켓 안의 항목 번호만 받아 선택한다. LLM에는 후보 ID·실행 경로·선택 명령을 새 도구 인자로 전달하지 않는다. 선택 직전과 실행 직전에 후보의 `app_id`, 정규 경로, `file_identity`를 다시 확인하며, 티켓 만료·카탈로그 변경·후보 불일치 시에는 처음부터 다시 해석한다.

### 6.4 권한과 실행

- 2026-09-09 사용자 요구에 따라 [앱 자동 탐색과 최초 실행 승인 저장](PROPOSAL_APP_DISCOVERY_AND_SAVED_APPROVAL.md)을 따른다. 이전 일회성 최초 승인 정책은 이 설계로 대체한다.
- `app_map` 등록 여부와 관계없이 저장된 사용자 실행 승인이 없으면 최초 실행을 `medium`으로 처리하고 앱 이름·정규 경로·이후 재질문하지 않는다는 안내를 표시한다.
- 사용자가 허용하면 해당 사용자·경로·exe 해시에 묶인 실행 권한을 저장한다. 동일 앱은 재시작 후에도 추가 승인 없이 실행한다. 거절·취소는 저장하지 않는다.
- 저장된 실행 권한은 종료·강제 종료 권한을 포함하지 않는다. 실행 파일 내용이나 경로가 변경되면 재승인을 요구하며 사용자가 허용을 취소할 수 있어야 한다.
- 셸 문자열을 만들지 않고 검증된 실행 대상만 배열 또는 Windows 실행 API에 전달한다.
- 실행 파일이 승인 이후 바뀌면 파일 식별자를 포함한 정규화 인자와 승인 해시 재평가에서 거부한다.

---

## 7. Gate C와 Gate D 설계

2026-09-09 사용자 요청에 따른 정적 카카오톡 종료 구현은
[카카오톡 종료 결정](KAKAOTALK_CLOSE.md)을 따른다. 이 구현은 범용 동적 탐색 게이트와
별도로 지원하며, 아래 동적 카탈로그 전체 완료를 의미하지 않는다.

### 7.1 프로세스와 창 탐색

프로세스 탐색에 `psutil`을 채택하면 이는 `benchmark` extra가 아닌 제품 런타임 의존성이어야 하며 `pyproject.toml`, `requirements.txt`, `requirements.lock`을 같은 변경에서 갱신한다. 채택하지 않으면 같은 정보를 제공하는 Windows API 어댑터를 사용한다. 창 열거와 정상 종료 요청은 Windows API를 별도 어댑터 뒤에 둔다. 테스트에서는 이 어댑터를 대체해 실제 사용자 앱을 종료하지 않는다.

탐색기는 기본적으로 `pid`, 생성 시각, 정규 실행 파일 경로, 소유자, 세션 ID, 최상위 창 핸들만 수집한다. `cmdline`은 기본 수집 대상에서 제외한다. 창 제목은 일치 계산에만 사용하고 원문을 로그나 LLM 입력에 남기지 않는다.

종료 후보는 다음 조건을 모두 만족해야 한다.

- 현재 사용자 소유
- 현재 대화형 세션에 속함
- 검증 가능한 실행 파일 경로 또는 등록된 앱 식별자를 가짐
- 시스템 서비스, 보호 프로세스, Jarvis 실행 트리와 일치하지 않음
- 이름 해석 결과가 하나의 앱으로 확정됨

### 7.2 정상 종료

일반적인 "닫아줘"와 "꺼줘"는 `medium` 위험의 정상 종료 요청으로 해석한다.

1. 대상 최상위 창에 비차단 `PostMessageW(WM_CLOSE)`를 보낸다. 임의 창 코드가 Jarvis를 멈추게 할 수 있는 동기 `SendMessage`는 사용하지 않는다.
2. 제한 시간 동안 종료 또는 저장 확인 창을 기다린다.
3. 종료되지 않으면 강제 종료하지 않고 상태를 사용자에게 알린다.

정상 종료는 저장 확인 UI를 표시할 수 있으므로 성공을 "메시지를 보냈다"가 아니라 대상 창이나 루트 프로세스가 실제로 종료되었는지로 판정한다.

### 7.3 강제 종료

강제 종료는 별도 Gate D로 구현한다.

- 사용자가 원래 요청에서 "강제 종료"를 명시한 경우에만 `force=true`를 허용한다. 모델이 임의로 추가한 `force=true`는 거부한다.
- `force`가 생략되면 Safety Gate 정규화 결과에 반드시 `force=false`, `close_mode="normal"`을 넣는다. `force=true`이면 `close_mode="force"`와 정확한 대상 집합을 해시에 넣고 위험도를 `high`로 승격한다.
- 위험도는 `high`이며 텍스트 확인 문구가 필요하다. 음성 채널에서 바로 승인할 수 없다.
- 이미지 이름이 아니라 승인된 정확한 PID 집합만 종료한다.
- 승인 화면에는 앱 이름, 실행 파일 경로, 창 수, 프로세스 수, 종료 방식을 표시한다.
- 승인 후 실행 직전에 각 PID의 생성 시각과 실행 파일 식별자를 다시 확인한다.
- 대상이 달라졌거나 일부 항목을 확인할 수 없으면 전체 요청을 거부한다.

### 7.4 보호 정책

블랙리스트 하나에 의존하지 않는다. 다음 통제를 함께 사용한다.

1. 서비스, 비대화형 세션, 다른 사용자, 상승된 프로세스는 기본 거부한다.
2. Windows 핵심 프로세스는 이름과 시스템 경로를 함께 확인해 `forbidden`으로 분류한다.
3. Jarvis 현재 PID, 부모 프로세스, 관리 중인 자식 프로세스를 실행 시점의 PID와 생성 시각으로 보호한다.
4. Ollama 보호가 필요하면 모든 `ollama.exe`를 막는 대신 Jarvis가 사용하는 인스턴스를 식별한다.
5. `explorer.exe` 프로세스를 종료하지 않는다. 폴더 창 닫기가 필요하면 해당 창 핸들에만 정상 종료를 요청한다.
6. 프로세스 정보 조회 권한이 없거나 식별이 불완전하면 거부한다.

`python.exe` 전체를 금지하면 사용자가 직접 실행한 Python 앱까지 닫을 수 없고, 파일명만 바꾼 프로세스를 식별하지 못한다. 따라서 이름 목록은 보조 통제이며 프로세스 정체성과 세션 경계가 주 통제여야 한다.

---

## 8. 인터페이스와 스키마 변경

현재 `open_app`과 `close_app`의 인자는 `app`이다. 동적 기능도 같은 이름을 유지해 기존 명령, 테스트, 감사 로그와 호환한다.

### 8.1 `open_app`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["app"],
  "properties": {
    "app": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    }
  }
}
```

### 8.2 `close_app`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["app"],
  "properties": {
    "app": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128
    },
    "force": {
      "type": "boolean",
      "default": false
    }
  }
}
```

동적 탐색이 꺼져 있으면 현재처럼 `app`에 `app_map` 열거값을 사용한다. 동적 탐색이 켜진 경우 문자열 스키마를 사용하고 Safety Gate가 로컬 카탈로그를 통해 정규화한다. `minLength`와 `maxLength`는 JSON Schema 설명에만 두지 않고 공용 `validate_tool_args`에서 실제 검증한다. `default`도 검증기가 자동 적용한다고 가정하지 않으며, 정규화 단계에서 `force=false`를 명시한다.

정규화된 `close_app` 인자는 최소한 다음 값에 승인 티켓을 묶어야 한다.

```text
app_id
canonical_executable_path
close_mode
targets[] = {pid, process_created_at, file_identity, window_handles[]}
```

Gate C/D에서는 `proc_terminate`를 `proc_spawn`과 구분하는 필수 capability로 추가한다. `scripts/app/config/models.py`, `scripts/app/tools/base.py`, `DESIGN.md`, `SCHEMAS.md`, 설정 예제와 정책 테스트를 같은 변경에서 수정한다. 정상 종료와 강제 종료 구현은 이 capability 없이 등록되거나 실행될 수 없다.

`ToolDefinition`의 동적 탐색 설정은 선택 필드로 추가하고 기존 `app_map`을 유지한다. 카탈로그 자체는 기존 기억 DB migration을 요구하지 않는다. 영구 실행 승인 저장소는 [최초 승인 저장 설계](PROPOSAL_APP_DISCOVERY_AND_SAVED_APPROVAL.md)에 따라 별도의 버전·스키마를 정의한다. 디스크 카탈로그는 버전이 맞지 않으면 삭제하고 다시 만들 수 있는 파생 캐시이며 승인 기록과 분리한다.

---

## 9. 데이터와 권한

| 항목 | 처리 원칙 |
|------|-----------|
| 설치 앱 이름과 경로 | 로컬에서만 탐색하고 외부로 전송하지 않는다 |
| 실행 중 PID와 생성 시각 | 승인 바인딩과 실행 직전 재검증에만 사용한다 |
| 창 제목 | 로컬 일치 계산에만 사용하고 원문 로그와 LLM 입력에서 제외한다 |
| 명령행 | 기본적으로 수집하지 않는다 |
| 앱 카탈로그 캐시 | 필요한 최소 필드만 `state` 아래에 원자 저장하고 삭제 후 재생성 가능하게 한다 |
| 네트워크 | 새 외부 전송 없음. Ollama loopback 제한을 유지한다 |
| 권한 상승 | 사용하지 않는다. 현재 사용자 권한으로 확인할 수 없는 대상은 거부한다 |

---

## 10. 위협 모델 변경

| 제안 위협 ID | 위협 | 필수 통제 | 검증 |
|--------------|------|-----------|------|
| DAC-T01 | 대화나 인용문을 명령으로 오인해 도구 호출 | 부정 예제 평가, 원래 사용자 의도 확인, Safety Gate | 도구 비호출 평가셋 |
| DAC-T02 | 유사도 검색이 다른 앱을 선택 | 정확 일치 우선, 최소 점수와 점수 차이, 모호하면 중단 | 충돌 이름과 오타 데이터셋 |
| DAC-T03 | 악성 바로가기나 실행 파일 바꿔치기 | 바로가기 대상 검증, canonical path, 파일 식별자 재검증 | 링크 변조와 TOCTOU 테스트 |
| DAC-T04 | PID 재사용으로 승인과 다른 프로세스 종료 | PID와 생성 시각, 실행 파일 식별자, 종료 방식을 인자 해시에 포함 | 승인 후 대상 교체 테스트 |
| DAC-T05 | 광범위 강제 종료로 데이터 손실 | 정상 종료 우선, `/IM` 금지, 강제 종료 `high`, 정확한 PID만 사용 | 다중 동명이인과 승인 거부 테스트 |
| DAC-T06 | 시스템 또는 Jarvis 프로세스 종료 | 사용자·세션·경로·실행 트리 검증, 보호 정책, 확인 실패 시 거부 | 보호 대상 표 전체 테스트 |
| DAC-T07 | 창 제목과 명령행의 민감정보 노출 | LLM 미전송, 원문 미기록, 최소 메타데이터만 감사 | 로그 및 이벤트 개인정보 검사 |
| DAC-T08 | 모델이 한 번에 여러 부작용 호출 | 한 단계 한 도구 규칙, Ollama 파서·일반 루프·AgentRunner의 다중 호출 전체 거부 | 세 경로의 병렬 호출 응답 테스트 |
| DAC-T09 | 레거시 이미지명 종료가 보호 정책을 우회 | 기존 `/IM ... /T /F` 비활성화, `explorer` 정적 거부, Gate C 어댑터만 허용 | 레거시 설정·정적 별칭·`explorer` 거부 테스트 |
| DAC-T10 | 모호한 후보 선택의 재사용·변조 | 일회성 후보 티켓, LLM 비노출, 선택·실행 전 파일 정체성 재검증 | 만료·카탈로그 변경·후보 교체 테스트 |

승인 후 구현 단계에서 이 표를 [위협 모델](../reference/THREAT_MODEL.md)에 정식 ID로 옮기고 [추적표](../reference/TRACEABILITY.md)에 테스트를 연결한다.

---

## 11. 작업 계획

### 11.1 Gate A 작업

- [ ] 도구 호출 결정 ID를 `docs/00-start-here/DECISIONS.md`에 등록
- [x] `DESIGN.md`의 LLM 메시지와 응답 계약 수정
- [x] `scripts/app/llm/ollama_client.py`에 ToolSpec 직렬화, tool message 직렬화, tool call 파싱 구현
- [x] `scripts/app/orchestrator/loop.py`의 일반 대화 경로에 활성 도구 명세를 전달하고, 도구 결과 후속 호출 없이 반환하는 분기를 Gate A 활성화 시 제거
- [x] `scripts/app/orchestrator/agent.py`가 최초 `LLMResponse`의 실제 assistant 호출과 tool 결과 이력을 보존하도록 수정
- [x] Ollama 파서·일반 대화 루프·AgentRunner 모두에서 다중 호출, 알 수 없는 도구, 잘못된 인자 응답을 실행 전에 전체 거부
- [x] Ollama 직렬화가 assistant `tool_calls`와 tool `tool_name`을 보존하고 내부 `tool_call_id`를 전송하지 않는지 검증
- [ ] 실제 `qwen3.5:9b` 평가와 기존 Phase 1~8 회귀 테스트 실행
- [ ] 평가 통과 전에는 한국어 정규식 폴백 유지

구현 항목은 결정론적 단위·통합 테스트로 검증했다. 출시 활성화에는 아직 결정 ID, 실제
`qwen3.5:9b` 평가, 전체 Phase 1~8 회귀가 남아 있으므로 기본 플래그는 `false`로 유지한다.

### 11.2 Gate B 작업

- [x] D020: `dynamic_discovery_enabled`·TTL 300초·상한 2000건·정확 일치 정책 확정
- [x] Windows 앱 카탈로그와 이름 정규화 모듈 구현
- [x] 시작 메뉴 바로가기와 App Paths 검증 어댑터 구현
- [x] 인메모리 캐시, TTL, 실패 시 갱신, 실행 직전 재검증 구현
- [x] `app_map` 또는 동적 카탈로그 정책을 조건부로 요구하도록 설정 검증, `open_app` 스키마와 Safety Gate를 정적 및 동적 모드에 맞게 수정
- [x] 최초 실행 승인·영구 실행 권한 저장·조회·취소와 감사 표시 구현
- [x] 모호한 후보의 일회성 선택 티켓, UI/CLI 선택, 재검증과 감사 흐름 구현
- [ ] 정량 이름 해석 평가와 보안 테스트 통과

### 11.3 Gate C와 Gate D 작업

- [ ] 레거시 `/IM ... /T /F` 종료 경로를 기본 비활성화하고, 모든 정적·동적 `explorer.exe` 종료를 거부
- [ ] 정상 종료와 강제 종료의 별도 결정 ID, `proc_terminate` capability, 런타임 프로세스 탐색 의존성 확정
- [ ] 프로세스·창 탐색 어댑터 구현
- [ ] 동일 사용자·동일 세션·대화형 창 필터 구현
- [ ] 비차단 `PostMessageW(WM_CLOSE)` 정상 종료와 실제 종료 확인 구현
- [ ] 정확한 PID 기반 강제 종료, 원래 사용자 요청의 명시성 검증, `force` 정규화·`high` 승격을 별도 기능 플래그로 구현
- [ ] PID 생성 시각과 파일 식별자의 승인 바인딩 및 재검증 구현
- [ ] 보호 프로세스 정책과 개인정보 최소 수집 적용
- [ ] [기존 `close_app` 제안](PROPOSAL_CLOSE_APP.md)을 이 문서에 의해 대체됨으로 표시하고 레거시 구현 예시를 배포 설계로 사용하지 못하게 정리

### 11.4 동기화할 기준 문서

제안이 승인되면 [문서 변경 규칙](../reference/DOCUMENTATION_RULES.md)의 순서대로 다음 문서를 같은 변경에서 갱신한다.

- `PLAN.md`: Post-v1 범위와 릴리스 게이트
- `DESIGN.md`: 메시지 계약, 앱 카탈로그, 프로세스 제어 경계
- `SCHEMAS.md`: ToolSpec, Message, `tools.yaml`, 캐시 스키마
- `TESTING.md`: 실제 모델 평가와 Windows 보안 테스트
- `docs/00-start-here/DECISIONS.md`: 미정 결정 세 건 이상
- `docs/reference/THREAT_MODEL.md`: 신규 위협과 잔여 위험
- `docs/reference/TRACEABILITY.md`: 요구사항과 테스트 연결
- `docs/post-v1/README.md`: 각 게이트의 상태와 링크

---

## 12. 자동 테스트와 정량 성공 기준

평가셋은 긍정 명령뿐 아니라 부정문, 질문, 인용문, 과거형, 모호한 앱 이름, 외부 문서의 명령문을 포함한다. 실제 모델 평가는 결정론적 단위 테스트와 분리해 느린 테스트로 실행한다.

| 영역 | 성공 기준 |
|------|-----------|
| 지원 의도 도구 선택 | 한국어 평가셋에서 도구명과 인자 완전 일치 95% 이상 |
| 비명령 발화 | 도구 오호출 1% 이하, 부작용 도구의 미승인 실행 0건 |
| 비정상 Ollama 응답 | 잘못된 구조, 다중 호출, 미등록 도구가 실행된 사례 0건 |
| 도구 이력 왕복 | assistant `tool_calls`와 tool `tool_name` 이력이 일반 루프·에이전트 모두에서 손실된 사례 0건 |
| 명시적 명령 회귀 | 지원하는 슬래시 명령 성공률 100% |
| 정확 이름과 등록 별칭 | 준비된 Windows 앱 데이터셋 해석 성공률 100% |
| 유사도 이름 | 오타 데이터셋 해석 성공률 95% 이상, 모호한 후보 자동 선택 0건 |
| 보호 대상 | 시스템·다른 사용자·Jarvis 실행 트리 종료 성공 0건 |
| 레거시 종료 차단 | `/IM ... /T /F` 실행 및 `explorer.exe` 종료 성공 0건 |
| 승인 바인딩 | 승인 후 PID 재사용, 경로 변경, 종료 방식 변경 시 실행 0건 |
| 종료 범위 | 승인 화면에 없는 PID 또는 창 종료 0건 |
| 개인정보 | 창 제목과 명령행 원문이 LLM 요청·이벤트·감사 로그에 남은 사례 0건 |
| 성능 | 1,000개 카탈로그 cold scan p95 2초 이하, warm lookup p95 50ms 이하 |
| 회귀 | 기존 Phase 1~8 테스트 전부 통과 |

권장 테스트 파일은 다음과 같다.

```text
scripts/tests/unit/test_ollama_tool_calling.py
scripts/tests/unit/test_app_catalog.py
scripts/tests/unit/test_app_name_resolver.py
scripts/tests/unit/test_process_resolver.py
scripts/tests/integration/test_native_tool_loop.py
scripts/tests/integration/test_dynamic_open_app.py
scripts/tests/integration/test_dynamic_close_app.py
scripts/tests/security/test_dynamic_app_control.py
scripts/tests/slow/test_qwen_tool_calling_eval.py
```

---

## 13. 롤백

- Gate A를 끄면 Ollama에 도구 명세와 tool 메시지를 보내지 않고 슬래시 명령 및 임시 한국어 폴백을 사용한다.
- Gate B의 동적 탐색을 끄면 `open_app`은 `app_map` 열거값만 해석한다. 최초 실행 승인 정책과 저장된 권한은 유지한다. 영구 승인 기능을 끄면 매 실행 승인으로 돌아가며 자동 허용으로 되돌리지 않는다.
- Gate C를 끄면 동적 `close_app`을 비활성화한다. 기본 종료 기능을 유지하려면 Gate C 보호 정책을 거친 정적 대상의 정상 종료만 별도 정책으로 허용한다. 레거시 `/IM ... /T /F` 경로는 다시 활성화하지 않는다.
- Gate D를 끄면 정상 종료만 남고 강제 종료는 항상 거부된다.
- 앱 카탈로그 캐시는 삭제 후 다시 만들 수 있어야 한다. 승인 저장소는 캐시 삭제와 독립적으로 보존하며 저장 스키마 롤백은 별도 절차로 검증한다.
- 기능 플래그를 끈 상태에서도 기존 Phase 1~8 회귀 테스트가 통과해야 한다.

---

## 14. 참고 자료

- [Ollama Tool calling](https://docs.ollama.com/capabilities/tool-calling)
- [Ollama Chat API](https://docs.ollama.com/api/chat)
- [Ollama qwen3.5 모델 태그](https://ollama.com/library/qwen3.5/tags)

Ollama 공식 문서는 `tools[].function.parameters`, 응답의 `message.tool_calls`, 후속 `tool` 역할 메시지를 지원한다. 현재 선택 모델인 `qwen3.5:9b`도 Ollama 모델 페이지에서 tools 지원 모델로 표시된다. 실제 배포 가능 여부는 문서 표기만으로 판단하지 않고 이 제안의 로컬 평가 게이트로 검증한다.

---

## 15. 결론

가장 먼저 해결할 문제는 도구 구현 부족이 아니라 Ollama 도구 호출 경로의 단절이다. Gate A를 먼저 완료하면 현재의 `ToolRegistry`, Safety Gate, 승인, 감사, AgentRunner를 자연어 요청에 연결할 수 있다.

동적 앱 제어는 그 다음 단계다. 발견된 앱을 곧바로 허용하거나 시스템 프로세스 이름 목록만으로 안전성을 판단해서는 안 된다. 발견과 권한을 분리하고, 모호한 매칭을 중단하며, 승인 대상을 실행 파일과 프로세스 생성 시각까지 묶어야 현재 보안 모델을 유지하면서 지원 앱 범위를 넓힐 수 있다.
