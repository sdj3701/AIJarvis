# Jarvis v2

Windows에서 실행하는 로컬 AI 비서입니다. 문서 RAG, 근거·페이지 인용, 대화 기억,
도구 실행과 음성 인터페이스를 제공합니다.

- [프로젝트 소개·기능·사용법](docs/PROJECT.md)
- [개발 문서 시작점](docs/README.md)
- [폴더 구조·설치·실행](docs/REPOSITORY_LAYOUT.md)
- [RAG 답변 품질 개선과 평가 조건](docs/rag/RAG_ANSWER_QUALITY.md)

실행 코드는 `scripts/app`, 테스트는 `scripts/tests`, 개발 문서는 `docs`,
공유 가능한 평가 결과는 `artifacts/evaluations`에 있습니다.
실행 설정·문서·DB·모델은 같은 프로젝트의 `data` 폴더에 모으며 Git에서 제외합니다.
[기존 데이터 통합 기록](docs/DATA_CONSOLIDATION.md)을 참고하세요.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe scripts\bootstrap.py --help
.venv\Scripts\python.exe -m app --help
```

GUI·음성·검색 모델 설정은 [실행 안내](docs/REPOSITORY_LAYOUT.md)를 참고하세요.
실제 설정·DB·대화 기록·모델·임시 파일은 Git에 포함하지 않습니다.
