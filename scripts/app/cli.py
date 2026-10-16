# 파이썬 공부 | scripts/app/cli.py
# 터미널에서 입력을 받아 대화와 슬래시 명령을 처리하고 결과를 출력합니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Text CLI: Phase 0 echo loop, plus later-phase slash commands when chat is wired."""

from __future__ import annotations

from typing import TextIO

from app.core.errors import ExitCode
from app.memory.commands import try_handle_memory_command
from app.orchestrator.loop import ChatOrchestrator, TurnOutcome
from app.safety.approval import GrantMethod

# HELP_TEXT에 문자열을 대입합니다.
HELP_TEXT = "사용 가능한 명령: /help(도움말), /bye(종료)"
# CHAT_HELP_TEXT에 문자열을 대입합니다.
CHAT_HELP_TEXT = (
    "사용 가능한 명령: /help(도움말), /clear(현재 문맥 초기화), "
    "/budget(비용 현황), /index(문서 동기화), /search <질의>(웹·문서 검색), "
    "/details(직전 상세), /status(응답 룰북), "
    "/recall <질의>(대화 검색), /recall status|reindex|forget <턴ID>, "
    "/commands(명령 기억), /commands reindex(벡터 갱신), "
    "/learn 표현 => /open_app 앱이름(명령 뜻 저장), "
    "/open_app <앱>(앱 실행·최초 승인), /apps(실행 허용 목록), "
    "/apps revoke <ID>(허용 취소), /open_folder <root> [경로], "
    "/open_url <https://...>, /create_file <root> <파일> [내용], /bye(종료), "
    "기억해: ..., 틀림: A → B, /memory list|confirm|edit|export, /forget <id>"
)
# WELCOME_TEXT에 문자열을 대입합니다.
WELCOME_TEXT = "Jarvis 로컬 CLI입니다. /help를 입력하면 도움말을 볼 수 있습니다."


# _write(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: stream, text.
# 반환 타입 힌트: 별도 결과 없음(None).
def _write(stream: TextIO, text: str) -> None:
    # 열린 출력 대상에 데이터를 기록합니다.
    stream.write(text)
    # 열린 출력 대상에 데이터를 기록합니다.
    stream.write("\n")
    # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
    stream.flush()


# _display(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: outcome.
# 반환 타입 힌트: 문자열(str).
def _display(outcome: TurnOutcome) -> str:
    # 오른쪽 식을 계산한 값을 suffix에 대입합니다.
    # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
    suffix = "\n상세: /details" if outcome.presentation and outcome.presentation.detail_text else ""
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return outcome.display_text + suffix


# _budget_text(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: chat.
# 반환 타입 힌트: 문자열(str).
def _budget_text(chat: ChatOrchestrator) -> str:
    # chat.budget_status()의 반환값을 status에 대입합니다.
    status = chat.budget_status()
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
    return (
        f"오늘: ${status.day.used:.2f}/{status.day.limit:.2f} "
        f"({status.day.ratio * 100:.1f}%), "
        f"이번 달: ${status.month.used:.2f}/{status.month.limit:.2f} "
        f"({status.month.ratio * 100:.1f}%)"
    )


