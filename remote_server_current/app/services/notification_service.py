"""
app/services/notification_service.py
======================================
Create and manage user-facing notifications.

Delivery model:
  1. IN_APP  — write Notification row; frontend polls or SSE-streams
  2. EMAIL   — enqueue Celery task send_email_notification (if user pref allows)
  3. PUSH    — future (FCM/APNs token not yet stored)

send() and send_to_role() never raise — individual delivery failures are
logged at WARNING so they don't abort the triggering domain operation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TypedDict

import redis.asyncio as aioredis

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationType,
)
from app.models.user import User, UserRole


# Default channels when caller does not specify
_DEFAULT_CHANNELS = [NotificationChannel.IN_APP, NotificationChannel.EMAIL]
_PENDING_NOTIFICATION_DISPATCHES_KEY = "pending_notification_dispatches"


class PendingNotificationDispatch(TypedDict):
    recipient_ids: list[uuid.UUID]
    notification_type: NotificationType
    title: str
    body: str
    metadata: dict[str, Any] | None
    notification_ids_for_email: list[uuid.UUID]


async def send(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    notification_type: NotificationType,
    recipients: list[User],
    title: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    channels: list[NotificationChannel] | None = None,
) -> None:
    """
    Create Notification rows for each recipient and enqueue email tasks.

    Never raises — failures are swallowed and logged.
    """
    if not recipients:
        return

    resolved_channels = channels if channels is not None else _DEFAULT_CHANNELS

    try:
        # Load preferences for all recipients in one query
        recipient_ids = [r.id for r in recipients]
        prefs_result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id.in_(recipient_ids)
            )
        )
        prefs_map: dict[uuid.UUID, NotificationPreference] = {
            p.user_id: p for p in prefs_result.scalars().all()
        }

        notification_ids_for_email: list[uuid.UUID] = []

        for user in recipients:
            pref = prefs_map.get(user.id)
            disabled = set(pref.disabled_types or []) if pref else set()

            if notification_type.value in disabled:
                continue  # user muted this type

            for channel in resolved_channels:
                if channel == NotificationChannel.EMAIL:
                    # Skip email if user opted out
                    if pref and not pref.email_enabled:
                        continue

                notif = Notification(
                    institution_id=institution_id,
                    recipient_user_id=user.id,
                    notification_type=notification_type,
                    title=title,
                    body=body,
                    metadata_=metadata,
                    channel=channel,
                )
                db.add(notif)
                await db.flush()

                if channel == NotificationChannel.EMAIL:
                    notification_ids_for_email.append(notif.id)

        _queue_pending_dispatch(
            db,
            recipient_ids=recipient_ids,
            notification_type=notification_type,
            title=title,
            body=body,
            metadata=metadata,
            notification_ids_for_email=notification_ids_for_email,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notification_service.send failed",
            notification_type=notification_type.value,
            error=str(exc),
        )


async def dispatch_pending(db: AsyncSession) -> None:
    """Flush queued realtime/email notification side effects after commit."""
    pending: list[PendingNotificationDispatch] = db.info.pop(
        _PENDING_NOTIFICATION_DISPATCHES_KEY,
        [],
    )

    for item in pending:
        await _publish_to_redis(
            recipient_ids=item["recipient_ids"],
            notification_type=item["notification_type"],
            title=item["title"],
            body=item["body"],
            metadata=item["metadata"],
        )

        if item["notification_ids_for_email"]:
            _enqueue_email_tasks(item["notification_ids_for_email"])


async def send_to_role(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    role: UserRole,
    notification_type: NotificationType,
    title: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Resolve all active users with *role* in *institution_id*, then call send().
    """
    try:
        role_filter = User.role == role
        if role == UserRole.ADMIN:
            role_filter = or_(User.role == UserRole.ADMIN, User.role == UserRole.SUPER_ADMIN)

        result = await db.execute(
            select(User).where(
                User.institution_id == institution_id,
                role_filter,
                User.is_active == True,  # noqa: E712
            )
        )
        recipients = list(result.scalars().all())
        await send(
            db,
            institution_id=institution_id,
            notification_type=notification_type,
            recipients=recipients,
            title=title,
            body=body,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notification_service.send_to_role failed",
            role=role.value,
            notification_type=notification_type.value,
            error=str(exc),
        )


async def mark_read(
    db: AsyncSession,
    notification_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    await db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.recipient_user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )


