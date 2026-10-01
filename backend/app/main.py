"""FastAPI application entry point."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from slowapi.errors import RateLimitExceeded

from app.api import chat, documents, health
from app.config import Settings, get_settings
from app.container import Container
from app.logging_config import RequestContextMiddleware, configure_logging
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

MAINTENANCE_INTERVAL_S = 3600
WATCHDOG_INTERVAL_S = 60
STALE_UPLOAD_MINUTES = 60


def build_container(settings: Settings) -> Container:
    """Wire real implementations. Heavy imports stay inside so tests never load them."""
    from app.db.pool import create_pool
    from app.db.repository import PgDocumentStore
    from app.services.embeddings import FastEmbedEmbedder
    from app.services.ingestion import IngestionWorker
    from app.services.llm import GroqLLM
    from app.services.rag import RagService
    from app.services.retrieval import Retriever
    from app.services.storage import SupabaseStorage

    store = None
    if settings.database_url:
        store = PgDocumentStore(
            create_pool(settings.database_url, settings.db_pool_min, settings.db_pool_max)
        )
    else:
        logger.error("DATABASE_URL is not set — database features are disabled")

    storage = SupabaseStorage(
        settings.supabase_url, settings.supabase_service_role_key, settings.supabase_bucket
    )
    embedder = FastEmbedEmbedder(
        model_name=settings.embedding_model,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
        threads=settings.embedding_threads,
        cache_dir=settings.embedding_cache_dir,
        query_prefix=settings.embedding_query_prefix,
    )
    llm = (
        GroqLLM(
            settings.groq_api_key,
            settings.groq_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_s,
            reasoning_effort=settings.llm_reasoning_effort,
            fallback_models=settings.groq_fallback_models,
        )
        if settings.llm_configured
        else None
    )
    worker = rag = None
    if store is not None:
        worker = IngestionWorker(store, storage, embedder, settings)
        retriever = Retriever(
            store,
            embedder,
            candidates=settings.retrieval_candidates,
            top_k=settings.retrieval_top_k,
            min_relevance=settings.min_relevance,
        )
        rag = RagService(retriever, llm)
    return Container(settings, store, storage, embedder, worker, rag)


def _retry_until_done(name: str, fn, stop: threading.Event, max_delay: float = 60.0) -> None:
    """Run ``fn`` until it succeeds. At boot the home network (or Wi-Fi) may not be up yet."""
    delay = 2.0
    while not stop.is_set():
        try:
            fn()
            return
        except Exception as exc:
            logger.warning("%s failed (%s) — retrying in %.0fs", name, exc.__class__.__name__, delay)
            stop.wait(delay)
            delay = min(delay * 2, max_delay)


def _purge_abandoned_uploads(container: Container) -> None:
    store, storage = container.store, container.storage
    if store is None:
        return
    for doc in store.stale_awaiting_uploads(STALE_UPLOAD_MINUTES):
        store.delete_document(doc["id"])
        if storage is not None and storage.configured:
            try:
                storage.delete(doc["storage_path"])
            except Exception as exc:
                logger.warning("could not delete abandoned object: %s", exc)
        logger.info("purged abandoned upload %s", doc["id"])


def _maintenance_loop(container: Container, stop: threading.Event) -> None:
    """Every minute: DB watchdog (keeps the pool reconnecting after internet outages and logs
    offline/online transitions). Hourly: purge abandoned uploads — this also keeps a free-tier
    Supabase project from pausing."""
    online = True
    ticks = 0
    while not stop.wait(WATCHDOG_INTERVAL_S):
        ticks += 1
        if container.store is None:
            continue
        ok = container.store.ping()
        if ok != online:
            online = ok
            if ok:
                logger.info("database reachable again")
                if container.worker is not None:  # resume anything that was waiting for the network
                    _retry_until_done("recover documents", container.worker.recover, stop)
            else:
                logger.warning("database unreachable (internet outage?) — will keep retrying")
        if ok and ticks * WATCHDOG_INTERVAL_S >= MAINTENANCE_INTERVAL_S:
            ticks = 0
            try:
                _purge_abandoned_uploads(container)
            except Exception:
                logger.exception("maintenance task failed")


def _startup(container: Container) -> threading.Event:
    settings = container.settings
    stop = threading.Event()

    def warm() -> None:
        # Model loads from the local cache, so this works offline after the first download.
        _retry_until_done("load embedding model", container.embedder.load, stop, max_delay=300)  # type: ignore[attr-defined]
        if container.worker is not None:
            container.worker.start()
            # After a power cut: re-queue documents that were mid-processing.
            _retry_until_done("recover documents", container.worker.recover, stop)
        storage = container.storage
        if storage is not None and storage.configured:
            _retry_until_done(
                "verify storage bucket",
                lambda: storage.ensure_bucket(settings.max_upload_bytes),  # type: ignore[attr-defined]
                stop,
            )

    # Load the model off the event loop so the API (and /health) come up immediately.
    threading.Thread(target=warm, name="warmup", daemon=True).start()
    threading.Thread(
        target=_maintenance_loop, args=(container, stop), name="maintenance", daemon=True
    ).start()
    return stop


def create_app(container: Container | None = None) -> FastAPI:
    settings = container.settings if container else get_settings()
    configure_logging(settings.log_level, settings.log_file)
    managed = container is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = None
        if managed:
            app.state.container = build_container(settings)
            stop = _startup(app.state.container)
        yield
        if stop is not None:
            stop.set()
            c: Container = app.state.container
            if c.worker is not None:
                c.worker.stop()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment == "development" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.environment == "development" else None,
    )
    if container is not None:
        app.state.container = container

    app.state.limiter = limiter
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["content-type", "x-api-key", "x-admin-key", "x-request-id"],
    )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many questions — please wait a moment and try again."},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": "Invalid request", "errors": errors})

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def database_unavailable(request: Request, exc: Exception):
        logger.warning("database unavailable: %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=503,
            content={"detail": "The database is temporarily unreachable. Please try again in a minute."},
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled exception")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(health.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    return app


app = create_app()
