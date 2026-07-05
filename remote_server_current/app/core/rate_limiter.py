"""
app/core/rate_limiter.py
========================
Shared slowapi Limiter instance used by auth (and any other) endpoints.

Storage: Redis DB 2 (separate from Celery broker/result DBs) so rate-limit
counters survive server restarts and are shared across multiple uvicorn workers.

Key function: respects X-Forwarded-For / X-Real-IP set by nginx or a load
balancer, falling back to the direct client IP.
"""

from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request

from app.core.config import settings


def _real_ip(request: Request) -> str:
    """Extract the originating client IP, honouring reverse-proxy headers."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return (
        request.headers.get("X-Real-IP")
        or (request.client.host if request.client else "unknown")
    )


limiter = Limiter(
    key_func=_real_ip,
    storage_uri=settings.RATE_LIMIT_REDIS_URL,
    default_limits=[],  # no global default — limits are declared per endpoint
)