async def mark_all_read(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    institution_id: uuid.UUID | None = None,
    role: UserRole | None = None,
) -> None:
    is_admin = role in (UserRole.ADMIN, UserRole.SUPER_ADMIN) if role else False
    if is_admin and institution_id:
        where_clause = and_(
            Notification.institution_id == institution_id,
            Notification.is_read == False,  # noqa: E712
        )
    else:
        where_clause = and_(
            Notification.recipient_user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
    await db.execute(
        update(Notification)
        .where(where_clause)
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )


async def get_unread(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    institution_id: uuid.UUID | None = None,
    role: UserRole | None = None,
    limit: int = 50,
) -> list[Notification]:
    is_admin = role in (UserRole.ADMIN, UserRole.SUPER_ADMIN) if role else False

    if is_admin and institution_id:
        base = select(Notification).where(
            Notification.institution_id == institution_id,
            Notification.is_read == False,  # noqa: E712
            Notification.channel == NotificationChannel.IN_APP,
        )
    else:
        base = select(Notification).where(
            Notification.recipient_user_id == user_id,
            Notification.is_read == False,  # noqa: E712
            Notification.channel == NotificationChannel.IN_APP,
        )
    result = await db.execute(
        base.order_by(Notification.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    institution_id: uuid.UUID,
    role: UserRole,
    department_id: uuid.UUID | None = None,
    unread_only: bool = False,
    notification_type: NotificationType | None = None,
    skip: int = 0,
    limit: int = 25,
) -> tuple[list[Notification], int, int]:
    """Returns (items, total, unread_count).

    Role-based scoping:
      ADMIN/SUPER_ADMIN → all notifications in the institution
      HOD              → own notifications + notifications for department members
      TEACHER/STUDENT  → own notifications only (current behavior)
    """
    is_admin = role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)

    if is_admin:
        base = select(Notification).where(
            Notification.institution_id == institution_id,
            Notification.channel == NotificationChannel.IN_APP,
        )
        unread_base = select(func.count()).where(
            Notification.institution_id == institution_id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.is_read == False,  # noqa: E712
        )
    elif role == UserRole.HOD:
        dept_filter = department_id
        if not dept_filter:
            user_dept = await db.execute(
                select(User.department_id).where(User.id == user_id)
            )
            dept_filter = user_dept.scalar_one_or_none()
        if dept_filter:
            dept_user_ids_q = select(User.id).where(
                User.department_id == dept_filter,
                User.is_active == True,  # noqa: E712
            )
            dept_user_ids = (await db.execute(dept_user_ids_q)).scalars().all()
            base = select(Notification).where(
                or_(
                    Notification.recipient_user_id == user_id,
                    Notification.recipient_user_id.in_(dept_user_ids),
                ),
                Notification.channel == NotificationChannel.IN_APP,
            )
            unread_base = select(func.count()).where(
                or_(
                    Notification.recipient_user_id == user_id,
                    Notification.recipient_user_id.in_(dept_user_ids),
                ),
                Notification.channel == NotificationChannel.IN_APP,
                Notification.is_read == False,  # noqa: E712
            )
        else:
            base = select(Notification).where(
                Notification.recipient_user_id == user_id,
                Notification.channel == NotificationChannel.IN_APP,
            )
            unread_base = select(func.count()).where(
                Notification.recipient_user_id == user_id,
                Notification.channel == NotificationChannel.IN_APP,
                Notification.is_read == False,  # noqa: E712
            )
    else:
        base = select(Notification).where(
            Notification.recipient_user_id == user_id,
            Notification.channel == NotificationChannel.IN_APP,
        )
        unread_base = select(func.count()).where(
            Notification.recipient_user_id == user_id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.is_read == False,  # noqa: E712
        )

    if unread_only:
        base = base.where(Notification.is_read == False)  # noqa: E712
    if notification_type is not None:
        base = base.where(Notification.notification_type == notification_type)

    count_q = select(func.count()).select_from(base.subquery())

    items_result = await db.execute(
        base.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
    )
    total_result = await db.execute(count_q)
    unread_result = await db.execute(unread_base)

    return (
        list(items_result.scalars().all()),
        total_result.scalar_one(),
        unread_result.scalar_one(),
    )


async def get_or_create_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> NotificationPreference:
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    pref = result.scalars().first()
    if pref is None:
        pref = NotificationPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    return pref


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _publish_to_redis(
    *,
    recipient_ids: list[uuid.UUID],
    notification_type: NotificationType,
    title: str,
    body: str,
    metadata: dict[str, Any] | None,
) -> None:
    """Publish to Redis pub/sub channel so SSE endpoints receive real-time updates."""
    import json
    from app.core.redis_client import get_async_redis

    payload = json.dumps({
        "notification_type": notification_type.value,
        "title": title,
        "body": body,
        "metadata": metadata or {},
    })

    r: aioredis.Redis | None = None
    try:
        r = get_async_redis()
        for recipient_id in recipient_ids:
            channel = f"notifications:{recipient_id}"
            await r.publish(channel, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notification redis publish failed", error=str(exc))
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


def _enqueue_email_tasks(notification_ids: list[uuid.UUID]) -> None:
    """Fire-and-forget: enqueue Celery email tasks."""
    try:
        from tasks.notification_tasks import send_email_notification  # noqa: PLC0415
        for nid in notification_ids:
            send_email_notification.delay(str(nid))
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to enqueue email notification tasks", error=str(exc))


def _queue_pending_dispatch(
    db: AsyncSession,
    *,
    recipient_ids: list[uuid.UUID],
    notification_type: NotificationType,
    title: str,
    body: str,
    metadata: dict[str, Any] | None,
    notification_ids_for_email: list[uuid.UUID],
) -> None:
    pending: list[PendingNotificationDispatch] = db.info.setdefault(
        _PENDING_NOTIFICATION_DISPATCHES_KEY,
        [],
    )
    pending.append(
        PendingNotificationDispatch(
            recipient_ids=recipient_ids,
            notification_type=notification_type,
            title=title,
            body=body,
            metadata=metadata,
            notification_ids_for_email=notification_ids_for_email,
        )
    )
