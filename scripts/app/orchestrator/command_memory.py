# 파이썬 공부 | scripts/app/orchestrator/command_memory.py
# 사용자가 확인한 명령 예시를 저장하고 비슷한 요청에서 찾아봅니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Durable, user-confirmed command examples; retrieval never grants execution authority."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.core.errors import PolicyDenied
from app.llm.base import ToolCall


# normalized(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 문자열(str).
def normalized(text: str) -> str:
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).rstrip(".!")


# eligible(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 참/거짓(bool).
def eligible(text: str) -> bool:
    """Conservative guard, applied before retrieval and after model interpretation."""
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not text.strip() or len(text) > 256 or
    # text.startswith('/').
    if not text.strip() or len(text) > 256 or text.startswith("/"):
        # False을 반환하고 이 함수의 실행을 끝냅니다.
        return False
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return not any(word in text.casefold() for word in (
        "?", "\uff1f", "\n", '"', "'", "“", "”", "<", ">", "하지", "말고", "말아", "말라",
        "아니", "취소", "금지", "않", "안 ", "안켜", "안열", "안띄", "안실행",
        "방법", "했어", "했니", "됐어", "되는지", "상태", "중이", "실행 중",
        "검색", "찾아", "문서", "파일", "폴더", "링크", "사이트", "라고", "라면",
        "강제", "삭제", "레지스트리", "명령어", "수 있어", "할 수", "왜 ",
    ))


# Embedder: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class Embedder(Protocol):
    # identity(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def identity(self) -> str: ...
    # embed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: list[float].
    def embed(self, text: str) -> list[float]: ...


