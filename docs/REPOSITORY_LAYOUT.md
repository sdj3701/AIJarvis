# 저장소 구조와 v2 main 전환

2026-10-16에 현재 v2 구현을 기준으로 문서·코드·결과물의 위치를 정리했다.
루트 README는 GitHub 탐색용 안내이고, 상세 개발 문서는 모두 이 docs 폴더에서 관리한다.

```text
Jarvis/
├── docs/                    개발 문서와 사람이 읽는 평가 보고서
│   ├── PROJECT.md           프로젝트 소개·사용법
│   ├── DESIGN.md            설계 기준
│   ├── PLAN.md              개발 계획
│   ├── SCHEMAS.md           데이터·도구 계약
│   ├── TESTING.md           검증 기준
│   ├── rag/                 PDF·청킹·임베딩·답변 품질 개발 기록
│   └── evaluations/         과거 평가의 설명 보고서
├── scripts/
│   ├── app/                 실행 패키지 (Python 모듈 이름은 app 유지)
│   ├── tests/               단위·통합·보안·장시간 테스트와 픽스처
│   ├── launchers/           Windows CLI·GUI·음성 실행 배치 파일
│   ├── packaging/           PyInstaller 설정
│   ├── portfolio/           영상 제작 도구
│   ├── archive/             과거 실험 스크립트·소스 스냅샷 (로컬 보관)
│   └── *.py                 초기화·백업·검증·모델 설정 도구
├── datasets/                평가 질문 데이터
├── artifacts/
│   ├── evaluations/         평가 수치·그래프·HTML·검증 결과
│   ├── gates/               기존 Phase 게이트 증적
│   └── portfolio-video/     영상 결과물 (로컬 보관)
├── config/                  배포 가능한 설정 예제
├── assets/                  아이콘 등 정적 자산
├── bin/                     로컬에서 빌드하는 실행 파일
├── local/                   백업·로그·임시 파일 (Git 제외)
├── AIJarvis/                기존 Git 앱의 경로 호환용 별도 체크아웃 (로컬 전용)
├── .venv/                   개발 Python 환경 (Git 제외)
├── pyproject.toml           패키지·테스트·품질 검사 설정
├── requirements.lock        고정 의존성과 해시
└── README.md                문서로 연결하는 짧은 진입점
```

## 실행과 개발

