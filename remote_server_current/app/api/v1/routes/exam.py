"""
exam.py
=======
Exam scheduling domain — scenarios, slots, and solver assignments.

Architecture note: exam_scenarios has NO FK to scenarios — it is a fully
separate scheduling domain with its own CP-SAT model.

GET    /exam-scenarios                           List exam scenarios for an institution
POST   /exam-scenarios                           Create an exam scenario
GET    /exam-scenarios/{id}                      Get an exam scenario
PATCH  /exam-scenarios/{id}                      Update name/status/config
GET    /exam-scenarios/{id}/slots                List exam slots
POST   /exam-scenarios/{id}/slots                Add a slot
PATCH  /exam-scenarios/slots/{slot_id}           Update a slot
DELETE /exam-scenarios/slots/{slot_id}           Delete a slot
GET    /exam-scenarios/{id}/assignments          Get solver output (ExamAssignments)
DELETE /exam-scenarios/{id}/assignments          Clear all assignments (pre-solve)
"""
from __future__ import annotations

import uuid
from typing import List

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
from app.schemas.exam import (
    ExamAssignmentListResponse,
    ExamAssignmentResponse,
    ExamScenarioCreate,
    ExamScenarioListResponse,
    ExamScenarioResponse,
    ExamScenarioUpdate,
    ExamSlotCreate,
    ExamSlotListResponse,
    ExamSlotResponse,
    ExamSlotUpdate,
)
import app.services.exam_service as exam_svc

router = APIRouter()


# ===========================================================================
# ExamScenario
# ===========================================================================


@router.get(
    "",
    response_model=ExamScenarioListResponse,
    summary="List exam scenarios for an institution",
)
async def list_exam_scenarios(
    institution_id: uuid.UUID = Query(..., description="Filter by institution"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamScenarioListResponse:
    assert_same_institution(current_user, institution_id)
    items = await exam_svc.list_by_institution(
        db, institution_id, skip=pagination.skip, limit=pagination.limit
    )
    return ExamScenarioListResponse(
        items=[ExamScenarioResponse.model_validate(s) for s in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.post(
    "",
    response_model=ExamScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an exam scenario",
)
async def create_exam_scenario(
    payload: ExamScenarioCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamScenarioResponse:
    inst_id = actor_institution_id(current_user, payload.institution_id)
    scenario = await exam_svc.create_scenario(db, inst_id, payload)
    await db.commit()
    await db.refresh(scenario)
    return ExamScenarioResponse.model_validate(scenario)


@router.get(
    "/{scenario_id}",
    response_model=ExamScenarioResponse,
    summary="Get an exam scenario",
)
async def get_exam_scenario(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamScenarioResponse:
    scenario = await exam_svc.get_exam_scenario_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    return ExamScenarioResponse.model_validate(scenario)


@router.patch(
    "/{scenario_id}",
    response_model=ExamScenarioResponse,
    summary="Update an exam scenario (name / status / solver_config)",
)
async def update_exam_scenario(
    scenario_id: uuid.UUID,
    payload: ExamScenarioUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamScenarioResponse:
    existing = await exam_svc.get_exam_scenario_or_404(db, scenario_id)
    assert_same_institution(current_user, existing.institution_id)
    scenario = await exam_svc.update_scenario(db, scenario_id, payload)
    await db.commit()
    await db.refresh(scenario)
    return ExamScenarioResponse.model_validate(scenario)


# ===========================================================================
# ExamSlots — nested under scenario
# ===========================================================================


@router.get(
    "/{scenario_id}/slots",
    response_model=ExamSlotListResponse,
    summary="List exam slots for a scenario",
)
async def list_slots(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamSlotListResponse:
    scenario = await exam_svc.get_exam_scenario_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    items = await exam_svc.list_slots(db, scenario_id)
    return ExamSlotListResponse(
        items=[ExamSlotResponse.model_validate(s) for s in items],
        total=len(items),
        skip=0,
        limit=len(items),
    )


@router.post(
    "/{scenario_id}/slots",
    response_model=ExamSlotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an exam slot (date + time window)",
)
async def add_slot(
    scenario_id: uuid.UUID,
    payload: ExamSlotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamSlotResponse:
    scenario = await exam_svc.get_exam_scenario_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    slot = await exam_svc.add_slot(db, scenario_id, payload)
    await db.commit()
    await db.refresh(slot)
    return ExamSlotResponse.model_validate(slot)


# ===========================================================================
# ExamSlots — individual resource endpoints
# ===========================================================================


@router.patch(
    "/slots/{slot_id}",
    response_model=ExamSlotResponse,
    summary="Update an exam slot",
)
async def update_slot(
    slot_id: uuid.UUID,
    payload: ExamSlotUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamSlotResponse:
    slot = await exam_svc.update_slot(db, slot_id, payload)
    await db.commit()
    await db.refresh(slot)
    return ExamSlotResponse.model_validate(slot)


@router.delete(
    "/slots/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete an exam slot",
)
async def delete_slot(
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    await exam_svc.delete_slot(db, slot_id)
    await db.commit()
    return None


# ===========================================================================
# ExamAssignments (solver output — read + clear)
# ===========================================================================


@router.get(
    "/{scenario_id}/assignments",
    response_model=ExamAssignmentListResponse,
    summary="Get solver output — exam assignments for a scenario",
)
async def get_assignments(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamAssignmentListResponse:
    scenario = await exam_svc.get_exam_scenario_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    items = await exam_svc.get_assignments(db, scenario_id)
    return ExamAssignmentListResponse(
        items=[ExamAssignmentResponse.model_validate(a) for a in items],
        total=len(items),
        skip=0,
        limit=len(items),
    )


@router.delete(
    "/{scenario_id}/assignments",
    response_model=None,
    summary="Clear all exam assignments for a scenario (called pre-solve by Celery task)",
)
async def clear_assignments(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> dict:
    """
    Deletes all ExamAssignment rows for this scenario.
    Returns the count of deleted rows for diagnostics.
    """
    scenario = await exam_svc.get_exam_scenario_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    deleted = await exam_svc.clear_assignments(db, scenario_id)
    await db.commit()
    return {"deleted": deleted, "exam_scenario_id": str(scenario_id)}
