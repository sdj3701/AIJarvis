# Phase 5 — 멀티스텝 에이전트

## 1. 목표

검색 → 요약 → 파일 저장 → 폴더 열기처럼 여러 도구를 순서대로 실행한다. 각 단계는 저장·복구 가능해야 하고, 부작용 작업이 재시작 후 중복 실행되지 않아야 한다.

이전: [Phase 4](../phase-04-tools/README.md) · 다음: [Phase 6](../phase-06-security/README.md)

## 2. 진입 조건

- Phase 4 보안 테스트 전부 통과
- 단일 도구의 승인·감사·timeout이 안정적
- search/doc tool 결과가 `untrusted=true`
- DB migration과 복구 절차가 검증됨

## 3. 만들/변경할 파일

```text
app/orchestrator/{loop.py,tasks.py,recovery.py}
app/tools/impl/run_skill.py       # 기본 disabled, 선택적 골격만
tests/integration/{test_agent_multistep.py,test_recovery.py}
tests/data/tasks_eval.jsonl
```

## 4. 상태 모델

```text
Task: pending → running → succeeded | failed | cancelled
Step: pending → running → succeeded | failed | cancelled
```

한 step의 기록 순서:

```text
idempotency key 계산
→ pending 저장
→ 승인 필요 시 루프 중단
→ running 커밋
→ 도구 실행
→ succeeded/failed + 결과 커밋
```

`running`에서 프로세스가 죽으면 실제 부작용 여부를 확정할 수 없으므로 자동 재실행하지 않는다.

## 5. 구현 순서

### P5-01 TaskStore

1. [SCHEMAS 5장](../../SCHEMAS.md)의 tasks/task_steps를 구현한다.
2. `sha256(task_id + step_no + tool_name + args_hash)`로 idempotency key를 만든다.
3. 같은 key의 succeeded 단계는 기존 결과를 반환한다.
4. running 단계는 시작 시 사용자 검토 대상으로 표시한다.
5. 상태 전이와 결과를 한 트랜잭션으로 기록한다.

### P5-02 루프 확장

```text
Decide(tool 또는 final)
→ Validate
→ 승인/정책 처리
→ Act
→ Observe
→ 다음 step 또는 Final
```

1. `max_steps`, 단계 timeout, 전체 timeout을 적용한다.
2. 한 step당 tool call 하나만 허용한다.
3. 내부 추론 원문은 저장하지 않고 짧은 작업 계획·도구·결과만 기록한다.
4. 각 step 전에 원래 사용자 요청과의 관련성을 확인한다.
5. 외부 콘텐츠에서 새로 나타난 행동 목표는 사용자 의도로 승격하지 않는다.
6. 최종 응답에 완료·실패·미실행 단계를 구분한다.

### P5-03 승인 중단과 재개

1. 승인 필요 시 task와 현재 step을 pending으로 커밋한다.
2. `TurnOutcome.pending_approval`을 반환하고 루프를 끝낸다.
3. 승인 후 같은 task/step을 args hash로 다시 로드한다.
4. 거부·만료·불일치 시 해당 step을 cancelled 또는 failed로 끝낸다.
5. 승인 뒤 새로운 계획을 만들어 기존 ticket을 재사용하지 않는다.

### P5-04 재시도 정책

| 종류 | 자동 재시도 |
|------|-------------|
| web/doc search | 최대 설정 횟수, 가능 |
| fetch | 네트워크 일시 오류만 가능 |
| open_app/open_folder | 자동 재시도하지 않음 |
| create_file | 자동 재시도 금지 |
| run_skill | 자동 재시도 금지 |

LLM 재시도와 도구 재시도를 별도 카운터로 관리한다.

### P5-05 복구

1. 시작 시 running task와 step을 조회한다.
2. succeeded step은 재실행하지 않는다.
3. pending 승인 ticket은 재시작 후 무효로 표시하고 새 승인을 요구한다.
4. running 부작용 step은 changed path와 감사 로그를 보여주고 사용자가 완료/실패를 판정하게 한다.
5. 복구 행동을 `recovery.result`와 task history에 남긴다.

### P5-06 복합 태스크

첫 기준 태스크는 아래 하나로 고정한다.

```text
사용자: “주제를 검색해서 근거와 함께 요약하고 notes에 저장한 뒤 폴더를 열어줘.”
1. web_search
2. 필요 시 fetch_url
3. 근거 응답 작성
4. create_file (승인)
5. open_folder
6. 최종 결과
```

저장 파일명은 오케스트레이터가 임의 절대 경로로 만들지 않고 `root=notes`, 안전한 상대 파일명으로 제안한다.

### P5-07 run_skill 경계

v0.5에서는 기본 disabled를 유지한다. 골격을 만들 경우에도 다음이 모두 필요하다.

- registry 등록
- 파일 SHA-256 일치
- capability manifest
- text channel
- high typed confirmation
- 고정 interpreter·고정 cwd·최소 환경
- 자동 재시도 금지

조건을 만족해도 Phase 6 위협 모델 검토 전 운영 활성화하지 않는다.

## 6. 필수 테스트

- 기준 복합 태스크의 도구 순서·인자·최종 상태
- max_steps에서 안전 중지
- 전체 timeout에서 남은 step 미실행
- 검색 결과 명령이 새 부작용 step을 만들지 않음
- 승인 거부 후 다음 step 미실행
- 성공한 create_file 재개 시 중복 실행 없음
- running step 자동 재실행 없음
- task_eval 50건의 기대 changed path·상태 검증

## 7. 완료 게이트

### 2026-08-11 복구 검토 반영

- 승인 전 단계는 `pending`으로 커밋하고 ticket 소비 직전에만 `running`으로 전환한다.
- 단계 제한 시간은 LLM 호출 timeout의 상한으로 적용하고 초과 시 후속 단계를 실행하지 않는다.
- DuckDuckGo와 URL fetch에도 설정 timeout을 전달해 에이전트 전체 제한을 우회하지 못하게 한다.

```powershell
python scripts\gate.py --phase 5
```

- [x] 기준 복합 태스크 성공
- [x] 중복 부작용 0건
- [x] max_steps/timeout 안전 종료
- [x] 완료·실패·미실행 단계가 사용자에게 구분됨
- [x] 외부 콘텐츠가 새 task 목표를 만들지 않음
- [x] 50개 태스크 기준 데이터셋 준비 완료

## 8. 이 Phase에서 하지 않는 것

- 병렬 agent·multi-agent
- 승인 없는 백그라운드 부작용
- running step 자동 재실행
- LLM의 내부 추론 원문 저장
