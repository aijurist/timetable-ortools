"""
teaching_assignments.py
=======================
HOD Teaching Plan endpoints.

Coordinators persist teacher-course assignments here BEFORE creating a COHORT.
COHORT creation reads these rows to auto-create buckets + offerings atomically.

Routes (prefix /teaching-assignments)
--------------------------------------
GET    /                      List assignments (filterable by institution/term/dept)
POST   /                      Create one (idempotent on unique conflict)
POST   /bulk                  Bulk create for a dept+term
POST   /bulk-preview          CSV/XLSX file → structured preview (no DB writes)
POST   /bulk-import           Execute rows from a preview → BulkImportResult
GET    /{id}                  Get one
PATCH  /{id}                  Update one
DELETE /{id}                  Hard-delete one
GET    /workload-preview       Per-course teacher coverage vs. class_count
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    actor_institution_id,
    assert_same_institution,
    get_db,
    get_pagination,
    hod_dept_filter,
    require_admin,
    require_hod,
)
from app.schemas.curriculum import (
    InstitutionPlanningStats,
    TeachingAssignmentCreate,
    TeachingAssignmentListResponse,
    TeachingAssignmentResponse,
    TeachingAssignmentUpdate,
    WorkloadPreview,
)
from app.schemas.bulk_upload import BulkImportRequest, BulkImportResult, BulkUploadPreview
import app.services.teaching_assignment_service as ta_svc

router = APIRouter()


async def _resolve_term(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: Optional[uuid.UUID],
) -> Optional[uuid.UUID]:
    """Return academic_term_id as-is, or fall back to the institution's active term."""
    if academic_term_id:
        return academic_term_id
    from app.models.institution import AcademicTerm, AcademicTermStatus
    result = await db.execute(
        select(AcademicTerm.id).where(
            AcademicTerm.institution_id == institution_id,
            AcademicTerm.status == AcademicTermStatus.ACTIVE,
        ).limit(1)
    )
    return result.scalar_one_or_none()


