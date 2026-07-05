"""Periodic Redis pub/sub broadcaster for selection seat-count SSE streams.

One publish per active dept+semester channel every ``SELECTION_SEATS_STREAM_INTERVAL_SECONDS``
so 1 000 SSE clients on the same cohort share a single MGET + PUBLISH tick instead of
each connection polling independently.
"""
from __future__ import annotations

import asyncio
import uuid

from app.core.config import settings
from app.core.logger import logger
from app.services import selection_cache_service as cache_svc

_broadcaster_task: asyncio.Task[None] | None = None

_BROADCAST_LOCK_KEY = "selection:seats:broadcast_tick"


async def start_selection_seats_broadcaster() -> None:
    """Start the background tick loop (idempotent)."""
    global _broadcaster_task
    if _broadcaster_task is not None:
        return
    _broadcaster_task = asyncio.create_task(
        _broadcast_loop(),
        name="selection-seats-broadcaster",
    )
    logger.info(
        "Selection seats broadcaster started",
        interval_seconds=settings.SELECTION_SEATS_STREAM_INTERVAL_SECONDS,
    )


async def stop_selection_seats_broadcaster() -> None:
    """Cancel the background tick loop."""
    global _broadcaster_task
    if _broadcaster_task is None:
        return
    _broadcaster_task.cancel()
    try:
        await _broadcaster_task
    except asyncio.CancelledError:
        pass
    _broadcaster_task = None
    logger.info("Selection seats broadcaster stopped")


async def _broadcast_loop() -> None:
    interval = settings.SELECTION_SEATS_STREAM_INTERVAL_SECONDS
    # Lock TTL must be shorter than the sleep interval so the lock always expires
    # before the next tick fires — prevents every-other-tick skipping.
    lock_ttl = max(1, int(interval * 0.7))

    while True:
        try:
            await asyncio.sleep(interval)
            await _tick_broadcast(lock_ttl)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Selection seats broadcast tick failed", error=str(exc))


async def _tick_broadcast(lock_ttl: int) -> None:
    """Publish full cohort snapshots for every channel with live SSE subscribers."""
    from app.core.redis_client import get_redis  # noqa: PLC0415

    async with get_redis() as r:
        acquired = await r.set(_BROADCAST_LOCK_KEY, "1", nx=True, ex=lock_ttl)
        if not acquired:
            return
        channels = await r.smembers(cache_svc.ACTIVE_SEATS_CHANNELS_KEY)

    for member in channels:
        try:
            dept_str, sem_str = member.split(":", 1)
            dept_id = uuid.UUID(dept_str)
            study_semester = int(sem_str)
        except (ValueError, AttributeError):
            continue

        try:
            await cache_svc.publish_cohort_seat_update(dept_id, study_semester)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Selection seats channel broadcast failed",
                channel=member,
                error=str(exc),
            )
