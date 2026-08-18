# Phase 0 — 기반 구축

## 1. 목표

외부 API나 PC 도구 없이도 안전하게 시작·종료할 수 있는 빈 CLI 골격을 만든다. 설정 오류, 시크릿 노출, 중복 실행, 부분 파일을 이 단계에서 차단한다.

다음 문서: [Phase 1 — 대화](../phase-01-chat/README.md)

## 2. 진입 조건

- [착수 체크리스트](../00-start-here/README.md)를 완료했다.
- `D:\Ai\Jarvis`, `D:\Ai\Jarvis-prototype`, `D:\Jarvis-v2-dev`의 역할을 구분했다.
- Python 3.11+를 사용할 수 있다.
- [결정 D001~D004](../00-start-here/DECISIONS.md)가 `decided`다.

## 3. Phase 종료 시 동작

```powershell
python scripts\bootstrap.py
python -m app
```

첫 명령은 운영 트리와 설정 사본·SQLite를 멱등적으로 준비한다. 두 번째 명령은 설정을 검증하고 단일 인스턴스 락을 획득한 뒤 입력을 그대로 돌려주는 CLI를 실행한다. LLM 호출은 아직 없다.

## 4. 만들 파일

```text
pyproject.toml
requirements.lock
.gitignore
.env.example
scripts/bootstrap.py
scripts/gate.py
app/__init__.py
app/__main__.py
app/cli.py
app/wiring.py
app/config/{models.py,loader.py,secrets.py}
app/core/{clock.py,ids.py,context.py,atomic.py,canonical.py,errors.py,recovery.py}
app/telemetry/{events.py,masking.py}
app/ui/single_instance.py
app/memory/{schema.sql,migrations.py}
tests/unit/test_{config_loader,atomic,canonical_hash,masking,single_instance}.py
```

전체 목표 구조는 [DESIGN 2장](../../DESIGN.md)을 따른다. 이 목록 밖의 Phase 1+ 모듈은 만들지 않는다.

## 5. 구현 순서

### P0-01 프로젝트와 품질 도구

1. `pyproject.toml`에 패키지 정보, Python 하한, pytest 마커, ruff, mypy 설정을 작성한다.
2. `.venv`를 만들고 Phase 0 런타임·개발 의존성만 설치한다.
3. exact version과 hash를 가진 `requirements.lock`을 생성한다. 생성 extra는 `dev`만 사용한다.
4. `.gitignore`에 `.venv`, `.env`, 캐시, 빌드 결과와 운영 데이터 사본을 등록한다. `artifacts\gates\`는 게이트 증거이므로 **제외하지 않는다**.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip pip-tools
.\.venv\Scripts\python.exe -m piptools compile --allow-unsafe --extra=dev --generate-hashes --output-file=requirements.lock --strip-extras pyproject.toml
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

검증:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
```

### P0-02 설정 모델과 로더

1. `config/*.example.yaml`에 대응하는 Pydantic 모델을 만든다.
2. 모든 모델에 `extra="forbid"`를 적용한다.
3. 세 파일의 `schema_version`, 경로, 예산, 비율, `default: deny`를 검증한다.
4. `D:\Jarvis-v2-dev\config`가 없으면 bootstrap 전이라는 명확한 `ConfigError`를 낸다.
5. 세 설정을 정규 직렬화해 `config_hash`를 계산한다.

계약: [SCHEMAS 11장](../../SCHEMAS.md), [설정 템플릿](../../config)

필수 테스트:

- 알 수 없는 키 거부
- 상위 버전 거부
- `tools.default=allow` 거부
- data root 밖 write root 거부
- context 비율 합계 초과 거부
- example YAML 세 개 정상 로드

### P0-03 시크릿 로더

1. 운영 모드에서는 Windows Credential Manager만 읽는다.
2. `.env` 폴백은 `dev_mode=true`일 때만 허용하고, 사용 시 `secrets.dev_fallback` 이벤트를 남긴다.
3. 읽은 시크릿 값을 즉시 마스킹 필터에 등록한다.
4. 시크릿 값 자체가 예외·로그·`repr`에 들어가지 않게 한다.

이 단계에서는 LLM 키가 없어도 앱 골격이 실행돼야 한다. Phase 1에서 실제 키를 필수화한다.

### P0-04 공통 타입

1. `Clock`, `Sleeper`, `RandomSource`와 운영·테스트 구현을 작성한다.
2. `<prefix>_<ULID>` ID 생성기를 작성한다.
3. `RequestContext`와 `CancelToken`을 정의한다.
4. [DESIGN 6장](../../DESIGN.md)의 예외 계층과 종료 코드를 구현한다.
5. `canonical_json`과 도구명 포함 `args_hash`를 작성한다.

