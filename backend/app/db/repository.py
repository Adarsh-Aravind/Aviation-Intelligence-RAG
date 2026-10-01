"""Data access for documents and chunks.

Services depend on the ``DocumentStore`` protocol so tests can swap in an in-memory fake.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from psycopg_pool import ConnectionPool

from app.models.domain import Chunk, RetrievedChunk

DOCUMENT_COLUMNS = (
    "id, title, description, original_filename, storage_path, file_type, file_size, sha256, "
    "page_count, chunk_count, status, error_message, created_at, processed_at"
)


class DocumentStore(Protocol):
    def ping(self) -> bool: ...
    def create_document(
        self,
        *,
        doc_id: UUID,
        title: str,
        description: str | None,
        original_filename: str,
        storage_path: str,
        file_type: str,
        file_size: int,
        sha256: str,
    ) -> dict[str, Any]: ...
    def get_document(self, doc_id: UUID) -> dict[str, Any] | None: ...
    def get_document_by_sha(self, sha256: str) -> dict[str, Any] | None: ...
    def list_documents(self) -> list[dict[str, Any]]: ...
    def update_document(self, doc_id: UUID, **fields: Any) -> None: ...
    def delete_document(self, doc_id: UUID) -> bool: ...
    def document_ids_with_status(self, statuses: Sequence[str]) -> list[UUID]: ...
    def stale_awaiting_uploads(self, older_than_minutes: int) -> list[dict[str, Any]]: ...
    def stats(self) -> dict[str, Any]: ...
    def delete_chunks(self, doc_id: UUID) -> None: ...
    def insert_chunks(
        self, doc_id: UUID, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None: ...
    def search_chunks(
        self, embedding: Sequence[float], limit: int, query_text: str | None = None
    ) -> list[RetrievedChunk]: ...


RRF_K = 60  # standard reciprocal-rank-fusion constant

_VECTOR_SQL = """
    select c.id, c.document_id, d.title, c.page_start, c.page_end, c.section, c.content,
           1 - (c.embedding <=> %(vec)s::vector) as score, true as in_vec, false as in_kw
    from chunks c
    join documents d on d.id = c.document_id
    where d.status = 'ready'
    order by c.embedding <=> %(vec)s::vector
    limit %(limit)s
"""

_HYBRID_SQL = """
    with q as (
        select websearch_to_tsquery('english', %(kw_all)s) as all_q,
               websearch_to_tsquery('english', %(kw_any)s) as any_q
    ),
    vec as (
        select id, row_number() over (order by dist) as r
        from (
            select c.id, c.embedding <=> %(vec)s::vector as dist
            from chunks c join documents d on d.id = c.document_id
            where d.status = 'ready'
            order by dist
            limit %(k)s
        ) v
    ),
    kw as (
        select id, row_number() over (order by has_all desc, rank desc) as r
        from (
            -- passages containing ALL query terms first, then ANY term (Postgres FTS has no IDF,
            -- so plain OR ranking lets common words like "airspace" drown out decisive ones)
            select c.id, (c.fts @@ q.all_q) as has_all, ts_rank_cd(c.fts, q.any_q, 32) as rank
            from chunks c join documents d on d.id = c.document_id, q
            where d.status = 'ready' and c.fts @@ q.any_q
            order by has_all desc, rank desc
            limit %(k)s
        ) k
    ),
    fused as (
        select id, sum(1.0 / (%(rrf_k)s + r)) as rrf,
               bool_or(src = 'v') as in_vec, bool_or(src = 'k') as in_kw
        from (
            select id, r, 'v' as src from vec
            union all
            select id, r, 'k' as src from kw
        ) u
        group by id
    )
    select c.id, c.document_id, d.title, c.page_start, c.page_end, c.section, c.content,
           1 - (c.embedding <=> %(vec)s::vector) as score, f.in_vec, f.in_kw
    from fused f
    join chunks c on c.id = f.id
    join documents d on d.id = c.document_id
    order by f.rrf desc
    limit %(limit)s
"""


def _keyword_queries(text: str) -> tuple[str, str]:
    """(all-terms, any-term) queries for websearch_to_tsquery, built from plain words only so user
    input can never inject search operators. Postgres drops English stop words itself."""
    words = re.findall(r"[A-Za-z0-9]+", text)[:32]
    return " ".join(words), " or ".join(words)


_UPDATABLE = {"status", "error_message", "page_count", "chunk_count", "processed_at", "file_size"}


def vector_literal(values: Sequence[float]) -> str:
    """Format a vector as a pgvector text literal: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{float(v):.7g}" for v in values) + "]"


