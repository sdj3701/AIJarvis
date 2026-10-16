# 텍스트 PDF 추출·법령 구조 보존 적용 보고

2026-10-15. 사용자가 제공한 건축기본법 PDF의 실제 등록 경로를 구현하고 다시 검사했다.
시험용 Markdown 변환이 아닌 `DocumentIndexer.sync()`의 PDF 직접 등록 결과다.
설계 기준: [DESIGN 16.6~7](../DESIGN.md), 저장 계약: [SCHEMAS 13장](../SCHEMAS.md),
검증 규약: [TESTING RG-PDF](../TESTING.md), 결정: [D012](../00-start-here/DECISIONS.md).

최신 후속 변경은 아래 **7. .md 자동 저장**이다. 1~6절의 초기 시험 수치는 당시 기록으로 유지한다.

## 1. 무엇을 왜 바꿨는가

| 부분 | 변경 | 이유 |
|---|---|---|
| PDF 읽기 | 로컬 pdfplumber 0.11.9로 페이지별 텍스트와 좌표 추출 | PDF를 별도 수작업 변환 없이 등록하기 위해 |
| 여백 정리 | 반복 머리말·꼬리말 제거, 삭제 줄과 좌표 기록 | 페이지 번호·사이트 이름이 조문 중간에 섞이는 문제 방지 |
| 구조 보존 | 장/부칙·조를 제목으로, 항/호를 문단으로 보존 | 조문 범위를 유지하며 검색하고 출처를 추적하기 위해 |
| 재귀 청크 | recursive-context-v3, 빈 상위 제목은 다음 본문에 연결 | 내용 없는 제목 청크 제거; 기존 384/48토큰 제한 유지 |
| 저장 | 전체 Markdown·원본 해시·페이지 구간·조항 정보를 DB에 저장 | 검색 조각과 원본 페이지를 연결하고 재추출 비용 절감 |
| 검색/생성 | 제목·페이지·구조 전달, 위치 정보와 인용 본문 분리 | 이어지는 청크의 소속을 알려주고 출처 페이지를 표시하기 위해 |
| 오류/갱신 | 상한 검사, OCR 필요/읽기 실패 구분, 기존 세대 유지 | 일부 페이지가 빠졌는데 성공한 것처럼 처리하는 문제 방지 |

```text
문서 등록
  PDF → 페이지별 텍스트·좌표 → 반복 여백 제거 → 장·조·항·호를 가진 Markdown
  md/txt → UTF-8 텍스트
       → 문단 → 문장 → 어절 → 문자 순으로 필요한 부분만 재귀 분할
       → 제목·접두사를 포함한 토큰 상한 검사 → 임베딩 → 원문·출처·색인 세대 게시

사용자 질문
  질문/후속 문맥 준비 → 질문 전체 토큰화·임베딩 → 키워드/벡터 검색 → 재정렬
       → 본문+구조/페이지를 생성 모델에 전달 → 인용 검증 → 답변
```

청크는 모델이 문서를 읽을 범위를 정한다. 문서의 의미를 이해하는 계산 자체는 학습된 모델에서 수행한다.
질문은 PDF 추출이나 문서 청크 경로로 보내지 않는다.

## 2. 저장과 동작

- 원본 PDF는 그대로 둔다. 변환 Markdown은 `rag_document_content`에 저장한다.
  후속 `.md 자동 저장` 변경부터는 DB 옆 전용 폴더에도 내보내며 해당 폴더를 색인에서 제외한다.
- `rag_chunk_structure`의 페이지/조항 정보와 기존 provenance를 함께 저장한다.
  청크 start/end는 원본 PDF 바이트 위치가 아니라 저장된 Markdown의 문자 위치다.
- 같은 파일 해시와 파서 정책이면 재시작 후에도 기존 추출 결과를 재사용한다.
  파서·청크 정책 변경 시 한 번 재색인하며, 이후 내용이 같으면 재임베딩하지 않는다.
- PDF 최대 300쪽, 추출 2,000,000자 기본값을 추가했다. 기존 파일 크기 상한도 적용한다.
- `.pdf`를 supported_extensions에서 빼면 해당 파일을 색인 대상으로 삼지 않는다.
- 긴 조항은 여러 청크가 될 수 있다. 각 청크의 제목 경로/구조 메타데이터로 같은 조항임을 유지한다.
  장·조·항·호 전체를 매번 본문에 복사하지 않는다.

