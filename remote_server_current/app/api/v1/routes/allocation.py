"""
Allocation router — pre-solve faculty/bucket allocation.

# Target course demand CRUD
GET    /target-course-demand               List demand entries (filter by institution/term/target)
POST   /target-course-demand               Add single demand entry
POST   /target-course-demand/bulk          Add multiple entries for one target
DELETE /target-course-demand/{demand_id}   Remove demand entry

# Scenario allocation
GET    /scenarios/{id}/allocation          Get current allocation state
POST   /scenarios/{id}/allocation/run      Trigger allocation (AllocationRunRequest body)
DELETE /scenarios/{id}/allocation          Reset auto-created offerings
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select
from app.api.v1.deps import CurrentUser, assert_same_institution, get_current_user, get_db
from app.models.curriculum import TargetCourseDemand
from app.schemas.allocation import (
    AllocationResult,
    AllocationRunRequest,
    AllocationState,
    TargetCourseDemandBulkCreate,
    TargetCourseDemandCreate,
    TargetCourseDemandResponse,
)
import app.services.allocation.service as allocation_svc
import app.services.scenario_service as scenario_svc

router = APIRouter()


# ---------------------------------------------------------------------------
# Target course demand CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/target-course-demand",
    response_model=list[TargetCourseDemandResponse],
    summary="List target course demand entries",
)
async def list_demand(
    institution_id: uuid.UUID = Query(...),
    academic_term_id: uuid.UUID = Query(...),
    target_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[TargetCourseDemandResponse]:
    assert_same_institution(current_user, institution_id)
    return await allocation_svc.get_demand(db, institution_id, academic_term_id, target_id)


@router.post(
    "/target-course-demand",
    response_model=TargetCourseDemandResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a single target course demand entry",
)
async def add_demand(
    payload: TargetCourseDemandCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TargetCourseDemandResponse:
    assert_same_institution(current_user, payload.institution_id)
    result = await allocation_svc.add_demand(db, payload)
    await db.commit()
    return result


@router.post(
    "/target-course-demand/bulk",
    response_model=list[TargetCourseDemandResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Add multiple demand entries for one target in one request",
    description=(
        "Provide a target_id and a list of course_ids. "
        "Creates one TargetCourseDemand row per course. "
        "Idempotent: existing rows are updated if required_sections differs."
    ),
)
async def bulk_add_demand(
    payload: TargetCourseDemandBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[TargetCourseDemandResponse]:
    assert_same_institution(current_user, payload.institution_id)
    results = await allocation_svc.bulk_add_demand(db, payload)
    await db.commit()
    return results


@router.delete(
    "/target-course-demand/{demand_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Remove a target course demand entry",
)
async def delete_demand(
    demand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    row = await db.scalar(select(TargetCourseDemand).where(TargetCourseDemand.id == demand_id))
    if row is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"Demand entry {demand_id} not found")
    assert_same_institution(current_user, row.institution_id)
    await allocation_svc.delete_demand(db, demand_id)
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Scenario allocation
# ---------------------------------------------------------------------------


@router.get(
    "/scenarios/{scenario_id}/allocation",
    response_model=AllocationState,
    summary="Get current allocation state for a scenario",
    description=(
        "Returns how many demand rows exist, how many already have faculty assigned, "
        "and is_ready_for_solve=True when all offerings have a faculty_id set "
        "(or when there are no demand rows at all)."
    ),
)
async def get_allocation_state(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AllocationState:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    return await allocation_svc.get_allocation_state(db, scenario)


@router.post(
    "/scenarios/{scenario_id}/allocation/run",
    response_model=AllocationResult,
    summary="Run pre-solve allocation for a scenario",
    description=(
        "Runs the CP-SAT mini-solver to assign faculty to sections (per_section mode) "
        "or creates shared/open-pool buckets (shared/open_pool modes). "
        "Set dry_run=true to preview without writing to DB."
    ),
)
async def run_allocation(
    scenario_id: uuid.UUID,
    payload: AllocationRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AllocationResult:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    result = await allocation_svc.run_allocation(db, scenario, payload)
    if not payload.dry_run:
        await db.commit()
    return result


@router.delete(
    "/scenarios/{scenario_id}/allocation",
    summary="Reset auto-created allocation offerings for a scenario",
    description=(
        "Deletes all CourseOfferings created by the allocation phase "
        "(slot_code=NULL, faculty_id IS NOT NULL). "
        "Does not delete manually-created offerings or offerings that have been solved. "
        "Returns count of deleted offerings."
    ),
)
async def reset_allocation(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    count = await allocation_svc.reset_allocation(db, scenario)
    await db.commit()
    return {"deleted": count}
