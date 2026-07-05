"""
FastAPI application factory.

Usage:
    uvicorn app.main:app --reload
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
"""

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.routes import v1_router
from app.core.config import settings
from app.core.exceptions import AppError, app_exception_handler, unhandled_exception_handler
from app.core.logger import logger
from app.core.rate_limiter import limiter
from app.core.request_context import set_request_context
from app.db.session import close_db, init_db


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown logic for the FastAPI application."""
    # --- Startup ---
    logger.info("Starting Exovance Scheduler API", env=settings.APP_ENV)

    await init_db()
    logger.info("Database connection pool initialised")

    # Initialise LangGraph checkpointer (AsyncPostgresSaver + psycopg pool).
    try:
        from agent_service.checkpointer import init_checkpointer  # noqa: PLC0415
        await init_checkpointer()  # setup() runs internally with autocommit
        logger.info("LangGraph checkpointer initialised")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "LangGraph checkpointer unavailable — agent state will not persist",
            error=str(exc),
        )

    # Ping Celery broker — warn but don't crash on failure.
    try:
        from celery import Celery  # noqa: PLC0415
        celery_app = Celery(broker=settings.CELERY_BROKER_URL)
        celery_app.control.inspect(timeout=2).ping()
        logger.info("Celery broker reachable", broker=settings.CELERY_BROKER_URL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Celery broker not reachable — background tasks will queue when available", error=str(exc))

    from app.services.selection_seats_broadcaster import start_selection_seats_broadcaster  # noqa: PLC0415
    await start_selection_seats_broadcaster()

    yield

    # --- Shutdown ---
    from app.services.selection_seats_broadcaster import stop_selection_seats_broadcaster  # noqa: PLC0415
    await stop_selection_seats_broadcaster()

    from agent_service.checkpointer import close_checkpointer  # noqa: PLC0415
    await close_checkpointer()

    await close_db()
    logger.info("Database connection pool closed")

    from app.core.redis_client import close_redis_pool  # noqa: PLC0415
    await close_redis_pool()
    logger.info("Redis connection pool closed")


# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique X-Request-ID to every request and response."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# Request-context middleware (IP + User-Agent for audit logs)
# ---------------------------------------------------------------------------

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Populate per-request context vars used by audit_log_service."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # X-Forwarded-For is set by reverse proxies (nginx, AWS ALB, Cloudflare).
        # Take the first (leftmost) value — the original client IP.
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
        else:
            ip = (
                request.headers.get("X-Real-IP")
                or (request.client.host if request.client else None)
            )
        user_agent = request.headers.get("User-Agent")
        set_request_context(ip, user_agent)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    _is_prod = settings.APP_ENV == "production"
    app = FastAPI(
        title="Exovance Scheduler API",
        description=(
            "Agentic AI University Timetable Scheduler. "
            "Powered by OR-Tools CP-SAT and LangGraph."
        ),
        version="0.1.0",
        docs_url=None if _is_prod else "/api/docs",
        redoc_url=None if _is_prod else "/api/redoc",
        openapi_url=None if _is_prod else "/api/openapi.json",
        lifespan=lifespan,
    )

    # --- Rate limiter ---
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # --- Middleware (registered in outer-to-inner execution order) ---
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers ---
    app.add_exception_handler(AppError, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]

    # --- Routers ---
    app.include_router(v1_router, prefix="/api/v1")

    # --- Health check (no auth required) ---
    @app.get("/health", tags=["health"], summary="Liveness probe")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": "0.1.0"})

    return app

app = create_app()
