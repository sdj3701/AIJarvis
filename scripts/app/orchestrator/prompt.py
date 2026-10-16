# 파이썬 공부 | scripts/app/orchestrator/prompt.py
# 시스템 지침, 기억, 대화 기록을 AI 입력으로 조합하고 길이를 조절합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Versioned Phase 1 prompt assembly with deterministic context compaction."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config.models import ContextSettings
from app.core.context import CancelToken
from app.core.errors import PromptTooLong
from app.llm.base import Message
from app.orchestrator.response_presenter import wants_detail
from app.orchestrator.rulebook import Rulebook, load_rulebook

# re.compile()의 반환값을 _VERSION_PATTERN에 대입합니다.
_VERSION_PATTERN = re.compile(r"^<!--\s*version:\s*([0-9]+)\s*-->$")
# 오른쪽 식을 계산한 값을 _DEFAULT_PROMPT_PATH에 대입합니다.
_DEFAULT_PROMPT_PATH = Path(__file__).with_name("prompts") / "system_core.md"


def merge_system_messages(messages: Sequence[Message]) -> tuple[Message, ...]:
    """Keep internal task contracts in the single system slot of local chat templates."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    return (Message("system", system), *(m for m in messages if m.role != "system"))


# TokenCounter: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class TokenCounter(Protocol):
    # count_tokens(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages.
    # 반환 타입 힌트: 정수(int).
    def count_tokens(self, messages: Sequence[Message]) -> int: ...


# PromptPlan: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class PromptPlan:
    # messages: tuple[Message, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    messages: tuple[Message, ...]
    # prompt_version: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    prompt_version: str
    # input_tokens: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    input_tokens: int
    # history_tokens: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    history_tokens: int
    # history_cap: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    history_cap: int
    # compressed: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    compressed: bool
    # compressed_turns: 정수(int) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    compressed_turns: int


# ExtractiveHistoryCompressor: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class ExtractiveHistoryCompressor:
    """Collapse old turns locally; no extra model request or external state is used."""

    # compress(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: turns.
    # 반환 타입 힌트: 문자열(str).
    def compress(self, turns: Sequence[Sequence[Message]]) -> str:
        # lines에 리스트(순서가 있고 수정 가능)을 대입합니다.
        lines = [f"[이전 대화 {len(turns)}턴 압축]"]
        # for 반복문: 대상의 항목을 하나씩 turn에 대입하며 아래 블록을 실행합니다.
        for turn in turns:
            # for 반복문: 대상의 항목을 하나씩 message에 대입하며 아래 블록을 실행합니다.
            for message in turn:
                # 오른쪽 식을 계산한 값을 label에 대입합니다.
                # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
                label = "사용자" if message.role == "user" else "자비스"
                # ' '.join()의 반환값을 content에 대입합니다.
                content = " ".join(message.content.split())
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(content) > 240.
                if len(content) > 240:
                    # 오른쪽 식을 계산한 값을 content에 대입합니다.
                    content = content[:237] + "..."
                # 리스트 끝에 항목 하나를 추가합니다.
                lines.append(f"{label}: {content}")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return "\n".join(lines)


# PromptAssembler: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class PromptAssembler:
    """Build system → compacted history → current-user messages in fixed order."""

    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: counter, context, prompt_path, compressor, rulebook.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(
        self,
        counter: TokenCounter,
        context: ContextSettings,
        *,
        prompt_path: Path = _DEFAULT_PROMPT_PATH,
        compressor: ExtractiveHistoryCompressor | None = None,
        rulebook: Rulebook | None = None,
    ) -> None:
        # 오른쪽 식을 계산한 값을 self._counter에 대입합니다.
        self._counter = counter
        # 오른쪽 식을 계산한 값을 self._context에 대입합니다.
        self._context = context
        # 언패킹: 오른쪽 결과를 순서대로 (self._system_text, self._version)에 나누어 담습니다.
        self._system_text, self._version = _load_prompt(prompt_path)
        # 오른쪽 식을 계산한 값을 self.rulebook에 대입합니다.
        self.rulebook = rulebook or load_rulebook()
        # 오른쪽 식을 계산한 값을 self._compressor에 대입합니다.
        self._compressor = compressor or ExtractiveHistoryCompressor()

    # prompt_version(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def prompt_version(self) -> str:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._version

    # build(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: current_user_text, history, cancel, confirmed_memory, candidate_memory, extra_system.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: PromptPlan.
    def build(
        self,
        *,
        current_user_text: str,
        history: Sequence[Message] = (),
        cancel: CancelToken | None = None,
        confirmed_memory: str | None = None,
        candidate_memory: str | None = None,
        extra_system: Sequence[str] = (),
        retrieved_context: str | None = None,
    ) -> PromptPlan:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(current_user_text, str) or not current_user_text.strip():
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("현재 사용자 발화는 비어 있을 수 없습니다")
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: cancel is not None.
        if cancel is not None:
            # cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
            cancel.raise_if_cancelled()

        # _history_turns()의 반환값을 turns에 대입합니다.
        turns = _history_turns(history)
        # Message()의 반환값을 system에 대입합니다.
        system = Message("system", self._system_text + "\n\n" + self.rulebook.system_text)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: wants_detail(current_user_text).
        if wants_detail(current_user_text):
            # Message()의 반환값을 system에 대입합니다.
            system = Message(
                "system", system.content + "\n이번 사용자 요청은 상세 설명 예외입니다."
            )
        # memory_messages에 리스트(순서가 있고 수정 가능)을 대입합니다.
        memory_messages: list[Message] = []
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: confirmed_memory.
        if confirmed_memory:
            # 리스트 끝에 항목 하나를 추가합니다.
            memory_messages.append(Message("system", confirmed_memory))
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: candidate_memory.
        if candidate_memory:
            # 리스트 끝에 항목 하나를 추가합니다.
            memory_messages.append(Message("system", candidate_memory))
        # 오른쪽 식을 계산한 값을 extra_messages에 대입합니다.
        # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
        extra_messages = [Message("system", block) for block in extra_system if block.strip()]
        # Message()의 반환값을 current에 대입합니다.
        current = Message("user", current_user_text)
        # self._count()의 반환값을 system_tokens에 대입합니다.
        system_tokens = self._count((system, *memory_messages, *extra_messages))
        # self._count()의 반환값을 current_tokens에 대입합니다.
        current_tokens = self._count((current,))
        # 오른쪽 식을 계산한 값을 fixed_tokens에 대입합니다.
        fixed_tokens = system_tokens + current_tokens + self._context.reserve_output_tokens
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: fixed_tokens >
        # self._context.max_input_tokens.
        if fixed_tokens > self._context.max_input_tokens:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PromptTooLong(
                "입력이 너무 깁니다. 내용을 나누어 다시 입력하세요.",
                {
                    "system_tokens": system_tokens,
                    "current_tokens": current_tokens,
                    "max_input_tokens": self._context.max_input_tokens,
                },
            )

        # 오른쪽 식을 계산한 값을 available에 대입합니다.
        available = (
            self._context.max_input_tokens
            - system_tokens
            - self._context.reserve_output_tokens
        )
        # int()의 반환값을 history_cap에 대입합니다.
        history_cap = int(available * self._context.history_share)
        # min()의 반환값을 protected_turn_count에 대입합니다.
        protected_turn_count = min(self._context.keep_recent_turns, len(turns))
        # 오른쪽 식을 계산한 값을 protected_turns에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        protected_turns = turns[-protected_turn_count:] if protected_turn_count else []
        # 오른쪽 식을 계산한 값을 old_turns에 대입합니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        old_turns = turns[:-protected_turn_count] if protected_turn_count else turns
        # tuple()의 반환값을 protected에 대입합니다.
        protected = tuple(message for turn in protected_turns for message in turn)
        # self._count()의 반환값을 protected_tokens에 대입합니다.
        protected_tokens = self._count(protected)
        # 오른쪽 식을 계산한 값을 remaining_total에 대입합니다.
        remaining_total = self._context.max_input_tokens - fixed_tokens - protected_tokens
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: remaining_total < 0.
        if remaining_total < 0:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PromptTooLong(
                "최근 대화와 현재 입력이 컨텍스트 한도를 넘었습니다. /clear 후 다시 입력하세요.",
                {
                    "protected_turns": protected_turn_count,
                    "protected_tokens": protected_tokens,
                    "max_input_tokens": self._context.max_input_tokens,
                },
            )

        # history_messages: tuple[Message, ...] 타입을 기대하는 필드입니다. 이 줄만으로 값이
        # 대입되지는 않습니다.
        history_messages: tuple[Message, ...]
        # Retrieved conversations are untrusted data and optional context. Drop
        # the block if it would crowd out the current input or protected history.
        retrieved_messages: tuple[Message, ...] = ()
        if retrieved_context:
            recall_message = Message("user", retrieved_context)
            recall_tokens = self._count((recall_message,))
            if recall_tokens <= remaining_total:
                retrieved_messages = (recall_message,)
                fixed_tokens += recall_tokens
                remaining_total -= recall_tokens
                history_cap = max(0, history_cap - recall_tokens)
        # compressed을 False(으)로 설정해 참/거짓 상태를 나타냅니다.
        compressed = False
        # compressed_turns에 숫자 등 고정된 값을 대입합니다.
        compressed_turns = 0
        # tuple()의 반환값을 full_history에 대입합니다.
        full_history = tuple(history)
        # self._count()의 반환값을 full_history_tokens에 대입합니다.
        full_history_tokens = self._count(full_history)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if full_history_tokens <= min(history_cap, self._context.max_input_tokens - fixed_tokens):
            # 오른쪽 식을 계산한 값을 history_messages에 대입합니다.
            history_messages = full_history
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # bool()의 반환값을 compressed에 대입합니다.
            compressed = bool(old_turns)
            # len()의 반환값을 compressed_turns에 대입합니다.
            compressed_turns = len(old_turns)
            # min()의 반환값을 summary_cap에 대입합니다.
            summary_cap = min(max(0, history_cap - protected_tokens), remaining_total)
            # self._summary_message()의 반환값을 summary에 대입합니다.
            summary = self._summary_message(old_turns, token_cap=summary_cap)
            # 오른쪽 식을 계산한 값을 history_messages에 대입합니다.
            history_messages = (() if summary is None else (summary,)) + protected

        # messages에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        messages = (system, *memory_messages, *extra_messages,
                    *retrieved_messages, *history_messages, current)
        # self._count()의 반환값을 input_tokens에 대입합니다.
        input_tokens = self._count(messages)
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if input_tokens + self._context.reserve_output_tokens > self._context.max_input_tokens:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PromptTooLong(
                "프롬프트가 컨텍스트 한도를 초과했습니다. /clear 후 다시 입력하세요."
            )
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: cancel is not None.
        if cancel is not None:
            # cancel.raise_if_cancelled()을 호출해 작업을 수행합니다.
            cancel.raise_if_cancelled()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return PromptPlan(
            messages=messages,
            prompt_version=self._version,
            input_tokens=input_tokens,
            history_tokens=self._count(history_messages),
            history_cap=history_cap,
            compressed=compressed,
            compressed_turns=compressed_turns,
        )

    # _summary_message(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: turns, token_cap.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: Message | None.
    def _summary_message(
        self,
        turns: Sequence[Sequence[Message]],
        *,
        token_cap: int,
    ) -> Message | None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not turns or token_cap <= 0.
        if not turns or token_cap <= 0:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # self._compressor.compress()의 반환값을 text에 대입합니다.
        text = self._compressor.compress(turns)
        # Message()의 반환값을 candidate에 대입합니다.
        candidate = Message("assistant", text)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._count((candidate,)) <=
        # token_cap.
        if self._count((candidate,)) <= token_cap:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return candidate

        # low에 숫자 등 고정된 값을 대입합니다.
        low = 0
        # len()의 반환값을 high에 대입합니다.
        high = len(text)
        # best을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        best: Message | None = None
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while low <= high:
            # 오른쪽 식을 계산한 값을 middle에 대입합니다.
            middle = (low + high) // 2
            # 오른쪽 식을 계산한 값을 suffix에 대입합니다.
            # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
            suffix = "..." if middle < len(text) else ""
            # Message()의 반환값을 attempt에 대입합니다.
            attempt = Message("assistant", text[:middle].rstrip() + suffix)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._count((attempt,)) <=
            # token_cap.
            if self._count((attempt,)) <= token_cap:
                # 오른쪽 식을 계산한 값을 best에 대입합니다.
                best = attempt
                # 오른쪽 식을 계산한 값을 low에 대입합니다.
                low = middle + 1
            # 앞선 조건이 거짓이면 이 블록을 실행합니다.
            else:
                # 오른쪽 식을 계산한 값을 high에 대입합니다.
                high = middle - 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return best if best is not None and best.content else None

    # _count(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: messages.
    # 반환 타입 힌트: 정수(int).
    def _count(self, messages: Sequence[Message]) -> int:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return self._counter.count_tokens(messages) if messages else 0


# _load_prompt(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: path.
# 반환 타입 힌트: tuple[str, str].
def _load_prompt(path: Path) -> tuple[str, str]:
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # Path(path).read_text()의 반환값을 text에 대입합니다.
        text = Path(path).read_text(encoding="utf-8")
    # (OSError, UnicodeError)를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except (OSError, UnicodeError) as error:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("시스템 프롬프트 파일을 읽을 수 없습니다") from error
    # text.splitlines()의 반환값을 lines에 대입합니다.
    lines = text.splitlines()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not lines.
    if not lines:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("시스템 프롬프트가 비어 있습니다")
    # _VERSION_PATTERN.fullmatch()의 반환값을 match에 대입합니다.
    match = _VERSION_PATTERN.fullmatch(lines[0])
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: match is None.
    if match is None:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("시스템 프롬프트 첫 줄에 정수 version이 필요합니다")
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not text.strip().
    if not text.strip():
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("시스템 프롬프트가 비어 있습니다")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return text, match.group(1)


# _history_turns(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: history.
# 반환 타입 힌트: list[tuple[Message, Message]].
def _history_turns(history: Sequence[Message]) -> list[tuple[Message, Message]]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(history) % 2 != 0.
    if len(history) % 2 != 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("완료된 히스토리는 user/assistant 쌍이어야 합니다")
    # turns에 리스트(순서가 있고 수정 가능)을 대입합니다.
    turns: list[tuple[Message, Message]] = []
    # for 반복문: 대상의 항목을 하나씩 index에 대입하며 아래 블록을 실행합니다.
    for index in range(0, len(history), 2):
        # 오른쪽 식을 계산한 값을 user에 대입합니다.
        user = history[index]
        # 오른쪽 식을 계산한 값을 assistant에 대입합니다.
        assistant = history[index + 1]
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: user.role != 'user' or assistant.role
        # != 'assistant'.
        if user.role != "user" or assistant.role != "assistant":
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ValueError("히스토리 메시지 순서는 user/assistant여야 합니다")
        # 리스트 끝에 항목 하나를 추가합니다.
        turns.append((user, assistant))
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return turns
