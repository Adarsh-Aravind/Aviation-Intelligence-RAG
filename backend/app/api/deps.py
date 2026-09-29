from fastapi import HTTPException, Request, status

from app.container import Container
from app.db.repository import DocumentStore
from app.services.ingestion import IngestionWorker
from app.services.rag import RagService
from app.services.storage import ObjectStorage


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_store(request: Request) -> DocumentStore:
    store = get_container(request).store
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not configured")
    return store


def get_storage(request: Request) -> ObjectStorage:
    storage = get_container(request).storage
    if storage is None or not storage.configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "File storage is not configured")
    return storage


def get_worker(request: Request) -> IngestionWorker:
    worker = get_container(request).worker
    if worker is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Ingestion is not available")
    return worker


def get_rag(request: Request) -> RagService:
    rag = get_container(request).rag
    if rag is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Question answering is not available")
    return rag
