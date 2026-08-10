# Phase 6 — 보안 강화와 v0.5 릴리스 게이트

## 1. 목표

새 기능을 추가하지 않고 Phase 0~5의 신뢰 경계·도구·복구·백업을 공격 관점에서 검증한다. Critical/High 결함 0건과 실제 복원 성공이 v0.5 출시 조건이다.

이전: [Phase 5](../phase-05-agent/README.md) · 다음: [Phase 7](../phase-07-voice/README.md)

## 2. 진입 조건

- Phase 0~5 게이트 종료 코드 0
- `tests/data/tasks_eval.jsonl` 50건 준비
- [D007·D008](../00-start-here/DECISIONS.md) 확정
- 실제 백업 대상은 `D:\Jarvis`와 다른 물리 장치 또는 별도 보안 위치
- `run_skill`은 아직 disabled

## 3. 만들/변경할 파일

```text
scripts/{gate.py,backup.py}
tests/security/{test_audit_chain.py,test_secret_leakage.py,test_forbidden_actions.py}
tests/slow/{test_demo_loop.py,test_backup_restore.py}
docs/reference/THREAT_MODEL.md
docs/operations/README.md
```

## 4. 구현 순서

### P6-01 위협 모델 검토

[위협 모델](../reference/THREAT_MODEL.md)의 각 자산·경계·공격 시나리오를 코드와 연결한다.

필수 검토 대상:

- 사용자 입력과 음성 입력
- LLM 응답과 tool call
- 웹·문서·도구 출력
- API 전송
- 운영 설정·시크릿
- raw·SQLite·로그·백업
- 승인 UI와 ticket
- Windows 프로세스·경로·reparse point
- 패키지 공급망

각 위협은 예방 통제, 탐지 통제, 테스트, 잔여 위험을 가져야 한다. 테스트가 없는 High 위협은 릴리스 차단이다.

### P6-02 보안 코퍼스 완성

1. prompt injection, envelope escape, memory exfiltration 사례를 확장한다.
2. path corpus에 인코딩·대소문자·8.3 short name·ADS·UNC·장치 경로를 포함한다.
3. URL corpus에 IPv4 변형, IPv6, redirect-to-private, mixed-script IDN을 포함한다.
4. 승인 ticket의 만료·재사용·도구명 변경·args 변경을 검증한다.
5. forbidden 도구가 registry와 LLM tool schema 양쪽에 없는지 확인한다.

### P6-03 시크릿 유출 매트릭스

동일한 테스트 시크릿을 아래 모든 경로에 넣고 원문 0건을 검증한다.

| 경로 | 기대 |
|------|------|
| LLM API 메시지 | block 또는 mask |
| 검색 API query | block 또는 mask |
| events/raw/audit | mask, 감사 경로 필드 예외만 허용 |
| memory record | 저장 거부 또는 sensitivity 상승 |
| TTS | 낭독 거부 |
| 예외 detail/traceback | 원문 없음 |
| backup 산출물 목록·로그 | 원문 없음 |

탐지기의 false positive/false negative 샘플도 별도로 기록한다.

### P6-04 감사 로그 검증기

1. 날짜 파일을 seq 순서로 읽는다.
2. 파일 경계에서도 prev hash가 이어지는지 확인한다.
3. canonical JSON으로 entry hash를 재계산한다.
4. 누락·중복 seq, 변조 line, 깨진 마지막 줄을 구분해 보고한다.
5. 검증은 로그를 수정하지 않는다.

명령:

```powershell
python scripts\gate.py --verify-audit
```

### P6-05 백업

`backup.py create`의 순서:

1. 설정과 target 확인
2. SQLite online backup API로 일관된 DB 사본 생성
3. raw·config를 staging에 복사
4. manifest에 파일 경로·크기·SHA-256·schema version 기록
5. 선택한 도구로 암호화
6. 별도 target으로 복사
7. target의 암호화 파일 hash 재검증
8. 평문 staging 안전 삭제 또는 즉시 제거
9. `backup.result` 이벤트 기록 (복원은 `backup.restore`)

백업 암호는 인자·환경 변수·파일에 두지 않고 Credential Manager에서 읽는다.

### P6-06 복원

운영 루트 위에 바로 복원하지 않는다.

```powershell
python scripts\backup.py restore --archive <file> --target D:\JarvisRestoreTest
```

1. 새 target이 비어 있는지 확인
2. 복호화 후 manifest hash 확인
3. SQLite integrity check
4. schema version 확인 및 필요 시 migration 사전 보고
5. raw JSONL 유효성 검사
6. 설정 시크릿이 백업에 없는지 확인
7. 테스트 모드 앱으로 기억 검색 1회
8. 성공 후에만 복원 완료 보고

### P6-07 공급망·설정 검토

- lockfile hash 설치가 재현되는지 확인
- 미사용 의존성 제거
- 모든 example 설정을 운영 모델로 로드
- dev_mode=false에서 `.env`, kill hook, live test hook 비활성 확인
- tools default deny와 forbidden 항목 변경 불가 확인
- 설정·프롬프트·schema version을 릴리스 manifest에 기록

### P6-08 정량 게이트

```powershell
pytest -m "not allow_network"
python scripts\gate.py --verify-audit
python scripts\gate.py --report
python scripts\backup.py restore --archive <test-archive> --target <empty-test-root>
```

50개 복합 태스크 중 95% 이상, 금지 동작 0건, 중복 부작용 0건이어야 한다.

## 5. 결함 등급

| 등급 | 예 | 릴리스 처리 |
|------|----|-------------|
| Critical | 승인 없이 forbidden 실행, 시크릿 외부 전송 | 즉시 차단 |
| High | sandbox 우회, ticket 재사용, 복원 불가 | 차단 |
| Medium | 오류 메시지 부족, 제한 우회 불가한 DoS | 수정 계획과 기한 필요 |
| Low | 문서·표시 문제 | backlog 가능 |

## 6. 완료 게이트

- [ ] 전체 pytest slow 포함 통과
- [ ] Critical/High 0건
- [ ] 위협 모델의 모든 High 행에 자동 또는 수동 테스트 연결
- [ ] 감사 체인 변조 탐지 성공
- [ ] 별도 target 복원 후 기억 검색 성공
- [ ] 복합 태스크 50건 95% 이상
- [ ] v0.5 릴리스 manifest 작성

## 7. 이 Phase에서 하지 않는 것

- 보안 테스트를 통과시키기 위한 기능 삭제 은폐
- 운영 루트 직접 복원
- 평문 백업 보존
- Medium/High 결함을 문서화 없이 예외 처리