## 3. 제공 PDF 재시험

자료: `건축기본법(법률)(제21065호)(20251001).pdf`, 6쪽, 121,450바이트.
원본 SHA-256: `b25f8073d1ecbb1dc268f322593e444af5cdf524aa2beee2d8949206c248ce11`.

| 항목 | 이전 원시 추출 청크 | 이전 구조화 실험 | 이번 실제 PDF 등록 |
|---|---:|---:|---:|
| 청크 수 | 21 | 43 | **34** |
| 최대 토큰 | 383 | 371 | **381 / 제한 384** |
| 서로 다른 조항이 섞인 청크 | 16 | 0 | **0** |
| 머리말·꼬리말 포함 청크 | 8 | 0 | **0** |
| 제목만 있는 청크 | 구조 제목 미생성 | 7 | **0** |
| 검색 Hit@1 | 9/9 | 8/9 | **8/9** |
| 검색 Hit@3 | 9/9 | 9/9 | **9/9** |

이전 값은 [기존 시험 기록](../evaluations/pdf-chunk-test-20261015/REPORT.md)에 보존했다.
구조 보존이 개선됐다고 검색 첫 순위까지 개선됐다고 주장하지 않는다. 목적 질문의 정답 조항은 2위였다.
9질문은 이 PDF의 작은 점검 표본이며 실제 업무 정확도나 법률 답변의 정확성 보장이 아니다.

- 매 페이지 머리말·꼬리말 각 1줄, 총 **12줄 제거**.
- 제거 대상 외의 추출 텍스트는 레이아웃 공백과 추가 Markdown 기호를 제외하면 모두 일치한다.
  비교한 비공백 문자 7,844자. 모든 청크는 저장 Markdown의 정확한 연속 구간이다.
- 정리된 Markdown의 모든 문자 위치가 적어도 한 청크에 포함됐다. 제목 경계의 빈 줄이 다음 조항으로
  잘못 표시되던 메타데이터 문제도 수정하고 회귀 테스트를 추가했다.
- 제14조: **3~4쪽의 1~8호가 한 청크(230토큰)**로 유지된다.
- 제25조: **343토큰/249토큰 두 청크**, 각각 5~6쪽/6쪽이며 같은 조항 경로를 가진다.
- 반복 sync에서 변경 0건, 같은 활성 세대 유지. 원본 PDF 해시는 변경되지 않았다.

눈으로 확인할 결과:

- [추출된 Markdown](../../artifacts/evaluations/pdf-ingestion-20261015/final/extracted.md)
- [34개 청크와 토큰·페이지 미리보기](../../artifacts/evaluations/pdf-ingestion-20261015/final/chunks-preview.md)
- [검색 9질문·진단·소스 해시](../../artifacts/evaluations/pdf-ingestion-20261015/final/report.json)
- [원본 추출 텍스트 보존 검사](../../artifacts/evaluations/pdf-ingestion-20261015/extraction-integrity.json)
- [페이지 구간·삭제 기록](../../artifacts/evaluations/pdf-ingestion-20261015/final/document-metadata.json)

## 4. 개발 환경 적용

개발 설정 `D:\Jarvis-v2-dev\config\settings.yaml`에 `.pdf`를 활성화했다.
제공 파일은 개발 docs 폴더에 복사했으며 Downloads 원본은 수정하지 않았다.
DB와 설정 백업: `D:\Jarvis-v2-dev\backups\pdf-ingestion-20261015-023e79d1`.

기존 20문서와 PDF 1개, 총 **21문서·54청크**로 새 세대를 게시했다. 최대 381토큰,
미측정 청크 0개, 오류 0개, SQLite integrity_check=ok, 반복 등록 변경 0건이다.
개발 DB에서도 위원회 기능·운영 위탁 두 질문의 PDF 검색과 페이지 정보를 확인했다.
[적용 기록](../../artifacts/evaluations/pdf-ingestion-20261015/runtime-application.json),
[개발 DB 검색 기록](../../artifacts/evaluations/pdf-ingestion-20261015/runtime-search.json).

