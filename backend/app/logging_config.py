"""Structured JSON logging and a request-id middleware."""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Log JSON to stdout, or — when ``log_file`` is set — to a size-capped rotating file
    (5 MB x 3 backups), so logs can never fill the disk of a long-running home server."""
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
    else:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_extra(**fields) -> dict:
    """Helper: logger.info("msg", extra=log_extra(doc_id=...))."""
    return {"extra_fields": fields}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        logger = logging.getLogger("app.request")
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error", extra=log_extra(path=request.url.path))
            raise
        finally:
            request_id_ctx.reset(token)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        response.headers["x-request-id"] = rid
        if request.url.path != "/api/health":
            logger.info(
                "request",
                extra=log_extra(
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    ms=elapsed,
                ),
            )
        return response
