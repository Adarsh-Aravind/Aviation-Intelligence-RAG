"""Background ingestion: download → validate → extract → chunk → embed → store.

A single worker thread processes one document at a time. That's deliberate on a 4 GB host:
it bounds peak memory and keeps the chat endpoint responsive while large manuals are indexed.
"""

from __future__ import annotations

import logging
import queue
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.config import Settings
from app.db.repository import DocumentStore
from app.logging_config import log_extra
from app.services.chunking import chunk_pages, embedding_text
from app.services.embeddings import Embedder
from app.services.pdf import PdfValidationError, extract_pdf
from app.services.storage import (
    FileTooLargeError,
    ObjectStorage,
    StorageError,
    TransientStorageError,
)

logger = logging.getLogger(__name__)

INSERT_BATCH = 64
_STOP = object()
RETRY_BASE_S = 30.0
RETRY_MAX_S = 600.0


def _is_transient(exc: BaseException) -> bool:
    """Errors caused by the network/DB being unreachable (home internet outage), not by the file."""
    if isinstance(exc, TransientStorageError):
        return True
    try:
        import psycopg
        from psycopg_pool import PoolTimeout

        return isinstance(exc, psycopg.OperationalError | PoolTimeout)
    except ImportError:  # pragma: no cover
        return False


class IngestionError(Exception):
    """Expected, user-facing processing failure."""


class IngestionWorker:
    def __init__(
        self,
        store: DocumentStore,
        storage: ObjectStorage,
        embedder: Embedder,
        settings: Settings,
    ):
        self.store = store
        self.storage = storage
        self.embedder = embedder
        self.settings = settings
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._pending: set[UUID] = set()
        self._pending_lock = threading.Lock()
        self._attempts: dict[UUID, int] = {}

    # ---- lifecycle -------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="ingestion-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._queue.put(_STOP)
        if self._thread:
            self._thread.join(timeout)

    def enqueue(self, doc_id: UUID) -> None:
        with self._pending_lock:
            if doc_id in self._pending:
                return  # already queued — prevents duplicate processing
            self._pending.add(doc_id)
        self._queue.put(doc_id)

    def recover(self) -> int:
        """Re-queue documents left queued/processing by a previous crash or restart."""
        ids = self.store.document_ids_with_status(["queued", "processing"])
        for doc_id in ids:
            self.store.update_document(doc_id, status="queued")
            self.enqueue(doc_id)
        if ids:
            logger.info("re-queued %d interrupted documents", len(ids))
        return len(ids)

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            try:
                self.process(item)
            except Exception:  # never let the worker thread die
                logger.exception("worker crashed on document", extra=log_extra(doc_id=str(item)))
            finally:
                with self._pending_lock:
                    self._pending.discard(item)

    # ---- processing ------------------------------------------------------------------
    def process(self, doc_id: UUID) -> None:
        try:
            doc = self.store.get_document(doc_id)
            if doc is None or doc["status"] not in ("queued", "processing"):
                return
            logger.info("processing document", extra=log_extra(doc_id=str(doc_id)))
            self.store.update_document(doc_id, status="processing", error_message=None)
            chunk_count, page_count = self._ingest(doc)
            self.store.update_document(
                doc_id,
                status="ready",
                chunk_count=chunk_count,
                page_count=page_count,
                processed_at=datetime.now(UTC),
                error_message=None,
            )
        except Exception as exc:
            if _is_transient(exc):
                self._retry_later(doc_id, exc)
            else:
                self._fail(doc_id, self._failure_message(doc_id, exc))
            return
        self._attempts.pop(doc_id, None)
        logger.info(
            "document ready",
            extra=log_extra(doc_id=str(doc_id), chunks=chunk_count, pages=page_count),
        )

    def _failure_message(self, doc_id: UUID, exc: Exception) -> str:
        """Map a permanent failure to a message that is safe to show in the UI."""
        if isinstance(exc, IngestionError | PdfValidationError | FileTooLargeError):
            return str(exc)
        if isinstance(exc, StorageError):
            logger.warning("storage error: %s", exc, extra=log_extra(doc_id=str(doc_id)))
            return "Could not retrieve the uploaded file from storage."
        logger.error("ingestion failed", exc_info=exc, extra=log_extra(doc_id=str(doc_id)))
        return "Processing failed due to an internal error."

    def _retry_later(self, doc_id: UUID, exc: Exception) -> None:
        """Network is down: keep the document queued and try again with backoff instead of failing it."""
        attempt = self._attempts.get(doc_id, 0) + 1
        self._attempts[doc_id] = attempt
        delay = min(RETRY_BASE_S * 2 ** (attempt - 1), RETRY_MAX_S)
        logger.warning(
            "transient error (%s) — retrying in %.0fs",
            exc.__class__.__name__,
            delay,
            extra=log_extra(doc_id=str(doc_id), attempt=attempt),
        )
        try:  # best effort: the DB itself may be what is unreachable
            self.store.update_document(
                doc_id, status="queued", error_message="Waiting for network — will retry automatically."
            )
        except Exception:  # noqa: S110 — the DB may be what's down; recover() repairs status later
            pass
        timer = threading.Timer(delay, self.enqueue, args=(doc_id,))
        timer.daemon = True
        timer.start()

    def _ingest(self, doc: dict) -> tuple[int, int]:
        doc_id: UUID = doc["id"]
        with tempfile.TemporaryDirectory(prefix="rag-") as tmp:
            path = Path(tmp) / "document.pdf"
            result = self.storage.download_to(doc["storage_path"], path, self.settings.max_upload_bytes)
            if result.sha256 != doc["sha256"]:
                raise IngestionError("Uploaded file does not match its declared checksum.")
            if result.size != doc["file_size"]:
                self.store.update_document(doc_id, file_size=result.size)

            extracted = extract_pdf(path, self.settings.max_pages)

        chunks = chunk_pages(
            extracted.pages,
            chunk_size=self.settings.chunk_size_chars,
            overlap=self.settings.chunk_overlap_chars,
        )
        if not chunks:
            raise IngestionError("No usable text could be extracted from this PDF.")
        self.store.update_document(doc_id, page_count=extracted.page_count)

        # Idempotent: a reprocess replaces previous chunks.
        self.store.delete_chunks(doc_id)
        for start in range(0, len(chunks), INSERT_BATCH):
            if self.store.get_document(doc_id) is None:
                raise IngestionError("Document was deleted during processing.")
            batch = chunks[start : start + INSERT_BATCH]
            vectors = self.embedder.embed_documents([embedding_text(c, doc["title"]) for c in batch])
            self.store.insert_chunks(doc_id, batch, vectors)
        return len(chunks), extracted.page_count

    def _fail(self, doc_id: UUID, message: str) -> None:
        logger.warning("document failed: %s", message, extra=log_extra(doc_id=str(doc_id)))
        try:
            self.store.delete_chunks(doc_id)
            self.store.update_document(doc_id, status="failed", error_message=message[:500])
        except Exception:
            logger.exception("could not mark document as failed")
