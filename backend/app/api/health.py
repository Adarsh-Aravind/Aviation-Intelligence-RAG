from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_store
from app.container import Container
from app.db.repository import DocumentStore
from app.models.schemas import HealthResponse, StatsResponse
from app.security import require_api_key

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(container: Container = Depends(get_container)) -> HealthResponse:
    s = container.settings
    db_ok = container.store.ping() if container.store else False
    storage_ok = bool(container.storage and container.storage.configured)
    embedder_ok = container.embedder.loaded
    healthy = db_ok and embedder_ok and storage_ok and s.llm_configured
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version=s.app_version,
        database=db_ok,
        embedder_loaded=embedder_ok,
        embedding_model=s.embedding_model,
        llm_configured=s.llm_configured,
        llm_model=s.groq_model,
        storage_configured=storage_ok,
    )


@router.get("/stats", response_model=StatsResponse, dependencies=[Depends(require_api_key)])
def stats(
    container: Container = Depends(get_container),
    store: DocumentStore = Depends(get_store),
) -> StatsResponse:
    data = store.stats()
    return StatsResponse(
        documents_total=sum(data["by_status"].values()),
        documents_by_status=data["by_status"],
        chunks_total=data["chunks_total"],
        pages_total=data["pages_total"],
        embedding_model=container.settings.embedding_model,
        llm_model=container.settings.groq_model,
    )
