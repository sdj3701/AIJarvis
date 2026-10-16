# 파이썬 공부 | scripts/app/rag/indexer.py
# 로컬 문서를 검색 가능한 색인에 저장하고 질문에 맞는 문서를 찾습니다.
# 읽는 법: # 뒤는 실행되지 않는 설명입니다. 들여쓰기는 실행할 코드의 묶음을 나타냅니다.
# name: Type과 -> Type은 타입 힌트이며, 일반 파이썬에서는 그 자체로 타입을 강제하지 않습니다.
# 기초 문법과 추천 읽기 순서: docs/PYTHON_STUDY.md
# import는 다른 모듈을 불러옵니다. from ... import는 사용할 이름을 골라 가져옵니다.
# 미래 기능 annotations는 타입 힌트 평가를 미뤄 아직 선언하지 않은 타입도 적을 수 있게 합니다.

"""Local document indexing and FTS5/learned-vector RRF search."""

from __future__ import annotations

import fnmatch
import json
import sqlite3
import threading
import time
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from app.config.models import DocumentPolicy, RagSettings
from app.core.errors import ConfigError
from app.core.ids import PrefixedIdFactory
from app.memory.migrations import configure_connection
from app.rag.embeddings import (
    reciprocal_rank_fusion,
)
from app.rag.generations import GenerationIndex
from app.rag.markdown_exports import export_root
from app.rag.models import IndexReport, RetrievedChunk
from app.rag.reranker import Candidate, Reranker
from app.rag.semantic import SemanticMemory


# EventSink: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# Protocol은 구현 객체가 어떤 속성·메서드를 갖춰야 하는지 정하는 타입 검사 규약입니다.
class EventSink(Protocol):
    # emit(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: event_type, payload.
    # 반환 타입 힌트: 별도 결과 없음(None).
    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


