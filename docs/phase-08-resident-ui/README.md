# Phase 8 — 상주 UI와 패키징

## 1. 목표

터미널을 직접 열지 않고 트레이·전역 단축키로 Jarvis를 호출한다. 승인 대기와 마이크 상태를 숨기지 않고, Windows 재시작 뒤에도 데이터 손상 없이 복구 상태를 표시한다.

이전: [Phase 7](../phase-07-voice/README.md) · 다음: [운영과 릴리스](../operations/README.md)

## 2. 진입 조건

- Phase 7 게이트 통과
- [D013~D015](../00-start-here/DECISIONS.md) 확정
- CLI 경로에서 모든 기능·승인·복구가 동작
- UI가 Orchestrator 내부를 직접 호출하지 않고 공개 계약만 사용

## 3. 만들 파일

```text
app/ui/{base.py,tray.py,hotkey.py,single_instance.py,notifications.py}
scripts/build.ps1
tests/integration/test_ui_state.py
tests/slow/test_packaged_bootstrap.py
```

## 4. UI 상태 머신

```text
Starting → Idle
Idle → Listening → Transcribing → Thinking
Thinking → ApprovalWaiting | Acting | ShowingResult | Error
ApprovalWaiting → Acting | Idle
Acting → Thinking | ShowingResult | Error
ShowingResult → Idle
Error → Idle | ShuttingDown
```

허용되지 않은 전이는 로그를 남기고 무시한다. 동일 시점의 상태는 하나만 존재한다.

## 5. 구현 순서

### P8-01 UI 계약과 이벤트 브리지

1. Orchestrator의 `TurnOutcome`과 voice controller 상태를 UI event로 변환한다.
2. UI는 LLM·MemoryStore·ToolRunner를 직접 import하지 않는다.
3. 승인 요청에는 Verdict display와 risk만 전달한다.
4. UI thread와 작업 thread 사이에는 thread-safe queue를 사용한다.
5. 종료 이벤트는 새 작업 수락을 중단하고 진행 중 상태를 정리한다.

### P8-02 트레이

필수 메뉴:

- Jarvis 열기
- PTT 시작/중지
- 현재 상태
- 미완료 task 확인
- 자동 시작 설정
- 로그 폴더 열기
- 종료

트레이 아이콘이 사라져도 백그라운드 프로세스가 유령 상태로 남지 않게 한다.

### P8-03 전역 단축키

1. 기본 단축키 충돌을 감지한다.
2. 등록 실패 시 앱을 종료하지 않고 설정 화면에서 변경을 요청한다.
3. 두 번째 인스턴스가 단축키를 다시 등록하지 못하게 한다.
4. 키 반복 입력을 debounce한다.
5. text 창 호출과 PTT 단축키를 구분한다.

### P8-04 승인 UI

1. medium/high 위험, 정확한 대상, 예상 변경, 만료 시간을 표시한다.
2. display는 Safety Gate가 만든 값을 그대로 사용한다.
3. high는 text typed phrase 입력만 받는다.
4. 창 닫기·timeout·새 요청은 거부로 처리한다.
5. 승인 창을 background notification만으로 대체하지 않는다.

### P8-05 복구·알림

1. 시작 시 recovery가 끝날 때까지 일반 입력을 받지 않는다.
2. 미완료 session/task/running step을 구분해 표시한다.
3. 완료 알림에는 민감한 결과 본문을 넣지 않는다.
4. 오류 알림은 user_message만 보여주고 상세는 로그 링크로 제공한다.
5. 마이크 사용 중 indicator는 트레이와 입력 창 양쪽에 표시한다.

### P8-06 자동 시작

자동 시작은 사용자 opt-in이며 agent tool이 아니라 설치/UI 설정 기능이다.

- 레지스트리 직접 수정 금지 정책을 유지한다.
- 결정된 방식으로 시작프로그램 바로가기 또는 설치 옵션을 사용한다.
- enable/disable을 대칭적으로 제공한다.
- 제거 시 자동 시작 항목도 제거한다.
- 자동 시작 실패가 앱 수동 실행을 막지 않는다.

### P8-07 패키징

1. `scripts/build.ps1` 한 명령으로 재현 가능하게 빌드한다.
2. 앱 버전·schema version·prompt version·설정 template version을 manifest에 넣는다.
3. 시크릿·운영 설정·운영 DB·raw 로그는 패키지에 포함하지 않는다.
4. 새 Windows 사용자 프로필에서 bootstrap부터 테스트한다.
5. 기존 `D:\Jarvis`가 있으면 데이터를 덮어쓰지 않고 migration을 실행한다.
6. 이전 앱 버전으로 rollback할 때 DB schema 호환 여부를 먼저 검사한다.

## 6. 필수 테스트

- 상태 머신 허용/거부 전이
- 작업 중 UI 응답성과 중복 요청 차단
- 단축키 충돌·두 번째 인스턴스
- 승인 창 닫기=deny
- notification에 secret/PII 없음
- Windows 재시작 시 미완료 task 표시
- 패키지에 `.env`, config 실사본, DB, raw 없음
- 깨끗한 테스트 프로필에서 bootstrap·실행 성공

## 7. 완료 게이트

```powershell
python scripts\gate.py --phase 8
pytest tests\slow\test_packaged_bootstrap.py
```

- [ ] 단축키로 입력 창과 PTT 호출
- [ ] 단일 인스턴스·중복 단축키 차단
- [ ] 마이크 상태 항상 표시
- [ ] 승인 상태와 실제 실행 상태 일치
- [ ] Windows 재시작 뒤 복구 목록 표시
- [ ] 패키징된 앱에서 bootstrap·migration 성공
- [ ] v1 후보 manifest 작성

## 8. 이 Phase에서 하지 않는 것

- 화면 비전 기반 임의 클릭
- 숨겨진 상시 녹음
- UI 전용 정책 예외
- 운영 데이터를 설치 패키지에 포함

