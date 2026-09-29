import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_rag
from app.logging_config import log_extra
from app.models.schemas import ChatRequest, ChatResponse
from app.rate_limit import chat_limit, limiter
from app.security import require_api_key
from app.services.llm import LLMError
from app.services.rag import RagService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"], dependencies=[Depends(require_api_key)])


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(chat_limit)
def chat(request: Request, body: ChatRequest, rag: RagService = Depends(get_rag)) -> ChatResponse:
    try:
        result = rag.answer(body.question)
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    logger.info(
        "chat answered",
        extra=log_extra(
            status=result.status,
            grounded=result.grounded,
            cited=len(result.citations),
            total_ms=result.timings.total_ms,
        ),
    )
    return result
