# 결정 기록

코드가 대신 결정해서는 안 되는 선택을 기록한다. 상태는 `decided`, `pending`, `superseded` 중 하나다. 결정을 바꾸면 기존 행을 수정하지 말고 새 ID를 추가하고 이전 행을 `superseded`로 바꾼다.

## 결정 목록

| ID | 상태 | 결정 | 현재 값 | 적용 시점 | 완료 조건 |
|----|------|------|---------|-----------|-----------|
| D001 | decided | 소스 경로 | `D:\Ai\Jarvis` | Phase 0 | 고정 |
| D002 | decided | 운영 데이터 경로 | `D:\Jarvis` | Phase 0 | 고정 |
| D003 | decided | 상태 저장 | JSONL + SQLite WAL/FULL | Phase 0 | DESIGN 9장 준수 |
| D004 | decided | 패키지 관리 | `venv`, `pip`, hash lockfile | Phase 0 | bootstrap 문서화 |
| D005 | pending | LLM 제공자 | `openai` 또는 `anthropic` | Phase 1 진입 전 | 제공자·모델 ID·단가 입력 |
| D006 | pending | 검색 제공자 | 미정 | Phase 3 진입 전 | API·비용·결과 스키마 확정 |
| D007 | pending | 백업 대상 | 미정 | Phase 6 진입 전 | 별도 장치/보안 위치 경로 확정 |
| D008 | pending | 백업 암호화 도구 | 7-Zip AES-256 또는 age | Phase 6 진입 전 | 설치·복원 자동화 방식 확정 |
| D009 | pending | TTS | edge-tts 또는 로컬 TTS | Phase 7 진입 전 | 개인정보·오프라인 요구 결정 |
| D010 | decided | 음성 호출 | push-to-talk | Phase 7 | 웨이크워드는 Phase 9 이후 |
| D011 | decided | 상주 시작 | autostart 기본 false | Phase 8 | 사용자 opt-in만 허용 |
| D012 | pending | PDF parser | 미정 | Phase 3 PDF 활성화 전 | 파서·라이선스·실패 처리 확정 |
| D013 | pending | Windows 패키징 | PyInstaller 또는 대안 | Phase 8 진입 전 | 단일 빌드 방식·재현 명령 확정 |
| D014 | pending | 트레이·전역 단축키 라이브러리 | 미정 | Phase 8 진입 전 | 권한·충돌·종료 동작 검증 |
| D015 | pending | 자동 시작 설치 방식 | 시작프로그램 바로가기 또는 설치 옵션 | Phase 8 진입 전 | 레지스트리 직접 수정 없이 opt-in 구현 |

## 결정 작성 양식

새 결정이 필요하면 아래 형식으로 이 문서에 추가한다.

```text
ID:
상태:
문제:
선택지:
결정:
이유:
영향 문서/설정:
재검토 조건:
결정 날짜:
```

## Phase 차단 규칙

- D005가 `pending`이면 Phase 1 구현을 시작하지 않는다.
- D006이 `pending`이면 Phase 3의 웹 검색 구현만 차단한다. 로컬 문서 RAG는 먼저 개발할 수 있다.
- D007·D008이 `pending`이면 Phase 6 릴리스 게이트를 통과시킬 수 없다.
- D009가 `pending`이면 Phase 7 TTS 구현을 시작하지 않는다. STT 사전 실험은 가능하다.
- D012가 `pending`이면 Phase 3에서 PDF 지원을 비활성화하고 `.md`·`.txt`만 제공한다.
- D013~D015가 `pending`이면 Phase 8 패키징·전역 단축키·자동 시작 구현을 시작하지 않는다.
