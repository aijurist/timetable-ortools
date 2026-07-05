"""
Elective Pools router — PE / OE pool management in the Planning section.

POST   /elective-pools                     Create a new pool
GET    /elective-pools                     List pools (with filters)
GET    /elective-pools/{pool_id}           Pool detail + TA summary
PATCH  /elective-pools/{pool_id}           Update label / active flag
DELETE /elective-pools/{pool_id}           Delete pool (unlinks TAs via CASCADE)
POST   /elective-pools/{pool_id}/assign    Assign a TA to this pool
DELETE /elective-pools/{pool_id}/assign/{ta_id}  Unassign a TA
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_db
from app.models.course import ElectiveType
import app.services.elective_pool_service as pool_svc

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ElectivePoolCreate(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: uuid.UUID
    study_semester: int = Field(..., ge=1, le=12)
    label: str = Field(..., max_length=30, description="e.g. 'PE-1', 'OE-2'")
    elective_type: ElectiveType = ElectiveType.PROFESSIONAL


class ElectivePoolUpdate(BaseModel):
    label: Optional[str] = Field(None, max_length=30)
    is_active: Optional[bool] = None


class ElectivePoolResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: uuid.UUID
    study_semester: int
    label: str
    elective_type: ElectiveType
    is_active: bool

    class Config:
        from_attributes = True


class AssignTARequest(BaseModel):
    ta_id: uuid.UUID


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/elective-pools",
    response_model=list[ElectivePoolResponse],
    summary="List elective pools for a department",
    tags=["elective-pools"],
)
async def list_pools(
    institution_id: Optional[uuid.UUID] = Query(default=None),
    academic_term_id: Optional[uuid.UUID] = Query(default=None),
    department_id: Optional[uuid.UUID] = Query(default=None),
    study_semester: Optional[int] = Query(default=None),
    elective_type: Optional[ElectiveType] = Query(default=None),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> list[ElectivePoolResponse]:
    from app.api.v1.deps import actor_institution_id
    inst_id = actor_institution_id(current_user, institution_id)
    pools = await pool_svc.list_pools(
        db, inst_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        study_semester=study_semester,
        elective_type=elective_type,
        active_only=active_only,
    )
    return [ElectivePoolResponse.model_validate(p) for p in pools]


@router.post(
    "/elective-pools",
    response_model=ElectivePoolResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an elective pool",
    tags=["elective-pools"],
)
async def create_pool(
    body: ElectivePoolCreate,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> ElectivePoolResponse:
    pool = await pool_svc.create_pool(
        db,
        institution_id=body.institution_id,
        academic_term_id=body.academic_term_id,
        department_id=body.department_id,
        study_semester=body.study_semester,
        label=body.label,
        elective_type=body.elective_type,
    )
    await db.commit()
    await db.refresh(pool)
    return ElectivePoolResponse.model_validate(pool)


@router.get(
    "/elective-pools/{pool_id}",
    summary="Pool detail with TA summary (for Planning UI preview)",
    tags=["elective-pools"],
)
async def get_pool(
    pool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> dict[str, Any]:
    return await pool_svc.get_pool_summary(db, pool_id)


@router.patch(
    "/elective-pools/{pool_id}",
    response_model=ElectivePoolResponse,
    summary="Update pool label or active flag",
    tags=["elective-pools"],
)
async def update_pool(
    pool_id: uuid.UUID,
    body: ElectivePoolUpdate,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> ElectivePoolResponse:
    patch = body.model_dump(exclude_unset=True)
    pool = await pool_svc.update_pool(db, pool_id, patch)
    await db.commit()
    await db.refresh(pool)
    return ElectivePoolResponse.model_validate(pool)


@router.delete(
    "/elective-pools/{pool_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a pool; TAs are unlinked via CASCADE",
    tags=["elective-pools"],
)
async def delete_pool(
    pool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> dict[str, str]:
    await pool_svc.delete_pool(db, pool_id)
    await db.commit()
    return {"status": "deleted"}


@router.post(
    "/elective-pools/{pool_id}/assign",
    summary="Assign a TA to this pool",
    tags=["elective-pools"],
)
async def assign_ta(
    pool_id: uuid.UUID,
    body: AssignTARequest,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> dict[str, Any]:
    ta = await pool_svc.assign_ta_to_pool(db, body.ta_id, pool_id)
    await db.commit()
    return {
        "ta_id": str(ta.id),
        "elective_pool_id": str(ta.elective_pool_id),
        "is_merged_session": ta.is_merged_session,
    }


@router.delete(
    "/elective-pools/{pool_id}/assign/{ta_id}",
    summary="Unassign a TA from this pool",
    tags=["elective-pools"],
)
async def unassign_ta(
    pool_id: uuid.UUID,
    ta_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> dict[str, str]:
    await pool_svc.assign_ta_to_pool(db, ta_id, None)
    await db.commit()
    return {"status": "unassigned"}