# _handle_approval(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: chat, outcome, input_stream, output_stream, typed_phrase.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def _handle_approval(
    chat: ChatOrchestrator,
    outcome: TurnOutcome,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    typed_phrase: str,
) -> str:
    # 오른쪽 식을 계산한 값을 verdict에 대입합니다.
    verdict = outcome.pending_approval
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: verdict is None.
    if verdict is None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _display(outcome)
    # _write()을 호출해 작업을 수행합니다.
    _write(output_stream, verdict.display)
    # _write()을 호출해 작업을 수행합니다.
    _write(output_stream, verdict.reason)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: verdict.decision == 'typed_confirm'.
    if verdict.decision == "typed_confirm":
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, f"계속하려면 다음 문구를 그대로 입력하세요: {typed_phrase}")
    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
    else:
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, "실행하려면 y, 취소하려면 n을 입력하세요.")

    # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
    while True:
        # 열린 출력 대상에 데이터를 기록합니다.
        output_stream.write("승인> ")
        # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
        output_stream.flush()
        # input_stream.readline()의 반환값을 answer에 대입합니다.
        answer = input_stream.readline()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: answer == ''.
        if answer == "":
            # chat.discard_pending_approval()을 호출해 작업을 수행합니다.
            chat.discard_pending_approval(cause="shutdown")
            # '승인 대기가 취소되었습니다.'을 반환하고 이 함수의 실행을 끝냅니다.
            return "승인 대기가 취소되었습니다."
        # answer.rstrip('\r\n').strip()의 반환값을 response에 대입합니다.
        response = answer.rstrip("\r\n").strip()
        # response.lower()의 반환값을 lowered에 대입합니다.
        lowered = response.lower()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lowered in {'n', 'no', '아니오',
        # '취소'}.
        if lowered in {"n", "no", "아니오", "취소"}:
            # chat.discard_pending_approval()을 호출해 작업을 수행합니다.
            chat.discard_pending_approval(cause="user_deny")
            # '작업을 실행하지 않았습니다.'을 반환하고 이 함수의 실행을 끝냅니다.
            return "작업을 실행하지 않았습니다."
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: verdict.decision == 'typed_confirm'.
        if verdict.decision == "typed_confirm":
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: response != typed_phrase.
            if response != typed_phrase:
                # chat.discard_pending_approval()을 호출해 작업을 수행합니다.
                chat.discard_pending_approval(cause="user_deny")
                # '확인 문구가 일치하지 않아 작업을 취소했습니다.'을 반환하고 이 함수의 실행을
                # 끝냅니다.
                return "확인 문구가 일치하지 않아 작업을 취소했습니다."
            # method에 문자열을 대입합니다.
            method: GrantMethod = "user_typed_phrase"
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: lowered in {'y', 'yes', '예', 'ㅇ'}.
        elif lowered in {"y", "yes", "예", "ㅇ"}:
            # method에 문자열을 대입합니다.
            method = "user_text"
        # 앞선 조건이 거짓이면 이 블록을 실행합니다.
        else:
            # _write()을 호출해 작업을 수행합니다.
            _write(output_stream, "y/n 또는 확인 문구를 입력하세요.")
            # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
            continue

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chat.approval_store is None or
        # chat.pending_context is
        # None.
        if chat.approval_store is None or chat.pending_context is None:
            # '승인 저장소가 구성되지 않았습니다.'을 반환하고 이 함수의 실행을 끝냅니다.
            return "승인 저장소가 구성되지 않았습니다."
        # chat.approval_store.grant()의 반환값을 ticket에 대입합니다.
        ticket = chat.approval_store.grant(
            verdict,
            ctx=chat.pending_context,
            method=method,
        )
        # chat.resume_after_approval()의 반환값을 resumed에 대입합니다.
        resumed = chat.resume_after_approval(ticket)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _display(resumed)


# _handle_turn_with_approval(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, chat, input_stream, output_stream, typed_phrase.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 문자열(str).
def _handle_turn_with_approval(
    text: str,
    *,
    chat: ChatOrchestrator,
    input_stream: TextIO,
    output_stream: TextIO,
    typed_phrase: str,
) -> str:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chat.has_pending_approval().
    if chat.has_pending_approval():
        # chat.discard_pending_approval()을 호출해 작업을 수행합니다.
        chat.discard_pending_approval(cause="new_input")
    # chat.handle_turn()의 반환값을 outcome에 대입합니다.
    outcome = chat.handle_turn(text)
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: outcome.pending_approval is not None.
    if outcome.pending_approval is not None:
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return _handle_approval(
            chat,
            outcome,
            input_stream=input_stream,
            output_stream=output_stream,
            typed_phrase=typed_phrase,
        )
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return _display(outcome)


# _handle_line(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text, output_stream, chat, input_stream, typed_phrase.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 참/거짓(bool).
def _handle_line(
    text: str,
    output_stream: TextIO,
    *,
    chat: ChatOrchestrator | None,
    input_stream: TextIO | None = None,
    typed_phrase: str = "실행합니다",
) -> bool:
    # text.strip().lower()의 반환값을 command에 대입합니다.
    command = text.strip().lower()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: command == '/help'.
    if command == "/help":
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, CHAT_HELP_TEXT if chat is not None else HELP_TEXT)
        # True을 반환하고 이 함수의 실행을 끝냅니다.
        return True
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: command == '/bye'.
    if command == "/bye":
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chat is not None.
        if chat is not None:
            # chat.discard_pending_approval()을 호출해 작업을 수행합니다.
            chat.discard_pending_approval(cause="shutdown")
            # chat.end()을 호출해 작업을 수행합니다.
            chat.end(reason="bye")
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, "안전하게 종료합니다.")
        # False을 반환하고 이 함수의 실행을 끝냅니다.
        return False
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chat is None.
    if chat is None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: text.strip().
        if text.strip():
            # _write()을 호출해 작업을 수행합니다.
            _write(output_stream, text)
        # True을 반환하고 이 함수의 실행을 끝냅니다.
        return True
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: command == '/clear'.
    if command == "/clear":
        # chat.clear()을 호출해 작업을 수행합니다.
        chat.clear()
        # chat.discard_pending_approval()을 호출해 작업을 수행합니다.
        chat.discard_pending_approval(cause="new_input")
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, "현재 대화 문맥을 초기화했습니다. raw 기록은 유지됩니다.")
        # True을 반환하고 이 함수의 실행을 끝냅니다.
        return True
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: command == '/budget'.
    if command == "/budget":
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, _budget_text(chat))
        # True을 반환하고 이 함수의 실행을 끝냅니다.
        return True
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: command == '/index'.
    if command == "/index":
        # chat.start()을 호출해 작업을 수행합니다.
        chat.start()
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, chat.handle_index())
        # True을 반환하고 이 함수의 실행을 끝냅니다.
        return True
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not text.strip().
    if not text.strip():
        # True을 반환하고 이 함수의 실행을 끝냅니다.
        return True
    # chat.start()을 호출해 작업을 수행합니다.
    chat.start()
    # chat.memory_command_context()의 반환값을 memory_ctx에 대입합니다.
    memory_ctx = chat.memory_command_context()
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: memory_ctx is not None.
    if memory_ctx is not None:
        # try_handle_memory_command()의 반환값을 memory_result에 대입합니다.
        memory_result = try_handle_memory_command(text, memory_ctx)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: memory_result is not None.
        if memory_result is not None:
            # _write()을 호출해 작업을 수행합니다.
            _write(output_stream, memory_result.message)
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return memory_result.ok or True
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: input_stream is None.
    if input_stream is None:
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, _display(chat.handle_turn(text)))
    # 앞선 조건이 거짓이면 이 블록을 실행합니다.
    else:
        # _write()을 호출해 작업을 수행합니다.
        _write(
            output_stream,
            _handle_turn_with_approval(
                text,
                chat=chat,
                input_stream=input_stream,
                output_stream=output_stream,
                typed_phrase=typed_phrase,
            ),
        )
    # True을 반환하고 이 함수의 실행을 끝냅니다.
    return True