# OllamaSentenceEmbedder: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class OllamaSentenceEmbedder:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: model, timeout.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, model: str = "embeddinggemma", timeout: float = 10) -> None:
        # 언패킹: 오른쪽 결과를 순서대로 (self.model, self.timeout)에 나누어 담습니다.
        self.model, self.timeout = model, timeout
        # self._identity을 아직 값이 없음을 뜻하는 None으로 설정합니다.
        self._identity: str | None = None

    # _request(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: endpoint, payload.
    # 반환 타입 힌트: 어떤 타입이든 허용(Any).
    def _request(self, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        # urllib.request.Request()의 반환값을 request에 대입합니다.
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/" + endpoint,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        # Do not honor proxy settings or follow redirects to another host.
        # NoRedirect: 관련 데이터와 동작을 한데 묶는 클래스입니다.
        # 부모 클래스의 기능을 물려받습니다: urllib.request.HTTPRedirectHandler.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            # redirect_request(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
            # self는 이 메서드를 호출한 객체입니다.
            # *args는 추가 위치 인자를 튜플로 모읍니다.
            # **kwargs는 추가 이름 인자를 딕셔너리로 모읍니다.
            # 반환 타입 힌트: 별도 결과 없음(None).
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:
                # None을 반환하고 이 함수의 실행을 끝냅니다.
                return None
        # urllib.request.build_opener()의 반환값을 opener에 대입합니다.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with opener.open(request, timeout=self.timeout) as response:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return json.load(response)

    # identity(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: 문자열(str).
    # @property 덕분에 호출 괄호 없이 객체.속성처럼 결과를 읽습니다.
    @property
    def identity(self) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: self._identity is None.
        if self._identity is None:
            # 오른쪽 식을 계산한 값을 models에 대입합니다.
            models = self._request("tags")["models"]
            # next()의 반환값을 found에 대입합니다.
            found = next((m for m in models if m["name"] in
                          {self.model, self.model + ":latest"}), None)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: found is None.
            if found is None:
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("명령 임베딩 모델이 없습니다. embeddinggemma 설치를 확인하세요.")
            # 오른쪽 식을 계산한 값을 self._identity에 대입합니다.
            self._identity = self.model + ":" + found["digest"] + ":command-v1"
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self._identity

    # embed(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: text.
    # 반환 타입 힌트: list[float].
    def embed(self, text: str) -> list[float]:
        # 오른쪽 식을 계산한 값을 _에 대입합니다.
        _ = self.identity
        # self._request()의 반환값을 result에 대입합니다.
        result = self._request("embed", {
            "model": self.model, "input": text, "truncate": False, "keep_alive": "5m",
        })
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return unit_vector(result["embeddings"][0])


# unit_vector(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: value.
# 반환 타입 힌트: list[float].
def unit_vector(value: Any) -> list[float]:
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not isinstance(value, list) or not 1 <=
    # len(value) <= 8192.
    if not isinstance(value, list) or not 1 <= len(value) <= 8192:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("invalid embedding dimension")
    # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("invalid embedding values")
    # math.sqrt()의 반환값을 norm에 대입합니다.
    norm = math.sqrt(sum(x * x for x in value))
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: norm == 0.
    if norm == 0:
        # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
        raise ValueError("zero embedding")
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    return [x / norm for x in value]


# Match: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
@dataclass(frozen=True)
class Match:
    # call: ToolCall 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    call: ToolCall
    # phrase: 문자열(str) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    phrase: str
    # score: 실수(float) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    score: float
    # exact: 참/거짓(bool) 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    exact: bool


# CommandMemory: 관련 데이터와 동작을 한데 묶는 클래스입니다.
class CommandMemory:
    # 객체를 만들 때 자동 호출되는 초기화 메서드입니다. 필요한 값과 의존 객체를 보관합니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: path, embedder, limit, threshold.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def __init__(self, path: Path, embedder: Embedder, *, limit: int = 2000,
                 threshold: float = 0.60) -> None:
        # 언패킹: 오른쪽 결과를 순서대로 (self.path, self.embedder)에 나누어 담습니다.
        self.path, self.embedder = path, embedder
        # 언패킹: 오른쪽 결과를 순서대로 (self.limit, self.threshold)에 나누어 담습니다.
        self.limit, self.threshold = limit, threshold

    # connection(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Iterator[sqlite3.Connection].
    # @contextmanager: yield 앞은 with 진입 준비, 뒤는 with 종료 시 처리입니다.
    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # 폴더를 만듭니다. parents와 exist_ok가 있으면 상위 폴더·기존 폴더 처리를 정합니다.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            db.execute("BEGIN IMMEDIATE")
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            db.execute("CREATE TABLE IF NOT EXISTS command_memory_meta "
                       "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            db.execute("INSERT OR IGNORE INTO command_memory_meta VALUES ('schema_version','1')")
            # 오른쪽 식을 계산한 값을 version에 대입합니다.
            version = db.execute("SELECT value FROM command_memory_meta "
                                 "WHERE key='schema_version'").fetchone()[0]
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: version != '1'.
            if version != "1":
                # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
                raise PolicyDenied("지원하지 않는 명령 기억 스키마입니다.")
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            db.execute("CREATE TABLE IF NOT EXISTS command_examples ("
                       "id TEXT PRIMARY KEY, phrase TEXT NOT NULL UNIQUE, original TEXT NOT NULL, "
                       "tool TEXT NOT NULL CHECK(tool='open_app'), app TEXT NOT NULL, "
                       "provenance TEXT NOT NULL, created_at TEXT NOT NULL)")
            # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
            db.execute("CREATE TABLE IF NOT EXISTS command_vectors ("
                       "example_id TEXT NOT NULL, model TEXT NOT NULL, dimension INTEGER NOT NULL, "
                       "vector TEXT NOT NULL, PRIMARY KEY(example_id,model))")
            # yield는 값을 건네고 실행을 잠시 멈춥니다. 다음 요청이 오면 이어서 진행합니다.
            yield db

    # remember(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrase, call, provenance.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def remember(self, phrase: str, call: ToolCall, *, provenance: str) -> None:
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if (not eligible(phrase) or call.name != "open_app" or set(call.arguments) != {"app"}
                or provenance not in {"explicit_command", "user_confirmed"}):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("이 문장은 실행 명령 예시로 저장할 수 없습니다.")
        # 오른쪽 식을 계산한 값을 app에 대입합니다.
        app = call.arguments["app"]
        # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
        if not isinstance(app, str) or not re.fullmatch(r"[\w .+\-]{1,80}", app):
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise PolicyDenied("앱 이름만 명령 예시에 저장할 수 있습니다.")
        # Save the confirmed meaning first; embedding is a repairable derived index.
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.connection() as db:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = db.execute("SELECT id FROM command_examples WHERE phrase=?",
                             (normalized(phrase),)).fetchone()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: row is None.
            if row is None:
                # 여러 조건을 묶어 검사합니다. 전체 조건이 참일 때만 아래 블록을 실행합니다.
                if db.execute("SELECT COUNT(*) FROM command_examples").fetchone()[0] >= self.limit:
                    # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로
                    # 이동합니다.
                    raise PolicyDenied("명령 예시 저장 한도입니다. /commands에서 정리하세요.")
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                db.execute("INSERT INTO command_examples VALUES (?,?,?,?,?,?,?)", (
                    uuid.uuid4().hex, normalized(phrase), phrase, call.name, app,
                    provenance, datetime.now(UTC).isoformat(),
                ))
            # 앞선 조건이 거짓이면 이 블록을 실행합니다.
            else:
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                db.execute("UPDATE command_examples SET app=?,provenance=? WHERE id=?",
                           (app, provenance, row[0]))

    # index_pending(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: batch.
    # 반환 타입 힌트: 정수(int).
    def index_pending(self, batch: int = 16) -> int:
        # 오른쪽 식을 계산한 값을 model에 대입합니다.
        model = self.embedder.identity
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.connection() as db:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = db.execute("SELECT id,original FROM command_examples WHERE id NOT IN "
                              "(SELECT example_id FROM command_vectors WHERE model=?) LIMIT ?",
                              (model, batch)).fetchall()
        # count에 숫자 등 고정된 값을 대입합니다.
        count = 0
        # for 반복문: 대상의 항목을 하나씩 (key, phrase)에 대입하며 아래 블록을 실행합니다.
        for key, phrase in rows:
            # unit_vector()의 반환값을 vec에 대입합니다.
            vec = unit_vector(self.embedder.embed(phrase))
            # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을
            # 사용합니다.
            with self.connection() as db:
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                db.execute("INSERT OR REPLACE INTO command_vectors "
                           "SELECT ?,?,?,? WHERE EXISTS(SELECT 1 FROM command_examples WHERE id=?)",
                           (key, model, len(vec), json.dumps(vec), key))
            # 복합 대입: 기존 값에 오른쪽 값을 더한 결과를 다시 저장합니다.
            count += 1
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return count

    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrase.
    # 반환 타입 힌트: Match | None.
    def search(self, phrase: str) -> Match | None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not eligible(phrase).
        if not eligible(phrase):
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # self.exact()의 반환값을 exact에 대입합니다.
        exact = self.exact(phrase)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: exact is not None.
        if exact is not None:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return exact
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.connection() as db:
            # 오른쪽 식을 계산한 값을 total에 대입합니다.
            total = db.execute("SELECT COUNT(*) FROM command_examples").fetchone()[0]
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not total.
        if not total:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # self.index_pending()을 호출해 작업을 수행합니다.
        self.index_pending()
        # unit_vector()의 반환값을 vector에 대입합니다.
        vector = unit_vector(self.embedder.embed(phrase))
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.connection() as db:
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = db.execute("SELECT e.original,e.app,v.vector FROM command_examples e "
                              "JOIN command_vectors v ON e.id=v.example_id "
                              "WHERE v.model=? AND v.dimension=? LIMIT ?",
                              (self.embedder.identity, len(vector), self.limit)).fetchall()
        # ranked에 리스트(순서가 있고 수정 가능)을 대입합니다.
        ranked = []
        # for 반복문: 대상의 항목을 하나씩 (original, app, raw)에 대입하며 아래 블록을 실행합니다.
        for original, app, raw in rows:
            # unit_vector()의 반환값을 other에 대입합니다.
            other = unit_vector(json.loads(raw))
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(other) != len(vector).
            if len(other) != len(vector):
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # sum()의 반환값을 score에 대입합니다.
            score = sum(a * b for a, b in zip(vector, other, strict=True))
            # 리스트 끝에 항목 하나를 추가합니다.
            ranked.append((score, original, app))
        # ranked.sort()을 호출해 작업을 수행합니다.
        ranked.sort(reverse=True)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not ranked or ranked[0][0] <
        # self.threshold.
        if not ranked or ranked[0][0] < self.threshold:
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # 언패킹: 오른쪽 결과를 순서대로 (score, original, app)에 나누어 담습니다.
        score, original, app = ranked[0]
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return Match(
            ToolCall("semantic_open_app", "open_app", {"app": app}), original, score, False
        )

    # exact(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: phrase.
    # 반환 타입 힌트: Match | None.
    def exact(self, phrase: str) -> Match | None:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not eligible(phrase).
        if not eligible(phrase):
            # None을 반환하고 이 함수의 실행을 끝냅니다.
            return None
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.connection() as db:
            # 아래 함수()의 반환값을 row에 대입합니다.
            row = db.execute("SELECT original,app FROM command_examples WHERE phrase=?",
                             (normalized(phrase),)).fetchone()
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
        return (Match(ToolCall("learned_open_app", "open_app", {"app": row[1]}), row[0], 1, True)
                if row else None)

    # manage(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: command.
    # 반환 타입 힌트: 문자열(str).
    def manage(self, command: str) -> str:
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: command == '/commands reindex'.
        if command == "/commands reindex":
            # self.index_pending()의 반환값을 count에 대입합니다.
            count = self.index_pending()
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            # f 문자열: 중괄호 안의 값을 글자에 끼워 넣어 문자열을 만듭니다.
            return f"명령 벡터 {count}건을 갱신했습니다."
        # with 블록: 자원의 진입·종료 처리를 맡깁니다. as 뒤의 이름으로 열린 자원을 사용합니다.
        with self.connection() as db:
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: command.startswith('/commands
            # forget ').
            if command.startswith("/commands forget "):
                # 아래 함수()의 반환값을 key에 대입합니다.
                key = command.removeprefix("/commands forget ").strip()
                # execute 메서드를 호출합니다. SQL 문자열과 별도 인자는 쿼리와 바인딩할 값입니다.
                db.execute("DELETE FROM command_vectors WHERE example_id=?", (key,))
                # 오른쪽 식을 계산한 값을 count에 대입합니다.
                count = db.execute("DELETE FROM command_examples WHERE id=?", (key,)).rowcount
                # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                # 조건식: 가운데 if 조건이 참이면 앞의 값, 거짓이면 else 뒤의 값을 고릅니다.
                return "명령 예시를 삭제했습니다." if count else "명령 예시를 찾지 못했습니다."
            # 아래 함수()의 반환값을 rows에 대입합니다.
            rows = db.execute(
                "SELECT id,original,app FROM command_examples ORDER BY created_at"
            ).fetchall()
            # 오른쪽 식을 계산한 값을 vectors에 대입합니다.
            vectors = db.execute("SELECT COUNT(*) FROM command_vectors").fetchone()[0]
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return f"확인된 명령 {len(rows)}건 · 저장된 벡터 {vectors}건\n" + "\n".join(
            f"{phrase} → {app} 실행\n삭제: /commands forget {key}" for key, phrase, app in rows
        )
