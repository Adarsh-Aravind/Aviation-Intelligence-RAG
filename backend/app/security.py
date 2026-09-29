"""Request authentication.

The public never talks to this API directly: the Next.js server-side proxy adds ``X-API-Key`` to every
request and ``X-Admin-Key`` only for a logged-in admin. Keys are compared in constant time.
"""

import secrets

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings


def _settings(request: Request) -> Settings:
    return request.app.state.container.settings


def _matches(provided: str | None, expected: str) -> bool:
    return bool(provided) and secrets.compare_digest(provided.encode(), expected.encode())


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(_settings),
) -> None:
    if not settings.backend_api_key:
        if settings.environment == "development":
            return  # convenience for local dev only
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API key is not configured")
    if not _matches(x_api_key, settings.backend_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")


def require_admin(
    x_admin_key: str | None = Header(default=None),
    settings: Settings = Depends(_settings),
) -> None:
    if not settings.backend_admin_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access is not configured")
    if not _matches(x_admin_key, settings.backend_admin_key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required")