# run_cli(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: input_stream, output_stream, once, chat, typed_confirm_phrase.
# 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
# 반환 타입 힌트: 정수(int).
def run_cli(
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    once: str | None = None,
    chat: ChatOrchestrator | None = None,
    typed_confirm_phrase: str = "실행합니다",
) -> int:
    """Run the Phase 0 echo CLI, or the later chat loop when ``chat`` is provided."""
    # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
    try:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chat is not None.
        if chat is not None:
            # chat.start()을 호출해 작업을 수행합니다.
            chat.start()
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: once is not None.
        if once is not None:
            # _handle_line()의 반환값을 keep_running에 대입합니다.
            keep_running = _handle_line(
                once,
                output_stream,
                chat=chat,
                input_stream=input_stream,
                typed_phrase=typed_confirm_phrase,
            )
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: keep_running and chat is not None.
            if keep_running and chat is not None:
                # chat.discard_pending_approval()을 호출해 작업을 수행합니다.
                chat.discard_pending_approval(cause="shutdown")
                # chat.end()을 호출해 작업을 수행합니다.
                chat.end(reason="bye")
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return int(ExitCode.SUCCESS)

        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, WELCOME_TEXT)
        # while 반복문: 조건을 매번 다시 검사하고 참인 동안 아래 블록을 반복합니다.
        while True:
            # 열린 출력 대상에 데이터를 기록합니다.
            output_stream.write("Jarvis> ")
            # 출력 버퍼에 모인 데이터를 다음 출력 계층으로 내보냅니다.
            output_stream.flush()
            # input_stream.readline()의 반환값을 line에 대입합니다.
            line = input_stream.readline()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: line == ''.
            if line == "":
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chat is not None.
                if chat is not None:
                    # chat.discard_pending_approval()을 호출해 작업을 수행합니다.
                    chat.discard_pending_approval(cause="shutdown")
                    # chat.end()을 호출해 작업을 수행합니다.
                    chat.end(reason="bye")
                # _write()을 호출해 작업을 수행합니다.
                _write(output_stream, "안전하게 종료합니다.")
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return int(ExitCode.SUCCESS)
            # line.rstrip()의 반환값을 text에 대입합니다.
            text = line.rstrip("\r\n")
            # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
            if not _handle_line(
                text,
                output_stream,
                chat=chat,
                input_stream=input_stream,
                typed_phrase=typed_confirm_phrase,
            ):
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                return int(ExitCode.SUCCESS)
    # KeyboardInterrupt를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
    except KeyboardInterrupt:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: chat is not None.
        if chat is not None:
            # chat.cancel_current()을 호출해 작업을 수행합니다.
            chat.cancel_current()
            # chat.end()을 호출해 작업을 수행합니다.
            chat.end(reason="discarded")
        # _write()을 호출해 작업을 수행합니다.
        _write(output_stream, "\n입력을 중단하고 안전하게 종료합니다.")
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return int(ExitCode.INTERRUPTED)
