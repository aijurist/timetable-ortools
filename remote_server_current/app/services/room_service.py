"""
app/services/room_service.py
==============================
CRUD operations for Room solver resources.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logger import logger
from app.models.room import Room, RoomType
from app.schemas.room import RoomCreate, RoomUpdate


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def list_distinct_buildings(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    active_only: bool = True,
) -> list[str]:
    q = (
        select(Room.building)
        .distinct()
        .where(
            Room.institution_id == institution_id,
            Room.building.isnot(None),
        )
    )
    if active_only:
        q = q.where(Room.is_active == True)  # noqa: E712
    q = q.order_by(Room.building)
    result = await db.execute(q)
    return [row[0] for row in result.all()]


async def get_type_counts(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    active_only: bool = True,
) -> dict[str, int]:
    q = select(Room.room_type, func.count()).where(
        Room.institution_id == institution_id
    )
    if active_only:
        q = q.where(Room.is_active == True)  # noqa: E712
    q = q.group_by(Room.room_type)
    result = await db.execute(q)
    counts: dict[str, int] = {}
    for row in result.all():
        key = row[0].value if hasattr(row[0], "value") else str(row[0])
        counts[key] = row[1]
    return counts


async def list_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    room_type: Optional[RoomType] = None,
    building: Optional[str] = None,
    search: Optional[str] = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[Room]:
    q = select(Room).where(Room.institution_id == institution_id)
    if active_only:
        q = q.where(Room.is_active == True)  # noqa: E712
    if room_type is not None:
        q = q.where(Room.room_type == room_type)
    if building is not None:
        q = q.where(Room.building == building)
    if search:
        term = f"%{search.lower()}%"
        q = q.where(
            Room.code.ilike(term) | Room.name.ilike(term)
        )
    q = q.order_by(Room.code).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    room_type: Optional[RoomType] = None,
    building: Optional[str] = None,
    search: Optional[str] = None,
    active_only: bool = True,
) -> int:
    q = select(func.count()).select_from(Room).where(Room.institution_id == institution_id)
    if active_only:
        q = q.where(Room.is_active == True)  # noqa: E712
    if room_type is not None:
        q = q.where(Room.room_type == room_type)
    if building is not None:
        q = q.where(Room.building == building)
    if search:
        term = f"%{search.lower()}%"
        q = q.where(
            Room.code.ilike(term) | Room.name.ilike(term)
        )
    result = await db.execute(q)
    return result.scalar_one()


async def get_by_id(db: AsyncSession, room_id: uuid.UUID) -> Optional[Room]:
    result = await db.execute(select(Room).where(Room.id == room_id))
    return result.scalars().first()


async def get_or_404(db: AsyncSession, room_id: uuid.UUID) -> Room:
    room = await get_by_id(db, room_id)
    if room is None:
        raise NotFoundError(f"Room {room_id} not found")
    return room


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    institution_id: uuid.UUID,
    payload: RoomCreate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Room:
    existing = await db.execute(
        select(Room).where(
            Room.institution_id == institution_id,
            Room.code == payload.code,
        )
    )
    if existing.scalars().first() is not None:
        raise ConflictError(f"Room code '{payload.code}' already exists in this institution")

    room = Room(**payload.model_dump())
    db.add(room)
    await db.flush()
    logger.info("Room created", room_id=str(room.id), code=room.code)

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.CREATED,
        entity_type="Room",
        entity_id=room.id,
        entity_label=room.code,
        institution_id=institution_id,
    )
    return room


async def update(
    db: AsyncSession,
    room_id: uuid.UUID,
    payload: RoomUpdate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Room:
    room = await get_or_404(db, room_id)
    before = {k: getattr(room, k) for k in payload.model_dump(exclude_unset=True)}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    await db.flush()
    logger.info("Room updated", room_id=str(room_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    after = {k: getattr(room, k) for k in before}
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="Room",
        entity_id=room_id,
        entity_label=room.code,
        institution_id=room.institution_id,
        before=before,
        after=after,
    )
    return room


async def soft_delete(
    db: AsyncSession,
    room_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Room:
    room = await get_or_404(db, room_id)
    room.is_active = False
    await db.flush()
    logger.info("Room deactivated", room_id=str(room_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="Room",
        entity_id=room_id,
        entity_label=room.code,
        institution_id=room.institution_id,
    )
    return room


async def hard_delete(
    db: AsyncSession,
    room_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> None:
    room = await get_or_404(db, room_id)
    label = room.code
    institution_id = room.institution_id
    await db.delete(room)
    await db.flush()
    logger.warning("Room permanently deleted", room_id=str(room_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="Room",
        entity_id=room_id,
        entity_label=label,
        institution_id=institution_id,
    )
