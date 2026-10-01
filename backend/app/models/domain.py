"""Internal (non-API) data structures shared by services."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class PageText:
    page_number: int  # 1-based
    text: str


@dataclass(slots=True)
class Chunk:
    chunk_index: int
    content: str
    page_start: int
    page_end: int
    section: str | None = None

    @property
    def token_estimate(self) -> int:
        # ~4 characters per token for English prose — good enough for bookkeeping.
        return max(1, len(self.content) // 4)


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: int
    document_id: UUID
    document_title: str
    page_start: int
    page_end: int
    section: str | None
    content: str
    score: float  # cosine similarity to the question (drives the relevance gate)
    match: str = "semantic"  # "semantic", "keyword" or "both" (hybrid retrieval)
