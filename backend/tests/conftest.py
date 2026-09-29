"""Shared fixtures: in-memory fakes for the database, storage, embedder and LLM."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container
from app.main import create_app
from app.models.domain import Chunk, RetrievedChunk
from app.rate_limit import limiter
from app.services.ingestion import IngestionWorker
from app.services.rag import RagService
from app.services.retrieval import Retriever
from app.services.storage import DownloadResult, FileTooLargeError, StorageError

API_KEY = "test-api-key"
ADMIN_KEY = "test-admin-key"


# ---------------------------------------------------------------------------- fakes
class FakeEmbedder:
    """Deterministic hashed bag-of-words vectors — similar texts get similar vectors."""

    model_name = "fake-embedder"
    dim = 256
    loaded = True

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            if len(tok) < 3:
                continue
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    def load(self):
        pass


class FakeStore:
    def __init__(self):
        self.docs: dict[UUID, dict] = {}
        self.chunks: dict[UUID, list[tuple[Chunk, list[float]]]] = {}

    def ping(self):
        return True

    def create_document(self, *, doc_id, **kw):
        doc = {
            "id": doc_id,
            **kw,
            "page_count": None,
            "chunk_count": 0,
            "status": "awaiting_upload",
            "error_message": None,
            "created_at": datetime.now(UTC),
            "processed_at": None,
        }
        self.docs[doc_id] = doc
        return dict(doc)

    def get_document(self, doc_id):
        d = self.docs.get(doc_id)
        return dict(d) if d else None

    def get_document_by_sha(self, sha256):
        return next((dict(d) for d in self.docs.values() if d["sha256"] == sha256), None)

    def list_documents(self):
        return [dict(d) for d in self.docs.values() if d["status"] != "awaiting_upload"]

    def update_document(self, doc_id, **fields):
        if doc_id in self.docs:
            self.docs[doc_id].update(fields)

    def delete_document(self, doc_id):
        self.chunks.pop(doc_id, None)
        return self.docs.pop(doc_id, None) is not None

    def document_ids_with_status(self, statuses):
        return [i for i, d in self.docs.items() if d["status"] in statuses]

    def stale_awaiting_uploads(self, older_than_minutes):
        return []

    def stats(self):
        by_status: dict[str, int] = {}
        for d in self.docs.values():
            if d["status"] != "awaiting_upload":
                by_status[d["status"]] = by_status.get(d["status"], 0) + 1
        return {
            "by_status": by_status,
            "pages_total": sum(d["page_count"] or 0 for d in self.docs.values() if d["status"] == "ready"),
            "chunks_total": sum(len(c) for c in self.chunks.values()),
        }

    def delete_chunks(self, doc_id):
        self.chunks.pop(doc_id, None)

    def insert_chunks(self, doc_id, chunks, embeddings):
        self.chunks.setdefault(doc_id, []).extend(zip(chunks, embeddings, strict=True))

    def search_chunks(self, embedding, limit):
        results = []
        for doc_id, items in self.chunks.items():
            doc = self.docs.get(doc_id)
            if not doc or doc["status"] != "ready":
                continue
            for chunk, vec in items:
                score = sum(a * b for a, b in zip(embedding, vec, strict=True))
                results.append(
                    RetrievedChunk(
                        chunk_id=hash((doc_id, chunk.chunk_index)) & 0xFFFFFFF,
                        document_id=doc_id,
                        document_title=doc["title"],
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        section=chunk.section,
                        content=chunk.content,
                        score=score,
                    )
                )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]


class FakeStorage:
    configured = True

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def create_signed_upload_url(self, path):
        return f"https://storage.test/upload/{path}?token=abc"

    def create_signed_read_url(self, path, expires_in):
        return f"https://storage.test/read/{path}?token=xyz"

    def download_to(self, path, dest: Path, max_bytes):
        if path not in self.objects:
            raise StorageError("uploaded file not found in storage")
        data = self.objects[path]
        if len(data) > max_bytes:
            raise FileTooLargeError("file exceeds the upload size limit")
        dest.write_bytes(data)
        return DownloadResult(size=len(data), sha256=hashlib.sha256(data).hexdigest())

    def delete(self, path):
        self.deleted.append(path)
        self.objects.pop(path, None)


class FakeLLM:
    model = "fake-llm"

    def __init__(self, reply: str = "Answer [1]."):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.reply


# ------------------------------------------------------------------------- fixtures
def make_pdf(pages: list[list[str]], header: str | None = "FAA-H-8083 Test Handbook") -> bytes:
    """Build a real PDF with fpdf2. Each page is a list of lines/paragraphs."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(False)
    pdf.set_font("Helvetica", size=11)
    for i, lines in enumerate(pages, start=1):
        pdf.add_page()
        if header:
            pdf.set_xy(10, 8)
            pdf.cell(0, 6, header)
        pdf.set_xy(10, 20)
        for line in lines:
            pdf.multi_cell(0, 6, line)
            pdf.ln(3)
        pdf.set_xy(10, 280)
        pdf.cell(0, 6, f"Page {i}")
    return bytes(pdf.output())


AVIATION_PAGES = [
    [
        "CHAPTER 1 WEIGHT AND BALANCE",
        "Weight and balance control is a responsibility of the pilot. The center of gravity must remain "
        "within the approved limits published in the airplane flight manual for every phase of flight.",
        "Exceeding the maximum takeoff weight reduces climb performance and increases takeoff distance.",
    ],
    [
        "2.1 Density Altitude",
        "Density altitude is pressure altitude corrected for nonstandard temperature. High density "
        "altitude reduces engine power, propeller efficiency and lift, which lengthens the takeoff roll.",
    ],
    [
        "2.2 Stall Recovery",
        "To recover from a stall, reduce the angle of attack by lowering the nose, level the wings, and "
        "apply maximum allowable power while avoiding secondary stalls.",
    ],
    [
        "2.3 Visual Flight Rules",
        "Basic VFR weather minimums specify flight visibility and distance from clouds for each class of "
        "airspace. Pilots must remain clear of clouds in Class G airspace at low altitudes during the day.",
    ],
]


@pytest.fixture
def pdf_bytes() -> bytes:
    return make_pdf(AVIATION_PAGES)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        backend_api_key=API_KEY,
        backend_admin_key=ADMIN_KEY,
        database_url="",
        groq_api_key="fake",
        min_relevance=0.2,
        chunk_size_chars=400,
        chunk_overlap_chars=80,
        max_upload_mb=5,
    )


@pytest.fixture
def fakes(settings):
    store, storage, embedder, llm = FakeStore(), FakeStorage(), FakeEmbedder(), FakeLLM()
    worker = IngestionWorker(store, storage, embedder, settings)
    retriever = Retriever(store, embedder, candidates=10, top_k=4, min_relevance=settings.min_relevance)
    rag = RagService(retriever, llm)
    container = Container(settings, store, storage, embedder, worker, rag)
    return container, llm


@pytest.fixture
def client(fakes):
    container, _ = fakes
    limiter.reset()
    app = create_app(container)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": API_KEY}


@pytest.fixture
def admin_headers():
    return {"X-API-Key": API_KEY, "X-Admin-Key": ADMIN_KEY}
