"""Per-client rate limiting (in-memory; fine for a single-process deployment)."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import get_settings


def client_key(request: Request) -> str:
    # The Next.js proxy forwards the real browser IP. Routes using this key require the API key,
    # so only the trusted proxy can set this header.
    return request.headers.get("x-client-ip") or get_remote_address(request)


limiter = Limiter(key_func=client_key, headers_enabled=False)


def chat_limit() -> str:
    return get_settings().chat_rate_limit
