"""
app/api/v1/routes/notifications.py
=====================================
User notification CRUD + SSE stream.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_current_user, get_db
from app.core.config import settings
from app.models.notification import NotificationType
from app.schemas.notification import (
    NotificationListResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    NotificationResponse,
)
from app.services import notification_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Notification list + mark-read
# ---------------------------------------------------------------------------

@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    unread_only: bool = Query(False),
    notification_type: NotificationType | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
) -> NotificationListResponse:
    user_id = uuid.UUID(current_user.user_id)
    inst_id = uuid.UUID(current_user.institution_id)
    items, total, unread_count = await notification_service.get_notifications(
        db,
        user_id,
        institution_id=inst_id,
        role=current_user.role,
        department_id=department_id,
        unread_only=unread_only,
        notification_type=notification_type,
        skip=skip,
        limit=limit,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
        unread_count=unread_count,
        skip=skip,
        limit=limit,
    )


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    user_id = uuid.UUID(current_user.user_id)
    await notification_service.mark_read(db, notification_id, user_id)
    await db.commit()
    return Response(status_code=204)


@router.post("/read-all")
async def mark_all_notifications_read(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    user_id = uuid.UUID(current_user.user_id)
    inst_id = uuid.UUID(current_user.institution_id)
    await notification_service.mark_all_read(
        db, user_id,
        institution_id=inst_id,
        role=current_user.role,
    )
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@router.get("/preferences", response_model=NotificationPreferenceResponse)
async def get_preferences(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferenceResponse:
    user_id = uuid.UUID(current_user.user_id)
    pref = await notification_service.get_or_create_preferences(db, user_id)
    await db.commit()
    return NotificationPreferenceResponse(
        id=pref.id,
        user_id=pref.user_id,
        email_enabled=pref.email_enabled,
        push_enabled=pref.push_enabled,
        disabled_types=pref.disabled_types or [],
    )


@router.put("/preferences", response_model=NotificationPreferenceResponse)
async def update_preferences(
    payload: NotificationPreferenceUpdate,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferenceResponse:
    user_id = uuid.UUID(current_user.user_id)
    pref = await notification_service.get_or_create_preferences(db, user_id)
    if payload.email_enabled is not None:
        pref.email_enabled = payload.email_enabled
    if payload.push_enabled is not None:
        pref.push_enabled = payload.push_enabled
    if payload.disabled_types is not None:
        pref.disabled_types = payload.disabled_types
    await db.commit()
    await db.refresh(pref)
    return NotificationPreferenceResponse(
        id=pref.id,
        user_id=pref.user_id,
        email_enabled=pref.email_enabled,
        push_enabled=pref.push_enabled,
        disabled_types=pref.disabled_types or [],
    )


# ---------------------------------------------------------------------------
# SSE real-time stream
# ---------------------------------------------------------------------------

@router.get("/stream")
async def notification_stream(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> StreamingResponse:
    """
    Server-Sent Events stream for real-time notifications.

    Connects to Redis pub/sub channel ``notifications:{user_id}``.
    Notifications are pushed instantly on create; a heartbeat is sent every
    ``NOTIFICATION_STREAM_HEARTBEAT_SECONDS`` (default 30 s) when idle.
    Reconnects are handled by the client.
    """
    user_id = current_user.user_id
    heartbeat_seconds = settings.NOTIFICATION_STREAM_HEARTBEAT_SECONDS

    async def _event_generator() -> AsyncGenerator[str, None]:
        from app.core.logger import logger  # noqa: PLC0415
        from app.core.redis_client import create_pubsub_redis  # noqa: PLC0415

        r = create_pubsub_redis()
        pubsub = r.pubsub()
        channel = f"notifications:{user_id}"
        try:
            await pubsub.subscribe(channel)
            yield "event: connected\ndata: {}\n\n"

            while True:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=heartbeat_seconds
                    )
                    if message and message.get("type") == "message":
                        data = message.get("data", "{}")
                        yield f"data: {data}\n\n"
                    else:
                        yield ": heartbeat\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Notification stream pub/sub error — retrying",
                        error=str(exc),
                        channel=channel,
                    )
                    await asyncio.sleep(1)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
            try:
                await r.aclose()
            except Exception:
                pass

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