앱이 이미 실행 중이라면 다시 실행해야 새 코드와 설정을 읽는다. `/index`로 재검사할 수 있다.
프로토타입 `D:\Jarvis` 데이터와 정식 릴리스는 이번 적용 범위가 아니다.

## 5. 자동 검증과 재현

새 단위/통합 회귀는 파싱·상한·손상·OCR 필요·캐시·삭제·구조·제목 청크·출처 전달을 검사한다.
실제 로컬 모델 답변 기존 17개도 **17/17 통과**했다. [답변 보고](../../artifacts/evaluations/pdf-ingestion-20261015/answers/answer_report.json).
변경 Python 파일 Ruff 통과, RAG/research mypy 27소스 통과, pip check 통과.
전체 app Ruff에는 이번 변경 전부터 있던 fast_path.py/embeddings.py 오류 9개가 남아 있으며 해당 파일은 수정하지 않았다.
Phase 0~3·security 회귀는 **531 passed, 실패 0건**이다. [검증 요약](../../artifacts/evaluations/pdf-ingestion-20261015/validation-summary.json)에 세부 수치를 기록했다.
최초 회귀에서 새 의존성 pdfplumber가 기존 허용 목록에 없어 1건 실패했고, 계약 테스트의 목록을 갱신했다.
정식 릴리스 게이트·물리 UI/음성 인수 완료와 구분한다.

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m pytest -m '(phase0 or phase1 or phase2 or phase3 or security) and not allow_network'
.\.venv\Scripts\python.exe artifacts/evaluations/pdf-ingestion-20261015/validate_pdf.py artifacts/evaluations/pdf-ingestion-rerun
.\.venv\Scripts\python.exe -m app.rag.benchmark.answers --config-dir D:\Jarvis-v2-dev\config --dataset scripts/tests/data/rag_r3_answers.json --output-dir artifacts/evaluations/pdf-answers-rerun
```

PDF 시험 스크립트는 기존 증거를 덮지 않으므로 새 출력 디렉터리를 지정한다.
검색은 설치된 로컬 embeddinggemma와 재정렬 모델을 사용한다. 파싱/본문 정리는 LLM에 맡기지 않는다.
최초 실패 증거도 별도 보존했다. 최종 제공 PDF 결과는 `final/` 디렉터리를 기준으로 한다.

## 6. 남은 범위

스캔 PDF OCR은 아직 없다. 이미지뿐인 페이지는 명시적으로 OCR 필요 오류를 내며,
텍스트와 이미지가 혼합된 페이지의 이미지 속 내용을 자동 인식하지 않는다.
다단 편집·복잡한 표·특수 법령 표기는 추가 검증이 필요하다. 반복 여백 제거는 좌표와 반복성에 기반한
규칙이므로 다른 판형에서 검토가 필요하다. 줄바꿈으로 갈라진 한국어 단어를 추측해서 다시 쓰지는 않는다.

## 7. .md 자동 저장 (2026-10-15 후속)

사용자 요청: PDF에서 변환한 Markdown을 사람이 직접 열 수 있는 파일로도 보관하고 기존 DB 저장을 유지한다.

### 변경과 이유

| 변경 | 이유 |
|---|---|
| DB 게시 후 `markdown_exports.py`에서 UTF-8 `.md` 생성 | 검색에 사용한 원문과 확인용 파일을 정확하게 일치시키기 위해 |
| DB 옆 `{DB이름}-pdf-markdown/{doc_id}/{PDF이름}.md` | 원본을 수정하지 않고 동명 PDF가 서로 덮어쓰지 않게 하기 위해 |
| 전용 출력 폴더를 문서 스캔에서 제외 | docs_root에 출력 폴더가 포함돼도 PDF와 변환본이 중복 검색되지 않게 하기 위해 |
| 변경 없는 sync에서도 누락·변경 사본 복구 | 이미 등록한 PDF를 재파싱·재임베딩 없이 파일로 내보내기 위해 |
| 임시 파일 완전 기록 후 교체, 오류 기록 후 재시도 | 파일 잠금 등으로 저장하지 못해도 기존 파일과 DB 검색을 유지하기 위해 |
| 소유 기록 기반 변경·삭제 동기화 | 삭제된 PDF의 변환본을 정리하고 사용자가 추가한 파일은 보존하기 위해 |

파일은 전체 문서 Markdown이며 청크별 파일이 아니다. DB 저장 내용과 바이트 단위로 동일하므로 별도
설명 머리말이나 페이지 표시를 삽입하지 않는다. 조항·페이지 구간 메타데이터와 벡터도 기존대로 DB에 남긴다.
페이지 번호를 답변에 표시할 때는 이 메타데이터를 사용한다.
자동 생성 파일을 수정하면 다음 sync에서 DB 내용으로 복구하므로 별도 편집본은 다른 폴더에 저장한다.
새 YAML 키는 없다. 기존 `.pdf` 등록 설정과 `/index`·주기 동기화 경로를 그대로 사용한다.

### 제공 PDF 시험 및 개발 환경 적용

원본은 위와 동일한 6쪽 건축기본법 PDF이고 SHA-256은 변하지 않았다.
독립 DB 최초 등록과 개발 DB 소급 생성 두 경로를 실제 embeddinggemma로 확인했다.

| 검사 | 결과 |
|---|---|
| 생성 파일 크기 | 24,046바이트, UTF-8 |
| DB Markdown ↔ `.md` | 바이트 단위 일치 |
| 청크·벡터 | PDF 각각 34개 유지 |
| 최대 입력 토큰 | 381 / 384 |
| 원본 6쪽·여백 정리 | 6쪽 보존, 머리말·꼬리말 12줄 제거 기록 유지 |
| 조항·페이지 검색 | 계획 주기(2쪽), 위원 수(3쪽), 국회 보고 주기(4쪽), 모두 Top-1 |
| 반복 sync | 문서/세대 변경 0, 파일 수정 시각 유지 |
| 파일 삭제 후 복원 | 독립 DB 시험 통과, 재청킹·재임베딩 없음 |
| 개발 DB | 21문서·54청크 그대로, PDF 파일 사본 1개 추가 |
| 원본·DB 무결성 | 원본 해시 유지, SQLite integrity_check=ok |

개발 환경 생성 위치:
`D:\Jarvis-v2-dev\memory\jarvis-pdf-markdown\doc_01M4YZA84Q1C650VG9NJ9PC35S\건축기본법(법률)(제21065호)(20251001).md`.

- [독립 DB 실제 시험](../../artifacts/evaluations/pdf-markdown-20261015/isolated-verified/report.json)
- [개발 환경 적용·백업·파일 위치](../../artifacts/evaluations/pdf-markdown-20261015/runtime/report.json)
- [자동 회귀 결과](../../artifacts/evaluations/pdf-markdown-20261015/regression.xml)
- [실제 PDF 재현 스크립트](../../scripts/validate_pdf_markdown.py)

개발 DB와 semantic DB는 적용 전에 `artifacts/evaluations/pdf-markdown-20261015/runtime/backup`에 백업했다.
활성 색인 세대는 변경하지 않았다. 개발 소스 적용이며 EXE 재빌드·배포는 수행하지 않았다.
현재 실행 중인 소스 기반 앱은 재시작해야 새 코드를 읽는다.

자동 검증: 파일 저장·세대·PDF 관련 **25개 통과**, 이를 포함한 Phase 0~3·security 회귀
**552개 통과(254개 범위 밖 제외)**. 변경 파일 Ruff와 RAG 변경 모듈 3개 Mypy도 통과했다.

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m pytest scripts/tests/unit/test_markdown_exports.py scripts/tests/unit/test_index_generations.py scripts/tests/unit/test_document_parser.py --no-cov
.\.venv\Scripts\python.exe scripts/validate_pdf_markdown.py --pdf 'C:/Users/djthe/Downloads/건축기본법(법률)(제21065호)(20251001).pdf' --output artifacts/evaluations/pdf-markdown-rerun
```

결과 폴더는 기존 기록을 덮어쓰지 않도록 새 경로로 지정한다. 이번 실제 시험은 변환 파일·DB·벡터·검색
회귀를 확인한 것이며 답변 생성 정확도를 새로 평가한 것은 아니다. 스캔 OCR 등 6절의 범위는 그대로다.
