# 큰 흐름 세분화

[`FLOW.md`](../FLOW.md)의 성숙 단계를 **단계별로 쪼갠** 폴더다.  
여기에는 “왜 이 단계가 필요한지 / 무엇이 끝나면 다음인지”만 둔다.  
파일·테스트·게이트 명령의 단일 기준은 각 `docs/phase-*/README.md`다.

## 읽는 순서

```text
FLOW.md (전체 지도)
  → 현재 단계의 L*/G*/Ops 문서
  → 연결된 phase-*/README.md 로 구현
  → PROGRESS.md 에 상태·증거 기록
```

| 파일 | 단계 | 구현 문서 |
|------|------|-----------|
| [L0-foundation.md](./L0-foundation.md) | 빈 골격 | [phase-00](../phase-00-foundation/README.md) |
| [L1-chat.md](./L1-chat.md) | 말하는 챗봇 | [phase-01](../phase-01-chat/README.md) |
| [L2-memory.md](./L2-memory.md) | 기억하는 챗봇 | [phase-02](../phase-02-memory/README.md) |
| [L3-research.md](./L3-research.md) | 찾아주는 비서 (MVP) | [phase-03](../phase-03-research/README.md) |
| [L4-tools.md](./L4-tools.md) | 손 있는 비서 | [phase-04](../phase-04-tools/README.md) |
| [L5-agent.md](./L5-agent.md) | 일 시키는 에이전트 | [phase-05](../phase-05-agent/README.md) |
| [G6-security.md](./G6-security.md) | v0.5 보안 게이트 | [phase-06](../phase-06-security/README.md) |
| [L7-voice.md](./L7-voice.md) | 말하는 자비스 | [phase-07](../phase-07-voice/README.md) |
| [L8-resident-ui.md](./L8-resident-ui.md) | 상주형 비서 | [phase-08](../phase-08-resident-ui/README.md) |
| [Ops-operations.md](./Ops-operations.md) | 운영·안정화 | [operations](../operations/README.md) |

## 작성 규칙

- PLAN/DESIGN/SCHEMAS 내용을 길게 복사하지 않는다. 절 이름과 링크로 연결한다.
- 상태는 이 폴더에 쓰지 않는다. [`PROGRESS.md`](../PROGRESS.md)만 갱신한다.
- 작업 ID(`P6-01` 등)의 권위는 Phase 문서에 있다. 여기에는 요약만 둔다.
- 단계가 끝나면 “다음 문서” 링크만 확인하고 FLOW 표의 현재 위치를 PROGRESS와 맞춘다.