@router.get(
    "",
    response_model=TeachingAssignmentListResponse,
    summary="List teaching assignments",
)
async def list_teaching_assignments(
    institution_id: uuid.UUID = Query(...),
    academic_term_id: Optional[uuid.UUID] = Query(default=None),
    department_id: Optional[uuid.UUID] = Query(default=None),
    requested_dept_id: Optional[uuid.UUID] = Query(default=None),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> TeachingAssignmentListResponse:
    assert_same_institution(current_user, institution_id)
    resolved_term = await _resolve_term(db, institution_id, academic_term_id)
    if not resolved_term:
        return TeachingAssignmentListResponse(items=[], total=0, skip=pagination.skip, limit=pagination.limit)
    dept_scope = hod_dept_filter(current_user) if requested_dept_id is None else None
    dept_scope = dept_scope or department_id
    raw = await ta_svc.list_teaching_assignments(
        db, institution_id, resolved_term,
        department_id=dept_scope,
        requested_dept_id=requested_dept_id,
        active_only=active_only,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    items = await ta_svc.enrich_assignments(db, raw)
    return TeachingAssignmentListResponse(
        items=items,
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/workload-preview",
    response_model=WorkloadPreview,
    summary="Preview teacher coverage vs. class_count for a dept+term",
)
async def get_workload_preview(
    institution_id: uuid.UUID = Query(...),
    academic_term_id: Optional[uuid.UUID] = Query(default=None),
    department_id: Optional[uuid.UUID] = Query(default=None),
    class_count: Optional[int] = Query(default=None, ge=1),
    include_service_load: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> WorkloadPreview:
    assert_same_institution(current_user, institution_id)
    resolved_term = await _resolve_term(db, institution_id, academic_term_id)
    if not resolved_term:
        raise HTTPException(status_code=404, detail="No active academic term found")
    dept_scope = hod_dept_filter(current_user) or department_id
    return await ta_svc.get_workload_preview(
        db, institution_id, resolved_term,
        department_id=dept_scope,
        class_count=class_count,
        include_service_load=include_service_load,
    )


@router.get(
    "/institution-planning-stats",
    response_model=InstitutionPlanningStats,
    summary="Per-dept planning aggregates for the admin dashboard",
)
async def get_institution_planning_stats(
    institution_id: uuid.UUID = Query(...),
    academic_term_id: Optional[uuid.UUID] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> InstitutionPlanningStats:
    resolved_term = await _resolve_term(db, institution_id, academic_term_id)
    if not resolved_term:
        raise HTTPException(status_code=404, detail="No active academic term found")
    return await ta_svc.get_institution_planning_stats(db, institution_id, resolved_term)


@router.post(
    "",
    response_model=TeachingAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a teaching assignment (idempotent)",
)
async def create_teaching_assignment(
    payload: TeachingAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> TeachingAssignmentResponse:
    inst_id = actor_institution_id(current_user, payload.institution_id)
    payload = payload.model_copy(update={"institution_id": inst_id})
    dept_scope = hod_dept_filter(current_user)
    if dept_scope and payload.department_id and payload.department_id != dept_scope:
        raise HTTPException(status_code=403, detail="Cannot create assignments outside your department")
    assignment = await ta_svc.create_teaching_assignment(
        db, payload,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
    )
    await db.commit()
    await db.refresh(assignment)
    return TeachingAssignmentResponse.model_validate(assignment)


@router.post(
    "/bulk",
    response_model=list[TeachingAssignmentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Bulk create teaching assignments for a dept+term",
)
async def bulk_create_teaching_assignments(
    payloads: list[TeachingAssignmentCreate],
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> list[TeachingAssignmentResponse]:
    inst_id = actor_institution_id(current_user, payloads[0].institution_id if payloads else None)
    dept_scope = hod_dept_filter(current_user)
    results = []
    for payload in payloads:
        payload = payload.model_copy(update={"institution_id": inst_id})
        if dept_scope and payload.department_id and payload.department_id != dept_scope:
            raise HTTPException(status_code=403, detail="Cannot create assignments outside your department")
        assignment = await ta_svc.create_teaching_assignment(db, payload)
        results.append(assignment)
    await db.commit()
    return [TeachingAssignmentResponse.model_validate(a) for a in results]


@router.post(
    "/bulk-preview",
    response_model=BulkUploadPreview,
    status_code=status.HTTP_200_OK,
    summary="Preview a CSV/XLSX bulk teaching assignment import",
)
async def bulk_preview_teaching_assignments(
    institution_id: uuid.UUID = Form(...),
    academic_term_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    auto_assign: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkUploadPreview:
    from app.services.bulk.base import cleanup_temp, parse_file, save_upload_to_temp
    from app.services.bulk.teaching_assignment_import import preview_import

    assert_same_institution(current_user, institution_id)
    dept_scope = hod_dept_filter(current_user)

    tmp = await save_upload_to_temp(file)
    try:
        rows = parse_file(tmp)
    finally:
        cleanup_temp(tmp)

    return await preview_import(
        db,
        rows=rows,
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        dept_id=dept_scope,
        role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        auto_assign=auto_assign,
    )


@router.post(
    "/bulk-import",
    response_model=BulkImportResult,
    status_code=status.HTTP_200_OK,
    summary="Execute a previewed bulk teaching assignment import",
)
async def bulk_import_teaching_assignments(
    payload: BulkImportRequest,
    institution_id: uuid.UUID = Query(...),
    academic_term_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkImportResult:
    from app.services.bulk.teaching_assignment_import import execute_import

    assert_same_institution(current_user, institution_id)
    dept_scope = hod_dept_filter(current_user)

    return await execute_import(
        db,
        rows=payload.rows,
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        dept_id=dept_scope,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
    )


@router.get(
    "/{assignment_id}",
    response_model=TeachingAssignmentResponse,
    summary="Get a teaching assignment",
)
async def get_teaching_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> TeachingAssignmentResponse:
    assignment = await ta_svc.get_teaching_assignment_or_404(db, assignment_id)
    assert_same_institution(current_user, assignment.institution_id)
    dept_scope = hod_dept_filter(current_user)
    if dept_scope and assignment.department_id and assignment.department_id != dept_scope and assignment.requested_dept_id != dept_scope:
        raise HTTPException(status_code=403, detail="Access denied: assignment belongs to another department")
    return TeachingAssignmentResponse.model_validate(assignment)


@router.patch(
    "/{assignment_id}",
    response_model=TeachingAssignmentResponse,
    summary="Update a teaching assignment",
)
async def update_teaching_assignment(
    assignment_id: uuid.UUID,
    payload: TeachingAssignmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> TeachingAssignmentResponse:
    existing = await ta_svc.get_teaching_assignment_or_404(db, assignment_id)
    assert_same_institution(current_user, existing.institution_id)
    dept_scope = hod_dept_filter(current_user)
    if dept_scope and existing.department_id and existing.department_id != dept_scope and existing.requested_dept_id != dept_scope:
        raise HTTPException(status_code=403, detail="Access denied: assignment belongs to another department")
    assignment = await ta_svc.update_teaching_assignment(
        db, assignment_id, payload,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
    )
    await db.commit()
    await db.refresh(assignment)
    return TeachingAssignmentResponse.model_validate(assignment)


@router.delete(
    "/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a teaching assignment",
)
async def delete_teaching_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    existing = await ta_svc.get_teaching_assignment_or_404(db, assignment_id)
    assert_same_institution(current_user, existing.institution_id)
    dept_scope = hod_dept_filter(current_user)
    if dept_scope and existing.department_id and existing.department_id != dept_scope and existing.requested_dept_id != dept_scope:
        raise HTTPException(status_code=403, detail="Access denied: assignment belongs to another department")
    await ta_svc.delete_teaching_assignment(
        db, assignment_id,
        actor_user_id=current_user.user_id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
    )
    await db.commit()
    return None
