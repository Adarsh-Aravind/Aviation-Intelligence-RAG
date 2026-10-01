"""Hybrid retrieval: pgvector semantic search + Postgres full-text search, fused with RRF."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.db.repository import DocumentStore
from app.models.domain import RetrievedChunk
from app.services.embeddings import Embedder


@dataclass(slots=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]  # relevant chunks (score >= threshold), best first
    best_score: float | None
    embedding_ms: float = 0.0
    retrieval_ms: float = 0.0
    candidates: list[RetrievedChunk] = field(default_factory=list)


class Retriever:
    def __init__(
        self,
        store: DocumentStore,
        embedder: Embedder,
        candidates: int = 20,
        top_k: int = 6,
        min_relevance: float = 0.55,
        hybrid: bool = True,
    ):
        self.store = store
        self.embedder = embedder
        self.candidates = candidates
        self.top_k = top_k
        self.min_relevance = min_relevance
        self.hybrid = hybrid

    def retrieve(self, question: str) -> RetrievalResult:
        t0 = time.perf_counter()
        query_vec = self.embedder.embed_query(question)
        t1 = time.perf_counter()
        candidates = self.store.search_chunks(
            query_vec, limit=self.candidates, query_text=question if self.hybrid else None
        )
        t2 = time.perf_counter()

        # Keep the store's order (fused for hybrid, cosine otherwise). The relevance gate stays on
        # cosine similarity, so keyword-only matches cannot pull in off-topic passages.
        relevant = [c for c in candidates if c.score >= self.min_relevance]
        return RetrievalResult(
            chunks=_dedupe(relevant)[: self.top_k],
            best_score=max((c.score for c in candidates), default=None),
            embedding_ms=(t1 - t0) * 1000,
            retrieval_ms=(t2 - t1) * 1000,
            candidates=candidates,
        )


def _dedupe(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Drop chunks already covered by a higher-ranked one: overlapping text within a document, or the
    same passage in another document (e.g. the same handbook uploaded twice as different files)."""
    kept: list[RetrievedChunk] = []
    for c in chunks:
        head = c.content[:200]
        if any(head in k.content for k in kept):
            continue
        kept.append(c)
    return kept