모듈 내부에서 현재 시간·난수·전역 설정을 직접 읽지 않는다.

### P0-05 데이터 트리와 SQLite 초기화

`bootstrap.py`는 다음 순서를 지킨다.

1. `D:\Jarvis-v2-dev` 하위 `config`, `memory/raw`, `memory/export`, `docs/notes`, `skills`, `state/quarantine`, `logs`, `models`, `backups` 생성
2. example 설정을 운영 설정으로 최초 1회 복사
3. 기존 설정은 덮어쓰지 않음
4. `memory/jarvis.sqlite3` 생성
5. [SCHEMAS 5장](../../SCHEMAS.md)의 DDL 적용 및 `meta.schema_version=1` 기록
6. 쓰기 권한·잔여 용량 확인
7. 수행/건너뜀/실패 항목을 요약

같은 명령을 두 번 실행해도 결과가 달라지지 않아야 한다.

DDL은 문서에서 아직 실행 검증된 적이 없다. 이 작업에서 다음을 함께 확인한다.

- SQLite 버전이 3.34 미만이면 FTS5 `trigram` 부재를 `ConfigError`로 알린다.
- 6개 트리거가 실제로 생성된다(`INSERT INTO records_fts(records_fts) VALUES('delete')` 형태의 조건부 delete 구문 포함).
- 레코드를 `candidate → confirmed → superseded → deleted` 순으로 전이시킨 뒤 `INSERT INTO records_fts(records_fts) VALUES('integrity-check')`가 통과한다.

트리거 구문에 오류가 있으면 Phase 2에서 발견하지 말고 여기서 발견해야 한다.

### P0-06 이벤트·마스킹

1. [SCHEMAS 2.1](../../SCHEMAS.md)의 이벤트 봉투를 구현한다.
2. append → flush → 설정에 따라 fsync 순서로 JSONL을 쓴다.
3. 기록 전 `PrivacyGate.for_log`에 해당하는 마스킹 함수를 통과시킨다.
4. 최소 `app.start`, `app.stop`, `error`, `recovery.start`, `recovery.result` 이벤트를 지원한다.
5. API 키·Bearer token·개인키·주민번호 테스트 문자열이 로그에 남지 않게 한다.

### P0-07 원자적 쓰기·복구·단일 인스턴스

1. 임시 파일 → flush → fsync → `os.replace`로 쓰는 `write_atomic` 구현
2. 시작 시 `*.tmp`와 깨진 JSONL 꼬리를 `state/quarantine`으로 이동 (`app.core.recovery`)
3. `state/jarvis.lock`을 `msvcrt.locking`으로 잠금
4. 두 번째 인스턴스는 사용자 메시지와 종료 코드 1로 끝냄
5. 모든 복구 결과를 이벤트로 기록

계약: [DESIGN 11장](../../DESIGN.md)

### P0-08 CLI와 조립

1. `wiring.py` 한 곳에서 설정·clock·ID·이벤트 라이터를 조립한다.
2. `__main__.py`는 인자 파싱 후 wiring과 CLI만 호출한다.
3. CLI는 입력, `/help`, `/bye`를 지원하고 일반 입력은 echo한다.
4. Ctrl+C는 정상 정리 후 종료 코드 130을 사용한다.
5. 스택 트레이스는 개발 모드에서만 화면에 보인다.

## 6. 구현 순서별 권장 커밋

| 커밋 | 범위 |
|------|------|
| 1 | pyproject, lockfile, gitignore |
| 2 | config 모델·로더·테스트 |
| 3 | core 타입·예외·canonical hash |
| 4 | bootstrap·SQLite DDL |
| 5 | telemetry·마스킹 |
| 6 | atomic·복구·single instance |
| 7 | CLI·wiring·Phase 게이트 |

## 7. 완료 게이트

```powershell
python scripts\gate.py --phase 0
```

- [ ] 종료 코드 0
- [ ] example 설정 세 개가 정상 로드됨
- [ ] `default: allow`와 알 수 없는 설정 키가 거부됨
- [ ] 테스트 로그에 시크릿 원문 0건
- [ ] bootstrap 두 번 실행 시 기존 운영 설정을 덮어쓰지 않음
- [ ] 두 번째 앱 인스턴스가 거부됨
- [ ] 부분 파일이 격리되고 `recovery.result`가 기록됨
- [ ] SQLite DDL·트리거가 적용되고 FTS `integrity-check`가 통과함
- [ ] `budget.on_exceed`를 다른 값으로 바꾸면 실행이 거부됨

## 8. 이 Phase에서 하지 않는 것

- 실제 LLM·검색 API 호출
- 기억 검색·세션 요약
- PC 앱·파일 도구 실행
- 음성·트레이 UI
