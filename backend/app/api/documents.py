"""Document library endpoints.

Upload flow (keeps large files off the Vercel proxy, which caps bodies at ~4.5 MB):
  1. POST /documents/init     → validates metadata + dedupes by SHA-256, returns a signed upload URL
  2. browser PUTs the PDF directly to Supabase Storage
  3. POST /documents/{id}/complete → queues background processing (verification happens in the worker)
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from pathlib import PurePath
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_container, get_storage, get_store, get_worker
from app.container import Container
from app.db.repository import DocumentStore
from app.logging_config import log_extra
from app.models.schemas import (
    DocumentList,
    DocumentOut,
    FileUrlResponse,
    UploadInitRequest,
    UploadInitResponse,
)
from app.security import require_admin, require_api_key
from app.services.ingestion import IngestionWorker
from app.services.storage import ObjectStorage, StorageError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_api_key)])

ALLOWED_CONTENT_TYPES = {"application/pdf"}
ALLOWED_EXTENSIONS = {".pdf"}
SIGNED_READ_SECONDS = 600


def sanitize_filename(name: str) -> str:
    """Strip paths, control characters and anything outside a conservative character set."""
    name = unicodedata.normalize("NFKC", name)
    name = PurePath(name.replace("\\", "/")).name
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r"[^\w\-. ()\[\]]", "_", name).strip(" .")
    name = re.sub(r"_+", "_", name)
    if not name:
        name = "document.pdf"
    if len(name) > 150:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 150 - len(ext) - 1] + dot + ext) if dot else name[:150]
    return name


def title_from_filename(filename: str) -> str:
    stem = PurePath(filename).stem
    return re.sub(r"[_\-]+", " ", stem).strip()[:200] or "Untitled document"


def _get_or_404(store: DocumentStore, doc_id: UUID) -> dict:
    doc = store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("", response_model=DocumentList)
def list_documents(store: DocumentStore = Depends(get_store)) -> DocumentList:
    items = [DocumentOut.model_validate(d) for d in store.list_documents()]
    return DocumentList(items=items, total=len(items))


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: UUID, store: DocumentStore = Depends(get_store)) -> DocumentOut:
    return DocumentOut.model_validate(_get_or_404(store, doc_id))


@router.get("/{doc_id}/file-url", response_model=FileUrlResponse)
def get_file_url(
    doc_id: UUID,
    store: DocumentStore = Depends(get_store),
    storage: ObjectStorage = Depends(get_storage),
) -> FileUrlResponse:
    doc = _get_or_404(store, doc_id)
    if doc["status"] == "awaiting_upload":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document file not available")
    try:
        url = storage.create_signed_read_url(doc["storage_path"], SIGNED_READ_SECONDS)
    except StorageError as exc:
        logger.warning("sign read failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not create a download link") from exc
    return FileUrlResponse(url=url, expires_in=SIGNED_READ_SECONDS)


@router.post(
    "/init",
    response_model=UploadInitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def init_upload(
    body: UploadInitRequest,
    container: Container = Depends(get_container),
    store: DocumentStore = Depends(get_store),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadInitResponse:
    settings = container.settings
    filename = sanitize_filename(body.filename)
    if PurePath(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are supported")
    if body.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are supported")
    if body.file_size > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds the {settings.max_upload_mb} MB limit"
        )

    existing = store.get_document_by_sha(body.sha256)
    if existing and existing["status"] != "awaiting_upload":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": f"This file has already been uploaded as “{existing['title']}”.",
                "document_id": str(existing["id"]),
            },
        )

    title = (body.title or "").strip() or title_from_filename(filename)
    description = (body.description or "").strip() or None
    if existing:  # a previous upload of the same file was interrupted — reuse the row
        doc = existing
    else:
        doc_id = uuid.uuid4()
        doc = store.create_document(
            doc_id=doc_id,
            title=title,
            description=description,
            original_filename=filename,
            storage_path=f"{doc_id}.pdf",  # never derived from user input
            file_type="application/pdf",
            file_size=body.file_size,
            sha256=body.sha256,
        )
    try:
        upload_url = storage.create_signed_upload_url(doc["storage_path"])
    except StorageError as exc:
        logger.warning("sign upload failed: %s", exc)
        if not existing:
            store.delete_document(doc["id"])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not prepare the upload") from exc

    logger.info("upload initialised", extra=log_extra(doc_id=str(doc["id"]), size=body.file_size))
    return UploadInitResponse(document=DocumentOut.model_validate(doc), upload_url=upload_url)


@router.post(
    "/{doc_id}/complete",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
def complete_upload(
    doc_id: UUID,
    store: DocumentStore = Depends(get_store),
    worker: IngestionWorker = Depends(get_worker),
) -> DocumentOut:
    doc = _get_or_404(store, doc_id)
    if doc["status"] != "awaiting_upload":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is already {doc['status']}")
    store.update_document(doc_id, status="queued")
    worker.enqueue(doc_id)
    return DocumentOut.model_validate({**doc, "status": "queued"})


@router.post(
    "/{doc_id}/reprocess",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
def reprocess(
    doc_id: UUID,
    store: DocumentStore = Depends(get_store),
    worker: IngestionWorker = Depends(get_worker),
) -> DocumentOut:
    doc = _get_or_404(store, doc_id)
    if doc["status"] not in ("failed", "ready"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is {doc['status']}")
    store.update_document(doc_id, status="queued", error_message=None)
    worker.enqueue(doc_id)
    return DocumentOut.model_validate({**doc, "status": "queued", "error_message": None})


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_document(
    doc_id: UUID,
    store: DocumentStore = Depends(get_store),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    doc = _get_or_404(store, doc_id)
    store.delete_document(doc_id)  # chunks cascade
    try:
        storage.delete(doc["storage_path"])
    except StorageError as exc:  # row is gone; an orphaned object is harmless and logged
        logger.warning("storage delete failed: %s", exc, extra=log_extra(doc_id=str(doc_id)))
    logger.info("document deleted", extra=log_extra(doc_id=str(doc_id)))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
