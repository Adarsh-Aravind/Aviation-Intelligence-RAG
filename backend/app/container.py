"""Dependency container: built once at startup, swapped for fakes in tests."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.db.repository import DocumentStore
from app.services.embeddings import Embedder
from app.services.flights import FlightFeed
from app.services.ingestion import IngestionWorker
from app.services.rag import RagService
from app.services.storage import ObjectStorage


@dataclass
class Container:
    settings: Settings
    store: DocumentStore | None
    storage: ObjectStorage | None
    embedder: Embedder
    worker: IngestionWorker | None
    rag: RagService | None
    flights: FlightFeed | None = None
