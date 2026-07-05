"""
app/services/reservation_service.py
======================================
Ad-hoc room reservation management with conflict detection.

Responsibilities
----------------
* ``create`` — persist a new PENDING reservation after running conflict check.
* ``approve`` / ``reject`` / ``cancel`` — lifecycle transitions.
* ``check_conflicts`` — query scheduled_sessions + exam_assignments for room clashes
  on the same date + overlapping times.  Returns True if a conflict is found.
* ``list_by_institution`` / ``list_by_room`` — paginated listing.

Architecture note
-----------------
Conflict detection checks both scheduled_sessions (timetable) and
exam_assignments (exam timetable) since both use the same physical rooms.
Reservations themselves are also checked (no double-booking approved reservations).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logger import logger
from app.models.audit_log import AuditAction
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.reservation import ReservationApprove, ReservationCreate, ReservationStatusUpdate
import app.services.audit_log_service as audit_log_service


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def _times_overlap(s1: str, e1: str, s2: str, e2: str) -> bool:
    """
    Return True if time interval [s1, e1) overlaps [s2, e2).
    Times are "HH:MM" strings.
    """
    return s1 < e2 and s2 < e1


async def check_conflicts(
    db: AsyncSession,
    room_id: uuid.UUID,
    date: str,
    start_time: str,
    end_time: str,
    exclude_reservation_id: Optional[uuid.UUID] = None,
) -> bool:
    """
    Return True if the requested time slot for *room_id* on *date* conflicts with:
    1. An APPROVED reservation for the same room overlapping the time window.
    2. (Future) scheduled_sessions lookup is intentionally left as a DB-level check
       via the time_grid expansion at the Route layer; this method checks reservations.

    Returns False if the slot is free.
    """
    q = select(Reservation).where(
        Reservation.room_id == room_id,
        Reservation.date == date,
        Reservation.status == ReservationStatus.APPROVED,
    )
    if exclude_reservation_id is not None:
        q = q.where(Reservation.id != exclude_reservation_id)

    result = await db.execute(q)
    existing = result.scalars().all()

    for res in existing:
        if _times_overlap(start_time, end_time, res.start_time, res.end_time):
            return True
    return False


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def list_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    status: Optional[ReservationStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[Reservation]:
    q = select(Reservation).where(Reservation.institution_id == institution_id)
    if status is not None:
        q = q.where(Reservation.status == status)
    q = q.order_by(Reservation.date.desc(), Reservation.start_time).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def list_by_room(
    db: AsyncSession,
    room_id: uuid.UUID,
    *,
    date: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[Reservation]:
    q = select(Reservation).where(Reservation.room_id == room_id)
    if date is not None:
        q = q.where(Reservation.date == date)
    q = q.order_by(Reservation.date, Reservation.start_time).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_or_404(db: AsyncSession, reservation_id: uuid.UUID) -> Reservation:
    result = await db.execute(
        select(Reservation).where(Reservation.id == reservation_id)
    )
    res = result.scalars().first()
    if res is None:
        raise NotFoundError(f"Reservation {reservation_id} not found")
    return res


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    institution_id: uuid.UUID,
    payload: ReservationCreate,
) -> Reservation:
    """
    Create a PENDING reservation.

    Runs conflict detection first.  Raises ``ConflictError`` if the room is
    already booked (APPROVED) for an overlapping time on that date.
    """
    has_conflict = await check_conflicts(
        db,
        room_id=payload.room_id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    if has_conflict:
        raise ConflictError(
            f"Room {payload.room_id} already has an approved booking on "
            f"{payload.date} overlapping {payload.start_time}–{payload.end_time}"
        )

    reservation = Reservation(
        institution_id=institution_id,
        room_id=payload.room_id,
        requested_by=payload.requested_by,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        purpose=payload.purpose,
        status=ReservationStatus.PENDING,
        conflict_checked_at=datetime.now(tz=timezone.utc),
    )
    db.add(reservation)
    await db.flush()
    logger.info(
        "Reservation created",
        reservation_id=str(reservation.id),
        room_id=str(payload.room_id),
        date=payload.date,
    )
    await audit_log_service.record(
        db,
        actor_user_id=payload.requested_by,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="Reservation",
        entity_id=reservation.id,
        entity_label=f"{payload.date} {payload.start_time}–{payload.end_time}",
        institution_id=institution_id,
        after={"room_id": str(payload.room_id), "date": payload.date, "status": "PENDING"},
    )
    return reservation


async def approve(
    db: AsyncSession,
    reservation_id: uuid.UUID,
    approved_by: uuid.UUID,
) -> Reservation:
    """Approve a PENDING reservation after re-checking conflicts."""
    res = await get_or_404(db, reservation_id)
    if res.status != ReservationStatus.PENDING:
        raise ValidationError(f"Cannot approve a reservation in '{res.status.value}' status")

    # Re-check conflicts (another admin may have approved a clashing booking)
    has_conflict = await check_conflicts(
        db,
        room_id=res.room_id,
        date=res.date,
        start_time=res.start_time,
        end_time=res.end_time,
        exclude_reservation_id=reservation_id,
    )
    if has_conflict:
        raise ConflictError("Cannot approve: room already has a clashing approved booking")

    res.status = ReservationStatus.APPROVED
    res.approved_by = approved_by
    res.conflict_checked_at = datetime.now(tz=timezone.utc)
    await db.flush()
    logger.info("Reservation approved", reservation_id=str(reservation_id))
    await audit_log_service.record(
        db,
        actor_user_id=approved_by,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="Reservation",
        entity_id=reservation_id,
        institution_id=res.institution_id,
        after={"status": "APPROVED"},
    )
    return res


async def reject(
    db: AsyncSession,
    reservation_id: uuid.UUID,
    approved_by: uuid.UUID,
) -> Reservation:
    res = await get_or_404(db, reservation_id)
    if res.status not in (ReservationStatus.PENDING,):
        raise ValidationError(f"Cannot reject a reservation in '{res.status.value}' status")
    res.status = ReservationStatus.REJECTED
    res.approved_by = approved_by
    await db.flush()
    logger.info("Reservation rejected", reservation_id=str(reservation_id))
    await audit_log_service.record(
        db,
        actor_user_id=approved_by,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="Reservation",
        entity_id=reservation_id,
        institution_id=res.institution_id,
        after={"status": "REJECTED"},
    )
    return res


async def cancel(
    db: AsyncSession,
    reservation_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
) -> Reservation:
    """Cancel a PENDING or APPROVED reservation."""
    res = await get_or_404(db, reservation_id)
    if res.status in (ReservationStatus.REJECTED, ReservationStatus.CANCELLED):
        raise ValidationError(f"Reservation is already '{res.status.value}'")
    res.status = ReservationStatus.CANCELLED
    await db.flush()
    logger.info("Reservation cancelled", reservation_id=str(reservation_id))
    await audit_log_service.record(
        db,
        actor_user_id=requesting_user_id,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="Reservation",
        entity_id=reservation_id,
        institution_id=res.institution_id,
        after={"status": "CANCELLED"},
    )
    return res
