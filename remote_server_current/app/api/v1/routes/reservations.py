"""
reservations.py
===============
Ad-hoc room reservation management with conflict detection.

Architecture Note
-----------------
Conflict detection runs at the API layer (reservation_service.check_conflicts).
It checks existing APPROVED reservations for overlapping date/room/time.
Does NOT run through the solver — purely a DB query.

``requested_by`` and ``approved_by`` reference ``users.id`` — any role can
request; only HOD/admin can approve or reject.

GET    /reservations                           List by institution (filterable by status)
POST   /reservations                           Create reservation (runs conflict check)
GET    /reservations/{id}                      Get a reservation
PATCH  /reservations/{id}/approve              Approve (HOD/admin only)
PATCH  /reservations/{id}/reject               Reject (HOD/admin only)
DELETE /reservations/{id}                      Cancel a reservation
GET    /reservations/by-room/{room_id}         List reservations for a specific room
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    actor_institution_id,
    assert_same_institution,
    get_current_user,
    get_db,
    get_pagination,
    require_hod,
)
from app.models.reservation import ReservationStatus
from app.schemas.reservation import (
    ReservationApprove,
    ReservationCreate,
    ReservationListResponse,
    ReservationResponse,
)
import app.services.reservation_service as reservation_svc

router = APIRouter()


@router.get(
    "",
    response_model=ReservationListResponse,
    summary="List reservations for an institution",
)
async def list_reservations(
    institution_id: uuid.UUID = Query(..., description="Institution UUID"),
    reservation_status: Optional[ReservationStatus] = Query(
        default=None, alias="status", description="Filter by status: PENDING | APPROVED | REJECTED | CANCELLED"
    ),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> ReservationListResponse:
    assert_same_institution(current_user, institution_id)
    items = await reservation_svc.list_by_institution(
        db, institution_id, status=reservation_status, skip=pagination.skip, limit=pagination.limit
    )
    return ReservationListResponse(
        items=[ReservationResponse.model_validate(r) for r in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.post(
    "",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a room reservation request (runs conflict check)",
)
async def create_reservation(
    payload: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ReservationResponse:
    """
    Creates a PENDING reservation after checking for conflicts with existing
    APPROVED reservations. Raises 409 if a clash is found.
    """
    inst_id = actor_institution_id(current_user, payload.institution_id)
    reservation = await reservation_svc.create(db, inst_id, payload)
    await db.commit()
    await db.refresh(reservation)
    return ReservationResponse.model_validate(reservation)


@router.get(
    "/by-room/{room_id}",
    response_model=ReservationListResponse,
    summary="List reservations for a specific room",
)
async def list_by_room(
    room_id: uuid.UUID,
    date: Optional[str] = Query(default=None, description="ISO date filter, e.g. '2026-11-10'"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> ReservationListResponse:
    items = await reservation_svc.list_by_room(
        db, room_id, date=date, skip=pagination.skip, limit=pagination.limit
    )
    return ReservationListResponse(
        items=[ReservationResponse.model_validate(r) for r in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/{reservation_id}",
    response_model=ReservationResponse,
    summary="Get a reservation",
)
async def get_reservation(
    reservation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ReservationResponse:
    reservation = await reservation_svc.get_or_404(db, reservation_id)
    assert_same_institution(current_user, reservation.institution_id)
    return ReservationResponse.model_validate(reservation)


@router.patch(
    "/{reservation_id}/approve",
    response_model=ReservationResponse,
    summary="Approve a pending reservation (HOD/admin only)",
)
async def approve_reservation(
    reservation_id: uuid.UUID,
    body: ReservationApprove,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ReservationResponse:
    """
    Re-checks conflicts before approving (another booking may have been
    approved since the original request was created).
    """
    existing = await reservation_svc.get_or_404(db, reservation_id)
    assert_same_institution(current_user, existing.institution_id)
    reservation = await reservation_svc.approve(db, reservation_id, body.approved_by)
    await db.commit()
    await db.refresh(reservation)
    return ReservationResponse.model_validate(reservation)


@router.patch(
    "/{reservation_id}/reject",
    response_model=ReservationResponse,
    summary="Reject a pending reservation (HOD/admin only)",
)
async def reject_reservation(
    reservation_id: uuid.UUID,
    body: ReservationApprove,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ReservationResponse:
    existing = await reservation_svc.get_or_404(db, reservation_id)
    assert_same_institution(current_user, existing.institution_id)
    reservation = await reservation_svc.reject(db, reservation_id, body.approved_by)
    await db.commit()
    await db.refresh(reservation)
    return ReservationResponse.model_validate(reservation)


@router.delete(
    "/{reservation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Cancel a reservation (PENDING or APPROVED)",
)
async def cancel_reservation(
    reservation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    existing = await reservation_svc.get_or_404(db, reservation_id)
    assert_same_institution(current_user, existing.institution_id)
    await reservation_svc.cancel(db, reservation_id, current_user.user_uuid)
    await db.commit()
    return None