# DocumentIndexer: 관련 데이터와 동작을 한데 묶는 클래스입니다.
# @dataclass는 필드 선언을 바탕으로 초기화·비교 등의 메서드를 자동 생성합니다.
# frozen=True는 필드 재대입을 막습니다. 필드 안의 가변 객체까지 불변이 되지는 않습니다.
# slots=True는 인스턴스의 속성 저장 공간을 정해 임의 속성 추가를 제한합니다.
@dataclass(frozen=True, slots=True)
class DocumentIndexer:
    # database_path: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    database_path: Path
    # docs_root: Path 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    docs_root: Path
    # settings: RagSettings 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    settings: RagSettings
    # document_policy: DocumentPolicy 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는
    # 않습니다.
    document_policy: DocumentPolicy
    # ids: PrefixedIdFactory 타입을 기대하는 필드입니다. 이 줄만으로 값이 대입되지는 않습니다.
    ids: PrefixedIdFactory
    # events을 아직 값이 없음을 뜻하는 None으로 설정합니다.
    events: EventSink | None = None
    semantic: SemanticMemory | None = None
    reranker: Reranker | None = None
    models_root: Path | None = None
    auto_refresh: bool = True
    _refresh_at: float = field(default=0.0, init=False, repr=False, compare=False)
    _sync_lock: Any = field(default_factory=threading.RLock, init=False, repr=False, compare=False)
    last_diagnostics: dict[str, Any] = field(default_factory=dict, init=False, compare=False)

    def __post_init__(self) -> None:
        if self.reranker is None:
            object.__setattr__(
                self,
                "reranker",
                Reranker(
                    self.settings.rerank,
                    self.models_root or self.database_path.parent.parent / "models",
                    events=self.events,
                ),
            )
        if self.semantic is None and self.settings.semantic.enabled:
            object.__setattr__(
                self,
                "semantic",
                SemanticMemory(
                    self.database_path.with_name("semantic.sqlite3"),
                    self.settings.semantic,
                    events=self.events,
                    rrf_k=self.settings.rrf_k,
                    reranker=self.reranker,
                ),
            )
        elif self.semantic is not None and self.semantic.reranker is None:
            self.semantic.reranker = self.reranker

    def sync_vectors(self) -> None:
        if self.semantic is None:
            return
        GenerationIndex(self)
        with self._connection() as db:
            rows = db.execute("""SELECT dc.*,d.path,d.transfer_class,
                coalesce(p.title,d.path) AS title FROM doc_chunks dc
                JOIN documents d ON d.doc_id=dc.doc_id
                LEFT JOIN rag_chunk_provenance p ON p.chunk_id=dc.chunk_id""").fetchall()
        self.semantic.sync_documents([dict(row) for row in rows])

    # sync(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: now.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: IndexReport.
    def sync(self, *, now: datetime | None = None) -> IndexReport:
        # 아래 함수()의 반환값을 indexed_at에 대입합니다.
        with self._sync_lock:
            report = GenerationIndex(self).sync(now=now)
            self.last_diagnostics["index_errors"] = len(report.errors)
            object.__setattr__(
                self, "_refresh_at", time.monotonic() + self.settings.refresh_interval_s
            )
        if self.events is not None:
            # 이벤트 이름과 관련 데이터를 전달해 실행 상황을 기록하거나 알립니다.
            self.events.emit(
                "rag.index",
                {
                    "indexed": report.indexed,
                    "updated": report.updated,
                    "removed": report.removed,
                    "skipped": report.skipped,
                    "errors": list(report.errors),
                },
            )
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return report

    # search(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: query, max_results, max_chunks.
    # 별표(*) 뒤의 인자는 이름=값 형태로 전달해야 합니다.
    # 반환 타입 힌트: tuple[RetrievedChunk, ...].
    def search(
        self,
        query: str,
        *,
        max_results: int | None = None,
        max_chunks: int | None = None,
    ) -> tuple[RetrievedChunk, ...]:
        """Search with one complete question; only sync() splits documents.

        A long question is still a question, not a document to index. Query
        embedding and reranking retain its conditions instead of slicing them.
        """
        if self.auto_refresh and self.docs_root.exists() and time.monotonic() >= self._refresh_at:
            report = self.sync()
            self.last_diagnostics["index_errors"] = len(report.errors)
        self.last_diagnostics.update(input_kind="question", query_strategy="whole-query")
        store = GenerationIndex(self)
        limit = max_results or self.settings.search.max_results
        chunk_limit = max_chunks or self.settings.max_chunks_per_answer
        candidate_limit = max(limit * 3, chunk_limit)
        if self.reranker is not None:
            candidate_limit = self.reranker.retrieval_limit(candidate_limit)
        vector_ranked_ids: list[str] = []
        with self._connection() as connection:
            connection.execute("BEGIN")  # FTS, vector and text share one read snapshot.
            active = connection.execute("SELECT active_generation FROM rag_index_state").fetchone()
            fts_rows = connection.execute(
                """SELECT dc.*,d.path,d.transfer_class,
                bm25(doc_chunks_fts) AS score FROM doc_chunks_fts
                JOIN doc_chunks dc ON dc.rowid=doc_chunks_fts.rowid
                JOIN documents d ON d.doc_id=dc.doc_id WHERE doc_chunks_fts MATCH ?
                ORDER BY score LIMIT ?""",
                (_fts_query(query), candidate_limit),
            ).fetchall()
            if not fts_rows:
                # Trigram FTS cannot index two-character Korean words. A bounded
                # result set from literal LIKE keeps this lexical fallback useful.
                short = [s for s in query.split() if len(s) == 2 and s.isalnum()][:8]
                if short:
                    clauses = " OR ".join("dc.text LIKE ?" for _ in short)
                    fts_rows = connection.execute(
                        f"""SELECT dc.*,d.path,d.transfer_class
                        FROM doc_chunks dc JOIN documents d ON d.doc_id=dc.doc_id
                        WHERE {clauses} ORDER BY dc.chunk_id LIMIT ?""",
                        [*(f"%{s}%" for s in short), candidate_limit],
                    ).fetchall()
            if self.semantic is not None:
                try:
                    if active:
                        vector_ranked_ids = store.vector_ranking(
                            query, limit=candidate_limit, db=connection
                        )
                    else:
                        # Compatibility for imported pre-generation benchmark snapshots.
                        rows = connection.execute(
                            "SELECT dc.*,d.path,d.transfer_class FROM doc_chunks dc "
                            "JOIN documents d ON d.doc_id=dc.doc_id"
                        ).fetchall()
                        self.semantic.sync_documents([dict(r) for r in rows])
                        vector_ranked_ids = self.semantic.document_ranking(
                            query, limit=candidate_limit
                        )
                except Exception as error:
                    self.semantic._failed(error)
            fts_ranked_ids = [str(r["chunk_id"]) for r in fts_rows]
            keys = list(dict.fromkeys([*fts_ranked_ids, *vector_ranked_ids]))
            chunk_map = {str(r["chunk_id"]): dict(r) for r in fts_rows}
            if keys:
                marks = ",".join("?" for _ in keys)
                rows = connection.execute(
                    f"""SELECT dc.*,d.path,d.transfer_class
                    FROM doc_chunks dc JOIN documents d ON d.doc_id=dc.doc_id
                    WHERE dc.chunk_id IN ({marks})""",
                    keys,
                ).fetchall()
                chunk_map.update({str(r["chunk_id"]): dict(r) for r in rows})
            neighbors: dict[str, list[str]] = {}
            article_leads: dict[str, list[str]] = {}
            radius = self.settings.neighbor_chunks
            if radius:
                for key in keys:
                    neighbor_row = chunk_map[key]
                    nearby = connection.execute(
                        """SELECT dc.*,d.path,d.transfer_class
                        FROM doc_chunks dc JOIN documents d ON d.doc_id=dc.doc_id
                        WHERE dc.doc_id=? AND dc.ordinal BETWEEN ? AND ? ORDER BY dc.ordinal""",
                        (
                            neighbor_row["doc_id"],
                            neighbor_row["ordinal"] - radius,
                            neighbor_row["ordinal"] + radius,
                        ),
                    ).fetchall()
                    neighbors[key] = [r["chunk_id"] for r in nearby if r["chunk_id"] != key]
                    chunk_map.update({str(r["chunk_id"]): dict(r) for r in nearby})
            if chunk_map:
                metadata_keys = list(chunk_map)
                metadata_marks = ",".join("?" for _ in metadata_keys)
                for row in connection.execute(
                    f"""SELECT p.chunk_id,p.title,s.pages,s.structure FROM rag_chunk_provenance p
                    LEFT JOIN rag_chunk_structure s USING(chunk_id)
                    WHERE p.chunk_id IN ({metadata_marks})""",
                    metadata_keys,
                ):
                    chunk_map[row["chunk_id"]].update(
                        title=row["title"],
                        pages=json.loads(row["pages"] or "[]"),
                        structure=json.loads(row["structure"] or "[]"),
                    )
                # Same read transaction as candidates: provenance cannot change mid-search.
                doc_ids = list({r["doc_id"] for r in chunk_map.values()})
                marks = ",".join("?" for _ in doc_ids)
                locations = {
                    r["doc_id"]: json.loads(r["metadata"]).get("spans", [])
                    for r in connection.execute(
                        "SELECT doc_id,metadata FROM rag_document_content "
                        f"WHERE doc_id IN ({marks})",
                        doc_ids,
                    )
                }
                # A later fragment of a long article needs its lead premise too.
                for key, candidate_row in list(chunk_map.items()):
                    doc_spans = locations.get(candidate_row["doc_id"], [])
                    articles = {
                        (s["chapter"], s["article"])
                        for s in doc_spans
                        if s["article"]
                        and s["start"] < candidate_row["end_char"]
                        and s["end"] > candidate_row["start_char"]
                        and candidate_row["text"][
                            max(0, s["start"] - candidate_row["start_char"]) : min(
                                len(candidate_row["text"]), s["end"] - candidate_row["start_char"]
                            )
                        ].strip()
                    }
                    for chapter, article in articles:
                        lead = next(
                            s["start"]
                            for s in doc_spans
                            if (s["chapter"], s["article"]) == (chapter, article)
                        )
                        row = connection.execute(
                            """SELECT dc.*,d.path,d.transfer_class,p.title,s.pages,s.structure
                            FROM doc_chunks dc JOIN documents d USING(doc_id)
                            JOIN rag_chunk_provenance p USING(chunk_id)
                            JOIN rag_chunk_structure s USING(chunk_id)
                            WHERE dc.doc_id=? AND dc.start_char<=? AND dc.end_char>?
                            ORDER BY dc.ordinal LIMIT 1""",
                            (candidate_row["doc_id"], lead + 1, lead + 1),
                        ).fetchone()
                        if row and row["chunk_id"] != key:
                            lead_key = row["chunk_id"]
                            if lead_key not in chunk_map:
                                chunk_map[lead_key] = {
                                    **dict(row),
                                    "pages": json.loads(row["pages"]),
                                    "structure": json.loads(row["structure"]),
                                }
                            article_leads.setdefault(key, []).append(lead_key)
                for candidate_row in chunk_map.values():
                    start, end = candidate_row["start_char"], candidate_row["end_char"]
                    candidate_row["spans"] = [
                        {
                            **s,
                            "start": max(start, s["start"]) - start,
                            "end": min(end, s["end"]) - start,
                        }
                        for s in locations.get(candidate_row["doc_id"], [])
                        if s["start"] < end and s["end"] > start
                    ]
            self.last_diagnostics.update(
                {
                    "generation": active[0] if active else "legacy",
                    "lexical_candidates": len(fts_ranked_ids),
                    "vector_candidates": len(vector_ranked_ids),
                    "embedding_error": self.semantic.last_error if self.semantic else None,
                }
            )

        # 3. Reciprocal Rank Fusion (RRF)
        # Combine FTS5 rankings and Vector rankings with the configured smoothing constant.
        # rankings_to_fuse에 리스트(순서가 있고 수정 가능)을 대입합니다.
        rankings_to_fuse: list[list[str]] = []
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: fts_ranked_ids.
        if fts_ranked_ids:
            # 리스트 끝에 항목 하나를 추가합니다.
            rankings_to_fuse.append(fts_ranked_ids)
        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: vector_ranked_ids.
        if vector_ranked_ids:
            # 리스트 끝에 항목 하나를 추가합니다.
            rankings_to_fuse.append(vector_ranked_ids)

        # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not rankings_to_fuse.
        if not rankings_to_fuse:
            # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
            return ()

        # reciprocal_rank_fusion()의 반환값을 fused_scores에 대입합니다.
        fused_scores = reciprocal_rank_fusion(rankings_to_fuse, k=self.settings.rrf_k)
        candidates = [
            Candidate(key, str(chunk_map[key]["text"]), score)
            for key, score in fused_scores
            if key in chunk_map
        ]
        if self.reranker is not None:
            candidates = self.reranker.rank(query, candidates)

        # Rank seed hits first, then add adjacent context without reranking it as a
        # separate answer. All rows were read from the same generation snapshot.
        seed_count = (
            max(1, (chunk_limit + 1) // 2)
            if self.settings.neighbor_chunks or article_leads
            else len(candidates)
        )
        expanded = list(candidates[:seed_count])
        present = {c.key for c in expanded}
        by_key = {c.key: c for c in candidates}
        # Premises outrank generic adjacent context, even with adjacency disabled.
        for context_keys in (article_leads, neighbors):
            for c in candidates[:seed_count]:
                for key in context_keys.get(c.key, []):
                    if key not in present:
                        expanded.append(
                            by_key.get(key, Candidate(key, str(chunk_map[key]["text"]), c.score))
                        )
                        present.add(key)
        expanded.extend(c for c in candidates if c.key not in present)
        candidates = expanded
        # hits에 리스트(순서가 있고 수정 가능)을 대입합니다.
        hits: list[RetrievedChunk] = []
        # seen_docs에 딕셔너리(키와 값의 쌍)을 대입합니다.
        seen_docs: dict[str, int] = {}
        # for 반복문: 대상의 항목을 하나씩 (chunk_id, rrf_score)에 대입하며 아래 블록을
        # 실행합니다.
        for candidate in candidates:
            chunk_id, rrf_score = candidate.key, candidate.score
            # chunk_map.get()의 반환값을 row에 대입합니다.
            row = chunk_map.get(chunk_id)
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not row.
            if not row:
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # str()의 반환값을 doc_id에 대입합니다.
            doc_id = str(row["doc_id"])
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: seen_docs.get(doc_id, 0) >= 2.
            if seen_docs.get(doc_id, 0) >= self.settings.max_chunks_per_document:
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # RetrievedChunk()의 반환값을 chunk에 대입합니다.
            chunk = RetrievedChunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                relative_path=str(row["path"]),
                ordinal=int(row["ordinal"]),
                text=str(row["text"]),
                start_char=int(row["start_char"]),
                end_char=int(row["end_char"]),
                transfer_class=row["transfer_class"],
                score=float(rrf_score),
                rerank_score=candidate.rerank_score,
                title=str(row.get("title", "")),
                pages=tuple(row.get("pages", [])),
                structure=tuple(row.get("structure", [])),
                spans=tuple(row.get("spans", [])),
            )
            # 리스트 끝에 항목 하나를 추가합니다.
            hits.append(chunk)
            # 오른쪽 식을 계산한 값을 seen_docs[doc_id]에 대입합니다.
            seen_docs[doc_id] = seen_docs.get(doc_id, 0) + 1
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: len(hits) >= chunk_limit.
            if len(hits) >= chunk_limit:
                # 가장 가까운 반복문을 즉시 끝내고 반복문 다음 코드로 이동합니다.
                break
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        self.last_diagnostics.update(
            {
                "selected_chunks": len(hits),
                "rerank_status": self.reranker.status if self.reranker else "disabled",
            }
        )
        return tuple(hits)

    # _iter_files(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: Iterable[Path].
    def _iter_files(self) -> Iterable[Path]:
        # 오른쪽 식을 계산한 값을 extensions에 대입합니다.
        # 집합 컴프리헨션: 반복 결과를 중복 없이 모읍니다.
        extensions = {ext.lower() for ext in self.settings.supported_extensions}
        generated_root = export_root(self.database_path).resolve()
        # for 반복문: 대상의 항목을 하나씩 path에 대입하며 아래 블록을 실행합니다.
        for path in self.docs_root.rglob("*"):
            if path.resolve().is_relative_to(generated_root):
                continue
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not path.is_file().
            if not path.is_file():
                # 현재 회차의 나머지를 건너뛰고 가장 가까운 반복문의 다음 회차로 이동합니다.
                continue
            # path.suffix.lower()의 반환값을 suffix에 대입합니다.
            suffix = path.suffix.lower()
            # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: suffix == '.pdf' or suffix in
            # extensions.
            if suffix in extensions:
                # yield는 값을 건네고 실행을 잠시 멈춥니다. 다음 요청이 오면 이어서 진행합니다.
                yield path

    # _relative_path(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: path.
    # 반환 타입 힌트: 문자열(str).
    def _relative_path(self, path: Path) -> str:
        # self.docs_root.resolve()의 반환값을 root에 대입합니다.
        root = self.docs_root.resolve(strict=False)
        # path.resolve()의 반환값을 resolved에 대입합니다.
        resolved = path.resolve(strict=False)
        # 오류가 발생할 수 있는 작업을 시도합니다. except가 있으면 일치하는 예외를 처리합니다.
        try:
            # resolved.relative_to()의 반환값을 rel에 대입합니다.
            rel = resolved.relative_to(root)
        # ValueError를 잡아 처리합니다. as 뒤의 이름에는 발생한 예외 객체가 담깁니다.
        except ValueError as error:
            # 오류를 예외로 알립니다. 현재 흐름을 중단하고 이 예외를 처리할 곳으로 이동합니다.
            raise ConfigError("문서 경로가 docs root 밖입니다.", {"path": str(path)}) from error
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return str(rel).replace("/", "\\")

    # _transfer_class(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 입력: relative_path.
    # 반환 타입 힌트: Literal['local_only', 'api_allowed'].
    def _transfer_class(self, relative_path: str) -> Literal["local_only", "api_allowed"]:
        # relative_path.replace()의 반환값을 normalized에 대입합니다.
        normalized = relative_path.replace("/", "\\")
        # candidates에 튜플(원소 구성을 바꿀 수 없는 묶음)을 대입합니다.
        candidates = (normalized, f"docs\\{normalized}")
        # for 반복문: 대상의 항목을 하나씩 rule에 대입하며 아래 블록을 실행합니다.
        for rule in self.document_policy.class_rules:
            # rule.match.replace()의 반환값을 pattern에 대입합니다.
            pattern = rule.match.replace("/", "\\")
            # for 반복문: 대상의 항목을 하나씩 candidate에 대입하며 아래 블록을 실행합니다.
            for candidate in candidates:
                # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: fnmatch.fnmatch(candidate,
                # pattern).
                if fnmatch.fnmatch(candidate, pattern):
                    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
                    return rule.classification
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return self.document_policy.default_class

    # _connection(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
    # self는 이 메서드를 호출한 객체입니다.
    # 반환 타입 힌트: sqlite3.Connection.
    def _connection(self) -> closing[sqlite3.Connection]:
        # sqlite3.connect()의 반환값을 connection에 대입합니다.
        connection = sqlite3.connect(self.database_path)
        # 오른쪽 식을 계산한 값을 connection.row_factory에 대입합니다.
        connection.row_factory = sqlite3.Row
        # configure_connection()을 호출해 작업을 수행합니다.
        configure_connection(connection)
        # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
        return closing(connection)


# _fts_query(): 아래 코드를 재사용할 수 있도록 묶은 함수입니다.
# 입력: text.
# 반환 타입 힌트: 문자열(str).
def _fts_query(text: str) -> str:
    # 오른쪽 식을 계산한 값을 tokens에 대입합니다.
    # 리스트 컴프리헨션: 반복하며 식을 계산하고 조건에 맞는 결과를 리스트로 모읍니다.
    tokens = [token for token in text.split() if token.strip()]
    # 조건이 참일 때만 아래 들여쓰기 블록을 실행합니다: not tokens.
    if not tokens:
        # '""'을 반환하고 이 함수의 실행을 끝냅니다.
        return '""'
    # 계산한 결과를 호출한 쪽으로 돌려주고 이 함수의 실행을 끝냅니다.
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
