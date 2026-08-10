# 운영·릴리스·장애 대응

이 문서는 v0.5 이후 실제 개인 데이터로 Jarvis를 운영할 때 사용한다. 개발 테스트에서는 운영 루트 대신 임시 경로를 사용한다.

## 1. 운영 원칙

- 운영 DB·raw·설정은 Git과 설치 패키지에 넣지 않는다.
- 문제 발생 시 쓰기 작업을 멈추고 원본을 보존한 뒤 복사본에서 조사한다.
- DB integrity 또는 감사 체인이 실패하면 PC 도구를 비활성화한다.
- 백업 성공이 아니라 **복원 성공**을 기준으로 본다.
- 시크릿 노출이 의심되면 로그 삭제보다 키 폐기를 먼저 한다.

## 2. 최초 설치

```powershell
python scripts\bootstrap.py
python scripts\gate.py --phase 0
python -m app
```

확인:

- `D:\Jarvis` 운영 트리 생성
- 설정 example의 최초 사본 생성
- 기존 파일 덮어쓰기 0건
- SQLite integrity 정상
- Credential Manager에 필요한 키 존재
- `app.start` 이벤트의 config hash 확인

## 3. 시작·정상 종료

시작 순서:

1. 단일 인스턴스 락
2. 설정·schema version 검증
3. tmp/quarantine 점검
4. SQLite integrity check
5. 미완료 세션·task 점검
6. 감사 로그 마지막 hash 확인
7. UI/CLI 입력 활성화

종료 순서:

1. 신규 요청 중단
2. 진행 중 low/idempotent 작업 완료 또는 취소
3. 승인 ticket 폐기
4. 체크포인트와 app.stop 기록
5. 오디오·프로세스·DB 종료
6. 단일 인스턴스 락 해제

강제 종료 뒤에는 다음 시작에서 복구 결과를 확인하기 전 같은 작업을 다시 지시하지 않는다.

## 4. 정기 운영

### 매일

```powershell
python scripts\gate.py --integrity
```

- DB integrity
- 미완료 task/running step
- 감사 체인
- quota·예산 80% 경고
- retention 작업 결과
- 최근 error 이벤트

### 매주

```powershell
python scripts\backup.py create
```

- 암호화 archive 생성
- 별도 target 복사와 hash 확인
- 오래된 사본 보존 개수 적용
- 평문 staging 잔여 0건 확인

### 매월

```powershell
python scripts\backup.py restore --archive <latest> --target <empty-test-root>
```

- 새 경로 복원
- integrity check
- 기억 검색 1회
- 설정 로드
- raw 유효성
- 복원 결과 기록

## 5. 업데이트

1. 정상 종료하고 백업을 만든다.
2. 릴리스 manifest와 현재 앱/schema/prompt/config version을 비교한다.
3. 새 코드를 별도 venv에 설치한다.
4. migration dry-run 결과를 확인한다.
5. 테스트 데이터 경로에서 전체 게이트를 실행한다.
6. 운영 DB의 추가 백업 사본을 만든다.
7. migration 후 앱을 한 번 시작하고 integrity를 확인한다.
8. 문제가 없을 때만 자동 시작을 다시 활성화한다.

## 6. 롤백

- 코드만 rollback: DB schema가 이전 코드와 호환될 때만 허용
- DB rollback: 업데이트 직전 백업을 **새 경로에 복원**하고 검증 후 data root를 전환
- 설정 rollback: 이전 설정의 schema version이 현재 코드와 맞을 때만 허용
- prompt rollback: prompt version과 모델 ID를 함께 기록

운영 DB 위에 이전 DB를 덮어쓰지 않는다. 실패 원인을 보존해야 한다.

## 7. 장애별 대응

### 설정 오류

증상: 시작 시 종료 코드 2.

1. 사용자 운영 설정을 보존한다.
2. example과 키 이름·schema version을 비교한다.
3. `default: deny`, privacy default deny를 완화해 우회하지 않는다.
4. 수정 후 config hash가 바뀐 이유를 기록한다.

### SQLite integrity 실패

증상: 종료 코드 5, 기억 검색 불가.

1. 앱과 자동 시작을 중단한다.
2. 손상 DB를 읽기 전용 사본으로 보존한다.
3. 최신 백업을 새 target에 복원한다.
4. 복원본 integrity와 기억 검색을 확인한다.
5. 복원본을 새 data root로 전환한다.

### 감사 체인 실패

1. PC 도구를 전부 disabled로 시작한다.
2. 끊긴 seq 전후 파일을 보존한다.
3. 로그 rotation·동시 실행·수동 수정 여부를 확인한다.
4. 원인이 밝혀지고 새 체인 시작점이 기록될 때까지 v0.5 기능을 재활성화하지 않는다.

### running step 발견

1. task, tool, args display, intent 로그, changed paths를 사용자에게 보여준다.
2. 자동 재실행하지 않는다.
3. 실제 결과를 확인해 succeeded/failed/cancelled 중 하나로 마감한다.
4. 필요하면 새로운 task로 다시 요청한다.

### API 장애·예산 초과

- 진행 중 로컬 저장을 완료한다.
- 신규 API 요청을 중단한다.
- 재시도 횟수 이후 사용자에게 원인과 미완료 단계를 표시한다.
- 예산을 자동으로 늘리지 않는다.

### 시크릿 노출 의심

1. 해당 키를 제공자에서 즉시 폐기·재발급한다.
2. PC 도구와 외부 전송을 비활성화한다.
3. events/raw/audit/memory/backup을 탐지 패턴으로 조사한다.
4. 노출 경로와 시간 범위를 기록한다.
5. 새 키를 Credential Manager에 저장한다.
6. 재현 테스트를 추가한 뒤 기능을 재활성화한다.

로그를 먼저 지우면 범위 조사가 불가능해지므로 키 폐기와 증거 보존이 우선이다.

## 8. 사용자 데이터 작업

| 작업 | 방법 | 주의 |
|------|------|------|
| 기억 조회 | `/memory list` | candidate/confirmed 구분 |
| 기억 삭제 | `/forget <id>` | tombstone과 인덱스 제거 확인 |
| 기억 내보내기 | `/memory export` | 민감도 필터와 저장 위치 승인 |
| raw 삭제 | retention 또는 전용 관리 명령 | 활성 세션 파일 삭제 금지 |
| 전체 초기화 | v1 자동 기능으로 제공하지 않음 | 백업 후 수동 절차 문서화 필요 |

## 9. v0.5 릴리스 체크리스트

- [ ] Phase 0~6 전체 게이트 통과
- [ ] Critical/High 결함 0건
- [ ] 복합 태스크 50건 95% 이상
- [ ] 암호화 백업·새 경로 복원 성공
- [ ] 감사 체인 검증 성공
- [ ] run_skill 활성 여부와 근거 기록
- [ ] 버전 manifest 보관

## 10. v1 릴리스 체크리스트

- [ ] v0.5 체크리스트 유지
- [ ] Phase 7~8 게이트 통과
- [ ] 깨끗한 Windows 프로필 설치 성공
- [ ] 마이크 indicator·음성 High 승인 차단 확인
- [ ] 재시작 복구·단축키 충돌 테스트
- [ ] 7일간 매일 integrity 기록
- [ ] 데이터 손상·금지 동작·시크릿 유출 0건

