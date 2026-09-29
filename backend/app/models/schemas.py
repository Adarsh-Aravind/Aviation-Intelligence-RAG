"""Pydantic request/response models — the typed API contract (mirrored in frontend/src/lib/types.ts)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

DocumentStatus = Literal["awaiting_upload", "queued", "processing", "ready", "failed"]


class DocumentOut(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    original_filename: str
    file_type: str
    file_size: int
    page_count: int | None = None
    chunk_count: int = 0
    status: DocumentStatus
    error_message: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int


class UploadInitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    file_size: int = Field(gt=0)
    content_type: str = "application/pdf"
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("sha256")
    @classmethod
    def lower_hash(cls, v: str) -> str:
        return v.lower()


class UploadInitResponse(BaseModel):
    document: DocumentOut
    upload_url: str


class FileUrlResponse(BaseModel):
    url: str
    expires_in: int


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)

    @field_validator("question")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("question is too short")
        return v


class SourceChunk(BaseModel):
    n: int = Field(description="1-based source number as referenced in the answer, e.g. [1]")
    chunk_id: int
    document_id: UUID
    document_title: str
    page_start: int
    page_end: int
    section: str | None = None
    excerpt: str
    score: float = Field(description="Cosine similarity, 0..1 (higher is more relevant)")


class Timings(BaseModel):
    embedding_ms: float = 0
    retrieval_ms: float = 0
    llm_ms: float = 0
    total_ms: float = 0


class ChatResponse(BaseModel):
    answer: str
    status: Literal["answered", "insufficient_context"]
    grounded: bool = Field(description="True when the answer cites at least one retrieved source")
    citations: list[SourceChunk] = Field(description="Sources actually cited in the answer")
    retrieved: list[SourceChunk] = Field(description="Other retrieved sources that were not cited")
    timings: Timings
    model: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: bool
    embedder_loaded: bool
    embedding_model: str
    llm_configured: bool
    llm_model: str
    storage_configured: bool


class StatsResponse(BaseModel):
    documents_total: int
    documents_by_status: dict[str, int]
    chunks_total: int
    pages_total: int
    embedding_model: str
    llm_model: str
