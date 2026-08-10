# 착수 안내

이 문서는 코드를 만들기 전에 한 번만 수행한다. 완료되지 않은 결정이 현재 Phase를 막으면 구현을 시작하지 않는다.

## 1. 목표

- 소스·운영·테스트 경로를 분리한다.
- 개발 도구와 Windows 환경을 확인한다.
- 제공자·비용·백업처럼 코드가 결정할 수 없는 항목을 기록한다.
- 기준 문서와 Phase 문서의 역할을 이해한다.

## 2. 사전 환경 확인

PowerShell에서 다음을 확인한다.

```powershell
python --version
git --version
nvidia-smi
Get-PSDrive D
```

요구 조건:

- Windows 10/11
- Python 3.11 이상
- `D:\Ai\Jarvis` 쓰기 가능
- `D:\Jarvis`를 생성할 권한과 최소 5GB 여유 공간
- Phase 7에서만 NVIDIA 드라이버·CUDA 호환성 필요

GPU 확인 실패는 Phase 0~6을 막지 않는다. Python 또는 D 드라이브 조건 실패는 Phase 0 진입을 막는다.

## 3. 경로 계약

| 용도 | 경로 | 규칙 |
|------|------|------|
| 소스 | `D:\Ai\Jarvis` | Git 관리 대상 |
| 운영 데이터 | `D:\Jarvis` | Git 관리 금지 |
| 설정 템플릿 | `D:\Ai\Jarvis\config` | 예제만 저장 |
| 운영 설정 | `D:\Jarvis\config` | bootstrap이 최초 복사, 이후 덮어쓰기 금지 |
| 개발 시크릿 | `D:\Ai\Jarvis\.env` | `dev_mode=true`에서만 사용, Git 제외 |
| 운영 시크릿 | Windows Credential Manager | 파일 저장 금지 |
| 테스트 | pytest `tmp_path` | `D:\Jarvis` 접근 금지 |

## 4. 읽어야 할 문서

1. [루트 README](../../README.md)
2. [PLAN 1~2장](../../PLAN.md) — 목표·비목표·릴리스 경계
3. [DESIGN 1~3장](../../DESIGN.md) — 설계 원칙·모듈·의존 규칙
4. [TESTING 1장](../../TESTING.md) — 테스트 원칙
5. [결정 기록](./DECISIONS.md)

## 5. 착수 체크리스트

- [x] 소스와 운영 데이터 경로의 역할을 이해했다.
- [x] 운영 데이터가 Git에 포함되지 않는다는 것을 확인했다.
- [x] Python 3.11+가 실행된다.
- [x] Phase 0에서 사용할 패키지 관리 방식을 `venv + pip + requirements.lock`으로 확정했다.
- [x] LLM·검색·백업의 미결정 값을 DECISIONS에 기록했다.
- [x] Phase를 건너뛰지 않고 게이트 종료 코드 0으로 완료를 판단하기로 했다.

완료 후 [Phase 0](../phase-00-foundation/README.md)으로 이동한다.