저장소 루트에서 다음을 실행한다. editable 설치가 `scripts/app`을 `app` 모듈로 연결하므로
기존 `python -m app`과 `from app...` import를 그대로 사용한다.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe scripts\bootstrap.py --help
.venv\Scripts\python.exe -m app --help
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check scripts/app scripts/tests
.venv\Scripts\python.exe -m mypy
```

선택 기능은 기존 선택 의존성과 모델 설정이 필요하다. 검색·재정렬·평가에는
`pip install -e ".[search,rerank,benchmark]"`, 음성에는 `pip install -e ".[voice]"`를 사용한다.
GUI는 `pip install -e ".[gui]"`로 설치하며 Windows WebView2 런타임도 필요하다.

GUI 실행은 `scripts/launchers/Jarvis_UI.bat`, CLI는 `Jarvis.bat`, 음성은 `Jarvis_Voice.bat`다.
각 배치 파일은 자신의 위치에서 저장소 루트를 계산한다. 네이티브 런처는
`python scripts/build_exe.py`로 `bin/Jarvis.exe`에 생성한다.
기존 루트 `Jarvis.exe`는 이 PC의 바로가기 호환을 위해 로컬에 보존한다.

## 파일과 기록의 구분

- 프롬프트 Markdown은 실행에 쓰이는 패키지 자산이므로 `scripts/app/orchestrator/prompts`에 둔다.
- 테스트용 Markdown·JSON은 개발 설명 문서가 아니라 픽스처이므로 `scripts/tests/data`에 둔다.
- PDF에서 추출한 Markdown·DB·벡터·대화 원본은 실행 데이터다. 개발 문서와 합치지 않는다.
- 과거 실험 스크립트와 소스 스냅샷은 `scripts/archive/evaluations`에 원본 그대로 보관한다.
  현재 실행·pytest·배포 패키지에는 포함하지 않으며, 이전 경로를 사용하는 역사 자료다.
- 과거 평가 JSON의 소스 경로·해시·측정값은 당시 실행 증거이므로 소급 수정하지 않는다.
  사람이 읽는 문서 링크는 새 경로로 갱신했다. 이번 폴더 정리는 답변 정답률 재평가가 아니다.
- Git에는 코드·개발 문서·설정 예제·평가 질문·선별한 결과만 올린다.
  실제 설정·DB·로그·모델·영상 원본·별도 체크아웃·유지보수 백업은 제외한다.
- 기존 운영 데이터 루트와 문서 인덱스는 이동하지 않는다. 폴더 정리 때문에 재색인할 필요는 없다.

## 변경 전후

| 이전 | 현재 |
|---|---|
| `app/` | `scripts/app/` |
| `tests/` | `scripts/tests/` |
| 루트 설계·계획·스키마·테스트 문서 | `docs/` |
| 루트 상세 README | `docs/PROJECT.md` |
| `docs/RAG_*.md` | `docs/rag/RAG_*.md` |
| `results/` | `artifacts/evaluations/` |
| `evaluation_queries.json` | `datasets/evaluation_queries.json` |
| 루트 배치 파일·PyInstaller spec | `scripts/launchers/`, `scripts/packaging/` |
| 임시 파일·로그 | `local/tmp/`, `local/logs/` |
| 중첩 `AIJarvis/` | 기존 위치 유지 (Git 앱 경로 호환, 상위 저장소의 Git 추적 제외) |

### 기존 Git 앱 경로 호환

정리 중 별도 체크아웃 `AIJarvis/`를 `local/archive/AIJarvis/`로 옮겼으나,
Git 앱이 이전 위치의 `.git/config`를 계속 참조해 파일을 찾지 못하는 오류가 발생했다.
2026-10-16에 해당 체크아웃을 원래 위치로 복구했으며, 미커밋 변경 7개와 Git 설정을 보존했다.
이동 후 앱이 생성한 불완전한 `.git/fork` 폴더는 `local/maintenance/`에 별도로 보관했다.

현재 개발·커밋·push 기준은 **`D:\Ai\Jarvis`의 `main`**이다.
`D:\Ai\Jarvis\AIJarvis`는 이전 작업을 보존한 독립 체크아웃이며 최신 v2 작업 경로가 아니다.
Git 앱에서도 최신 v2를 보려면 상위 `D:\Ai\Jarvis`를 저장소로 연다.
기존 체크아웃은 사용하는 앱의 저장소 경로를 전환하기 전까지 다시 이동하지 않는다.

Git 전환은 기존 main의 커밋 이력을 유지하는 fast-forward로 진행한다.
이전 main을 사용하는 prototype 체크아웃은 보관 브랜치로 전환하고, 현재 v2 체크아웃을 main으로 사용한다.

## 이번 정리의 검증

- 외부 API·GPU·관리자 권한 테스트 5개를 제외하고 812개 통과.
- 기존 구형 Sandbox 초기화 테스트 3개 파일을 현재 build_sandbox 계약에 맞춰 수정했고, 관련 9개 테스트도 통과했다.
- CLI·bootstrap 도움말, 네이티브 런처 빌드, wheel 빌드와 별도 경로에서의 패키지 import·프롬프트·SQL·UI 자산 확인을 통과했다.
- 문서 상대 링크와 JSON 예제를 검증했다.
- Ruff 경고는 정리 전 52개 / 정리 후 52개이며 이번 이동으로 추가된 경고는 0개다.
- 기존 음성·GUI 타입 검사 오류 7개는 남아 있다. 전체 정적 검사 통과나 정식 릴리스 완료로 표시하지 않는다.

[검증 수치](../artifacts/evaluations/repository-layout-20261016/validation.json) ·
[전체 테스트 결과](../artifacts/evaluations/repository-layout-20261016/pytest.xml)
