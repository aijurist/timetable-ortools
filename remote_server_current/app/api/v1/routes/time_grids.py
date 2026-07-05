"""
time_grids.py
=============
TimeGrid CRUD — academic-term slot dictionaries used by the CP-SAT solver.

The slot dictionary is the authoritative time-slot mapping. Slot codes are
opaque strings (e.g. "A1", "B3") — never hardcode slot integers in the solver.
The solver builds integer indices from this dict at pipeline start.

GET    /time-grids                      List time grids for an academic term
POST   /time-grids                      Create a time grid
GET    /time-grids/{id}                 Get a time grid
PATCH  /time-grids/{id}                 Replace name and/or entire slot dict
PATCH  /time-grids/{id}/slots           Surgical upsert/remove of individual slots
DELETE /time-grids/{id}                 Hard-delete a time grid
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    assert_same_institution,
    get_current_user,
    get_db,
    get_pagination,
    require_admin,
)
from app.schemas.time_grid import (
    TimeGridCreate,
    TimeGridListResponse,
    TimeGridResponse,
    TimeGridSlotPatch,
    TimeGridUpdate,
)
import app.services.time_grid_service as time_grid_svc

router = APIRouter()


@router.get(
    "",
    response_model=TimeGridListResponse,
    summary="List time grids for an academic term",
)
async def list_time_grids(
    academic_term_id: uuid.UUID = Query(..., description="Academic term UUID"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TimeGridListResponse:
    term_institution_id = await time_grid_svc._resolve_institution_id(db, academic_term_id)
    assert_same_institution(current_user, term_institution_id)
    items = await time_grid_svc.get_by_term(db, academic_term_id)
    return TimeGridListResponse(
        items=[TimeGridResponse.from_orm_with_count(g) for g in items],
        total=len(items),
        skip=0,
        limit=len(items),
    )


@router.post(
    "",
    response_model=TimeGridResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a time grid for an academic term",
)
async def create_time_grid(
    payload: TimeGridCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> TimeGridResponse:
    term_institution_id = await time_grid_svc._resolve_institution_id(db, payload.academic_term_id)
    assert_same_institution(current_user, term_institution_id)
    grid = await time_grid_svc.create(db, payload)
    await db.commit()
    await db.refresh(grid)
    return TimeGridResponse.from_orm_with_count(grid)


@router.get(
    "/{grid_id}",
    response_model=TimeGridResponse,
    summary="Get a time grid",
)
async def get_time_grid(
    grid_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TimeGridResponse:
    grid = await time_grid_svc.get_or_404(db, grid_id)
    term_institution_id = await time_grid_svc._resolve_institution_id(db, grid.academic_term_id)
    assert_same_institution(current_user, term_institution_id)
    return TimeGridResponse.from_orm_with_count(grid)


@router.patch(
    "/{grid_id}",
    response_model=TimeGridResponse,
    summary="Update a time grid (name and/or full slot dict replacement)",
)
async def update_time_grid(
    grid_id: uuid.UUID,
    payload: TimeGridUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> TimeGridResponse:
    """
    Replaces ``slots`` wholesale if provided. Use PATCH /{id}/slots for
    surgical slot-level changes without replacing the whole dictionary.
    """
    existing = await time_grid_svc.get_or_404(db, grid_id)
    term_institution_id = await time_grid_svc._resolve_institution_id(db, existing.academic_term_id)
    assert_same_institution(current_user, term_institution_id)
    grid = await time_grid_svc.update(db, grid_id, payload)
    await db.commit()
    await db.refresh(grid)
    return TimeGridResponse.from_orm_with_count(grid)


@router.patch(
    "/{grid_id}/slots",
    response_model=TimeGridResponse,
    summary="Surgical slot patch — add/overwrite or remove individual slot codes",
)
async def patch_slots(
    grid_id: uuid.UUID,
    payload: TimeGridSlotPatch,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> TimeGridResponse:
    """
    Merges ``slots`` (upsert) and removes any codes listed in ``remove``.
    Existing slot codes not mentioned are preserved.

    Example body::

        {
          "slots": {"A1": {"day": "MON", "start": "09:00", "end": "10:00"}},
          "remove": ["B5"]
        }
    """
    existing = await time_grid_svc.get_or_404(db, grid_id)
    term_institution_id = await time_grid_svc._resolve_institution_id(db, existing.academic_term_id)
    assert_same_institution(current_user, term_institution_id)
    grid = await time_grid_svc.patch_slots(db, grid_id, payload)
    await db.commit()
    await db.refresh(grid)
    return TimeGridResponse.from_orm_with_count(grid)


@router.delete(
    "/{grid_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Hard-delete a time grid",
)
async def delete_time_grid(
    grid_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    existing = await time_grid_svc.get_or_404(db, grid_id)
    term_institution_id = await time_grid_svc._resolve_institution_id(db, existing.academic_term_id)
    assert_same_institution(current_user, term_institution_id)
    await time_grid_svc.delete(db, grid_id)
    await db.commit()
    return None
