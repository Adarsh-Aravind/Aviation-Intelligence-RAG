"""Data access for documents and chunks.

Services depend on the ``DocumentStore`` protocol so tests can swap in an in-memory fake.
"""

from __future__ import annotations

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
    def search_chunks(self, embedding: Sequence[float], limit: int) -> list[RetrievedChunk]: ...


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

    def search_chunks(self, embedding: Sequence[float], limit: int) -> list[RetrievedChunk]:
        vec = vector_literal(embedding)
        with self.pool.connection() as conn:
            rows = conn.execute(
                """
                select c.id, c.document_id, d.title, c.page_start, c.page_end, c.section,
                       c.content, 1 - (c.embedding <=> %(vec)s::vector) as score
                from chunks c
                join documents d on d.id = c.document_id
                where d.status = 'ready'
                order by c.embedding <=> %(vec)s::vector
                limit %(limit)s
                """,
                {"vec": vec, "limit": limit},
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
            )
            for r in rows
        ]
