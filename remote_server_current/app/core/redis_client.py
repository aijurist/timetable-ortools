"""
app/core/redis_client.py
========================
Shared Redis client helpers.

Uses a shared async ConnectionPool so each request/coroutine does NOT open a
new TCP connection.  The pool is lazily initialised on first use and shared
across all coroutines in a single uvicorn worker process.

Calling patterns
----------------
* New code:  async with get_redis() as r:  await r.get(key)
* Legacy code:  r = get_async_redis(); … await r.aclose()   ← still works;
  aclose() on a pool-backed client releases the slot back to the pool.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis
import redis.asyncio as aioredis

from app.core.config import settings

# ---------------------------------------------------------------------------
# Sync client — Celery task context (blocking, no pool needed)
# ---------------------------------------------------------------------------

def get_sync_redis() -> redis.Redis:
    """Sync Redis client safe for Celery task context (blocking calls)."""
    return redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)


# ---------------------------------------------------------------------------
# Shared async connection pool (one per process)
# ---------------------------------------------------------------------------

_async_pool: aioredis.ConnectionPool | None = None


def _get_async_pool() -> aioredis.ConnectionPool:
    """Lazily create and return the shared async Redis connection pool.

    ConnectionPool creation is synchronous in redis-py — no event loop needed.
    max_connections=50 supports 1 000 concurrent users while keeping Redis
    memory overhead low (~750 KB).
    """
    global _async_pool
    if _async_pool is None:
        _async_pool = aioredis.ConnectionPool.from_url(
            settings.CELERY_BROKER_URL,
            decode_responses=True,
            max_connections=100,
        )
    return _async_pool


def get_async_redis() -> aioredis.Redis:
    """Return an async Redis client backed by the shared pool.

    Callers MUST still call ``await client.aclose()`` when done — this returns
    the connection to the pool rather than destroying it.

    DO NOT use this for pub/sub.  Use ``create_pubsub_redis()`` instead.
    """
    return aioredis.Redis(connection_pool=_get_async_pool())


def create_pubsub_redis() -> aioredis.Redis:
    """Create a **dedicated** Redis client for pub/sub subscriptions.

    Pub/sub requires a connection that is held open for the entire subscription
    lifetime — it cannot share the command pool.  This factory creates a
    single-connection client that is owned by the caller and must be closed
    (``await client.aclose()``) when the subscription ends.

    Each SSE endpoint that calls ``r.pubsub()`` must use this, never
    ``get_async_redis()``, to avoid exhausting the shared pool.
    """
    return aioredis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)


@asynccontextmanager
async def get_redis() -> AsyncIterator[aioredis.Redis]:
    """Async context manager — borrow a connection from the shared pool.

    Preferred over ``get_async_redis()`` for new code; guarantees release even
    when an exception is raised.

    Usage::

        async with get_redis() as r:
            value = await r.get("my-key")
    """
    client = get_async_redis()
    try:
        yield client
    finally:
        await client.aclose()


async def close_redis_pool() -> None:
    """Gracefully disconnect the shared pool — call from app shutdown lifespan."""
    global _async_pool
    if _async_pool is not None:
        await _async_pool.aclose()
        _async_pool = None


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def solver_stream_key(job_id: str) -> str:
    """Redis Stream key for a solver job's progress events."""
    return f"solver:stream:{job_id}"


def solver_cancel_key(job_id: str) -> str:
    """Redis flag key — set by the cancel API, polled by the Celery task."""
    return f"solver:cancel:{job_id}"


def offering_seats_key(offering_id: str | object) -> str:
    """Canonical Redis key for a CourseOffering's remaining-seat counter."""
    return f"offering:seats:{offering_id}"
