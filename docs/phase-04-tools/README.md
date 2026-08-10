# Phase 4 — 안전한 PC 도구

## 1. 목표

화이트리스트에 등록된 앱·폴더·URL·텍스트 파일 생성만 수행한다. LLM 출력은 실행 요청일 뿐이며 스키마 검증, 정규화, 정책 판정, 승인, 감사 기록을 모두 통과해야 한다.

이전: [Phase 3](../phase-03-research/README.md) · 다음: [Phase 5](../phase-05-agent/README.md)

## 2. 진입 조건

- MVP/Phase 3 게이트 종료 코드 0
- 검색 도구 인터페이스와 registry가 안정화됨
- `tools.yaml`의 실제 앱 경로·sandbox root를 사용자가 검토함
- 등록되지 않은 도구가 LLM 스키마에 노출되지 않음

## 3. 만들 파일

```text
app/safety/{paths.py,gate.py,approval.py}
app/tools/runner.py
app/tools/impl/{open_app.py,open_folder.py,open_url.py,create_file.py}
app/telemetry/audit.py
tests/integration/test_tool_execution.py
tests/security/test_{path_traversal,reparse_points,url_schemes,approval_binding,forbidden_actions}.py
tests/data/paths/{traversal.txt,url_schemes.txt}
```

## 4. 실행 파이프라인

```text
LLM ToolCall
→ registry 조회
→ JSON Schema 검증
→ SafetyGate 정규화·위험도 판정
→ 필요 시 승인 대기로 TurnOutcome 반환
→ 승인 ticket 발급
→ 실행 직전 재평가·args_hash 비교·ticket 소진
→ audit intent flush
→ 제한된 실행
→ audit result flush
→ ToolResult 반환
```

승인 UI와 실행 코드는 직접 연결하지 않는다. 승인 대기는 값으로 저장하고 오케스트레이터가 재개한다.

## 5. 구현 순서

### P4-01 경로 정규화

1. 설정 경로와 도구 인자 경로 함수를 분리한다.
2. 도구는 root enum + relative path만 받는다.
3. 환경 변수, 절대 경로, UNC, 장치 경로, NTFS ADS, Windows 예약어, 끝 공백·점을 거부한다.
4. 각 중간 요소의 reparse point를 검사한다.
5. `commonpath`를 대소문자 무시로 비교한다.
6. 허용/금지 확장자를 최종 경로에 적용한다.

계약: [DESIGN 11.4](../../DESIGN.md), [tools.example.yaml](../../config/tools.example.yaml)

### P4-02 Safety Gate

1. [DESIGN 5.4](../../DESIGN.md)의 `Verdict`를 구현한다.
2. normalized args에서 정책 엔진이 display를 만든다.
3. 도구 기본 risk와 조건별 escalation을 합친다.
4. forbidden 요청은 승인 여부와 관계없이 deny한다.
5. interactive=false에서 승인 필요 작업은 `ApprovalRequired`로 반환한다.

### P4-03 승인 ticket

1. ticket에 request, tool, args hash, risk, channel, TTL을 결합한다.
2. ticket은 1회용이고 프로세스 재시작 시 자동 무효다.
3. medium은 y/n, high는 고정 문구 입력을 요구한다.
4. voice channel은 high ticket을 발급하지 않는다.
5. 실행 직전에 call을 다시 정규화해 hash를 비교한다.

### P4-04 감사 로그

1. [SCHEMAS 3장](../../SCHEMAS.md)의 intent/result/denied 레코드를 쓴다.
2. intent를 실행 전에 flush한다.
3. 단조 seq와 이전 entry hash로 전체 날짜 파일을 연결한다.
4. 승인·거부·불일치도 이벤트와 감사 로그 양쪽에 남긴다. 스키마 검증 실패나 정책 거부처럼 실행 전에 끝난 요청은 `phase="denied"` 한 줄과 `cause`를 남긴다.
5. 일반 대화 내용은 감사 로그에 넣지 않는다.

한 번의 `execute`가 감사 로그에 아무 줄도 남기지 않는 경로가 있으면 안 된다. 보안 테스트가 거부 사유를 감사 로그에서 확인하기 때문이다.

### P4-05 Secure Tool Runner

0. Phase 3에서 전용 경로로 실행하던 `web_search`·`doc_search`·`fetch_url`도 이 Runner를 거치게 옮긴다. 도구 실행 경로가 두 개 남으면 정책·감사가 한쪽만 적용된다.
1. [DESIGN 5.6](../../DESIGN.md)의 8단계 순서를 그대로 구현한다. 거부로 끝나는 경로도 감사 로그 한 줄을 남긴다.
2. `shell=True`, `os.system`, 문자열 명령 조립을 금지한다.
3. 프로세스에는 최소 환경 변수와 고정 cwd만 전달한다.
4. timeout, 출력 크기, 동시 실행 수를 제한한다.
5. `managed_process`만 Windows Job Object로 자식 트리를 묶고 timeout에 전체 종료한다.
6. `detached_allowlisted`는 등록된 실행 파일을 시작한 뒤 PID를 기록하고 앱 프로세스를 유지한다.
7. 실제 changed path를 결과와 감사 로그에 기록한다.

### P4-06 개별 도구

| 도구 | 구현 규칙 | 기본 위험 |
|------|-----------|-----------|
| `open_app` | enum → tools.yaml 경로, 추가 인자 없음 | low |
| `open_folder` | 허용 root 아래 기존 폴더만 | low |
| `open_url` | http/https, URL 재검증, 미등록 도메인/쿼리 승격 | low/medium |
| `create_file` | 허용 확장자, 새 파일만 medium, overwrite high | medium/high |

실패를 성공 메시지로 바꾸지 않는다. `ToolResult.ok=false`와 구체적 오류 유형을 유지한다.

### P4-07 CLI 승인 흐름

1. `TurnOutcome.pending_approval`이 있으면 display를 그대로 보여준다.
2. 사용자가 거부하면 `approval.deny` 후 task를 미실행 상태로 종료한다.
3. 승인하면 ticket을 발급해 `resume_after_approval`에 전달한다.
4. 승인 대기 중 새 사용자 입력이 오면 이전 승인을 취소한다.
5. Ctrl+C와 timeout도 ticket을 폐기한다.

## 6. 필수 보안 테스트

- traversal 코퍼스 전부 거부
- junction/symlink sandbox 우회 거부
- `file:`, `javascript:`, 장치/사용자 정의 URL 거부
- loopback·사설 IP·자격증명 URL 거부
- mixed-script IDN 정책 검증
- 승인 후 인자·도구명 변경 시 mismatch
- ticket 재사용·만료 거부
- timeout 후 자식 프로세스 0개
- 금지 확장자 생성 0건
- forbidden 작업 실행 0건

## 7. 완료 게이트

```powershell
python scripts\gate.py --phase 4
pytest -m "phase4 and security"
```

- [ ] 허용 앱·폴더 작업 성공
- [ ] 비허용 앱·경로 요청 거부와 이유 표시
- [ ] medium/high 승인 동작 구분
- [ ] 승인 화면과 실제 인자 불일치 실행 0건
- [ ] audit intent/result 모두 존재하고 체인이 이어짐
- [ ] timeout 프로세스 트리 잔존 0건

## 8. 이 Phase에서 하지 않는 것

- 삭제·포맷·임의 셸·레지스트리·다운로드 실행
- `run_skill` 활성화
- 여러 도구를 한 요청에서 연쇄 실행
- UI가 정책 엔진 판정을 우회하는 예외 경로