class PgDocumentStore:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def ping(self) -> bool:
        try:
            with self.pool.connection(timeout=5) as conn:
                conn.execute("select 1")
            return True
        except Exception:
            return False

    # ---- documents -------------------------------------------------------------------
    def create_document(self, **kw: Any) -> dict[str, Any]:
        with self.pool.connection() as conn:
            row = conn.execute(
                f"""
                insert into documents
                    (id, title, description, original_filename, storage_path, file_type,
                     file_size, sha256, status)
                values (%(doc_id)s, %(title)s, %(description)s, %(original_filename)s,
                        %(storage_path)s, %(file_type)s, %(file_size)s, %(sha256)s,
                        'awaiting_upload')
                returning {DOCUMENT_COLUMNS}
                """,
                kw,
            ).fetchone()
        return row

    def get_document(self, doc_id: UUID) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            return conn.execute(
                f"select {DOCUMENT_COLUMNS} from documents where id = %s", (doc_id,)
            ).fetchone()

    def get_document_by_sha(self, sha256: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            return conn.execute(
                f"select {DOCUMENT_COLUMNS} from documents where sha256 = %s", (sha256,)
            ).fetchone()

    def list_documents(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(
                f"select {DOCUMENT_COLUMNS} from documents "
                "where status <> 'awaiting_upload' order by created_at desc"
            ).fetchall()

    def update_document(self, doc_id: UUID, **fields: Any) -> None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"cannot update columns: {unknown}")
        if not fields:
            return
        assignments = ", ".join(f"{k} = %({k})s" for k in fields)
        with self.pool.connection() as conn:
            conn.execute(f"update documents set {assignments} where id = %(id)s", {**fields, "id": doc_id})

    def delete_document(self, doc_id: UUID) -> bool:
        with self.pool.connection() as conn:
            cur = conn.execute("delete from documents where id = %s", (doc_id,))
            return cur.rowcount > 0

    def document_ids_with_status(self, statuses: Sequence[str]) -> list[UUID]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "select id from documents where status = any(%s) order by created_at",
                (list(statuses),),
            ).fetchall()
        return [r["id"] for r in rows]

    def stale_awaiting_uploads(self, older_than_minutes: int) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(
                f"select {DOCUMENT_COLUMNS} from documents where status = 'awaiting_upload' "
                "and created_at < now() - make_interval(mins => %s)",
                (older_than_minutes,),
            ).fetchall()

    def stats(self) -> dict[str, Any]:
        with self.pool.connection() as conn:
            by_status = conn.execute(
                "select status, count(*)::int as n, coalesce(sum(page_count), 0)::int as pages "
                "from documents where status <> 'awaiting_upload' group by status"
            ).fetchall()
            chunks = conn.execute("select count(*)::int as n from chunks").fetchone()
        return {
            "by_status": {r["status"]: r["n"] for r in by_status},
            "pages_total": sum(r["pages"] for r in by_status if r["status"] == "ready"),
            "chunks_total": chunks["n"],
        }

    # ---- chunks ----------------------------------------------------------------------
    def delete_chunks(self, doc_id: UUID) -> None:
        with self.pool.connection() as conn:
            conn.execute("delete from chunks where document_id = %s", (doc_id,))

    def insert_chunks(
        self, doc_id: UUID, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        rows = [
            (
                doc_id,
                c.chunk_index,
                c.page_start,
                c.page_end,
                c.section,
                c.content,
                c.token_estimate,
                vector_literal(e),
            )
            for c, e in zip(chunks, embeddings, strict=True)
        ]
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                insert into chunks
                    (document_id, chunk_index, page_start, page_end, section, content,
                     token_estimate, embedding)
                values (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                """,
                rows,
            )

    def search_chunks(
        self, embedding: Sequence[float], limit: int, query_text: str | None = None
    ) -> list[RetrievedChunk]:
        """Vector search, or hybrid search when ``query_text`` is given: pgvector cosine ranking and
        Postgres full-text ranking (ts_rank_cd, BM25-like) fused with reciprocal rank fusion.

        Keyword matching rescues passages that embeddings rank poorly, e.g. dense tables of
        regulatory minimums. ``score`` is always the cosine similarity, so the relevance gate
        upstream keeps working on the same scale.
        """
        vec = vector_literal(embedding)
        kw_all, kw_any = _keyword_queries(query_text) if query_text else ("", "")
        with self.pool.connection() as conn:
            if not kw_any:
                rows = conn.execute(_VECTOR_SQL, {"vec": vec, "limit": limit}).fetchall()
            else:
                rows = conn.execute(
                    _HYBRID_SQL,
                    {
                        "vec": vec,
                        "kw_all": kw_all,
                        "kw_any": kw_any,
                        "k": limit,
                        "rrf_k": RRF_K,
                        "limit": limit,
                    },
                ).fetchall()
        return [
            RetrievedChunk(
                chunk_id=r["id"],
                document_id=r["document_id"],
                document_title=r["title"],
                page_start=r["page_start"],
                page_end=r["page_end"],
                section=r["section"],
                content=r["content"],
                score=float(r["score"]),
                match="both" if r["in_vec"] and r["in_kw"] else ("keyword" if r["in_kw"] else "semantic"),
            )
            for r in rows
        ]
