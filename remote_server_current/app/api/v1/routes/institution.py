"""
institution.py
==============
Infrastructure layer CRUD — Institution, Department, AcademicTerm.

Institutions router  (prefix /institutions)
-------------------------------------------
GET    /institutions                           List all institutions (super-admin) or own institution
POST   /institutions                           Create institution (super_admin only)
GET    /institutions/{id}                      Get institution
PATCH  /institutions/{id}                      Update institution
GET    /institutions/{id}/departments          List departments for an institution
POST   /institutions/{id}/departments          Create a department
GET    /institutions/{id}/terms                List academic terms for an institution
POST   /institutions/{id}/terms                Create an academic term

Departments router  (prefix /departments)
-----------------------------------------
GET    /departments/{id}                       Get a department
PATCH  /departments/{id}                       Update a department

Terms router  (prefix /terms)
-----------------------------
GET    /terms/{id}                             Get an academic term
PATCH  /terms/{id}                             Update an academic term
PATCH  /terms/{id}/status                      Set academic term status
POST   /terms/{id}/archive                     Soft-delete (archive) an academic term
POST   /terms/{id}/restore                     Restore a soft-deleted term
GET    /terms/{id}/dependents                  Count dependent records
DELETE /terms/{id}/purge                       Permanently purge an archived term
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    get_current_user,
    get_db,
    get_pagination,
    require_admin,
    require_hod,
    require_super_admin,
    assert_same_institution,
)
from app.models.institution import AcademicTermStatus
from app.schemas.institution import (
    AcademicTermCreate,
    AcademicTermListResponse,
    AcademicTermResponse,
    AcademicTermUpdate,
    DepartmentCreate,
    DepartmentCreateRequest,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentUpdate,
    DependentCountsResponse,
    InstitutionCreate,
    InstitutionListResponse,
    InstitutionResponse,
    InstitutionStatsResponse,
    InstitutionUpdate,
)
import app.services.institution_service as institution_svc
import app.services.institution_stats_service as institution_stats_svc

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

institutions_router = APIRouter()
departments_router = APIRouter()
terms_router = APIRouter()


# ===========================================================================
# Institutions
# ===========================================================================


@institutions_router.get(
    "",
    response_model=InstitutionListResponse,
    summary="List institutions",
    description="Super-admins see all institutions. Admins/HODs should filter by their own institution_id.",
)
async def list_institutions(
    active_only: bool = Query(default=False, description="Return only active institutions"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> InstitutionListResponse:
    if current_user.is_super_admin:
        items = await institution_svc.list_institutions(
            db, active_only=active_only, skip=pagination.skip, limit=pagination.limit
        )
    else:
        # Non-super-admins only see their own institution
        if current_user.institution_id is None:
            items = []
        else:
            import uuid as _uuid
            inst = await institution_svc.get_institution_or_404(
                db, _uuid.UUID(current_user.institution_id)
            )
            items = [inst] if (not active_only or inst.is_active) else []
    return InstitutionListResponse(
        items=[InstitutionResponse.model_validate(i) for i in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@institutions_router.post(
    "",
    response_model=InstitutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an institution (super_admin only)",
)
async def create_institution(
    payload: InstitutionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> InstitutionResponse:
    institution = await institution_svc.create_institution(db, payload)
    await db.commit()
    await db.refresh(institution)
    return InstitutionResponse.model_validate(institution)


@institutions_router.get(
    "/{institution_id}",
    response_model=InstitutionResponse,
    summary="Get an institution",
)
async def get_institution(
    institution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> InstitutionResponse:
    institution = await institution_svc.get_institution_or_404(db, institution_id)
    assert_same_institution(current_user, institution.id)
    return InstitutionResponse.model_validate(institution)


@institutions_router.get(
    "/{institution_id}/stats",
    response_model=InstitutionStatsResponse,
    summary="Aggregate resource counts for an institution",
)
async def get_institution_stats(
    institution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> InstitutionStatsResponse:
    assert_same_institution(current_user, institution_id)
    stats = await institution_stats_svc.get_institution_stats(db, institution_id)
    return stats


@institutions_router.patch(
    "/{institution_id}",
    response_model=InstitutionResponse,
    summary="Update an institution",
)
async def update_institution(
    institution_id: uuid.UUID,
    payload: InstitutionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> InstitutionResponse:
    existing = await institution_svc.get_institution_or_404(db, institution_id)
    assert_same_institution(current_user, existing.id)
    institution = await institution_svc.update_institution(db, institution_id, payload)
    await db.commit()
    await db.refresh(institution)
    return InstitutionResponse.model_validate(institution)


# ---------------------------------------------------------------------------
# Departments — nested under institution
# ---------------------------------------------------------------------------


@institutions_router.get(
    "/{institution_id}/departments",
    response_model=DepartmentListResponse,
    summary="List departments for an institution",
)
async def list_departments(
    institution_id: uuid.UUID,
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> DepartmentListResponse:
    assert_same_institution(current_user, institution_id)
    # HODs can see all departments (needed to resolve dept names in planning/catalog).
    # Write operations on departments are admin-only and enforce ownership separately.
    items = await institution_svc.list_departments(
        db, institution_id, active_only=active_only, skip=pagination.skip, limit=pagination.limit
    )
    hod_name_map = await institution_svc.bulk_hod_names(db, items)
    responses = []
    for d in items:
        r = DepartmentResponse.model_validate(d)
        r.hod_faculty_name = hod_name_map.get(d.hod_faculty_id) if d.hod_faculty_id else None
        responses.append(r)
    return DepartmentListResponse(
        items=responses,
        total=len(responses),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@institutions_router.post(
    "/{institution_id}/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a department",
)
async def create_department(
    institution_id: uuid.UUID,
    payload: DepartmentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> DepartmentResponse:
    assert_same_institution(current_user, institution_id)
    department = await institution_svc.create_department(
        db,
        DepartmentCreate(
            institution_id=institution_id,
            **payload.model_dump(),
        ),
    )
    await db.commit()
    await db.refresh(department)
    return DepartmentResponse.model_validate(department)


# ---------------------------------------------------------------------------
# Terms — nested under institution
# ---------------------------------------------------------------------------


@institutions_router.get(
    "/{institution_id}/terms",
    response_model=AcademicTermListResponse,
    summary="List academic terms for an institution",
)
async def list_terms(
    institution_id: uuid.UUID,
    active_only: bool = Query(default=False),
    include_deleted: bool = Query(default=False, description="Include soft-deleted terms"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> AcademicTermListResponse:
    assert_same_institution(current_user, institution_id)
    items = await institution_svc.list_terms(
        db, institution_id, active_only=active_only, include_deleted=include_deleted,
        skip=pagination.skip, limit=pagination.limit,
    )
    return AcademicTermListResponse(
        items=[AcademicTermResponse.model_validate(t) for t in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@institutions_router.post(
    "/{institution_id}/terms",
    response_model=AcademicTermResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an academic term",
)
async def create_term(
    institution_id: uuid.UUID,
    payload: AcademicTermCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> AcademicTermResponse:
    assert_same_institution(current_user, institution_id)
    term = await institution_svc.create_term(db, payload)
    await db.commit()
    await db.refresh(term)
    return AcademicTermResponse.model_validate(term)


# ===========================================================================
# Departments  (individual resource endpoints)
# ===========================================================================


@departments_router.get(
    "/{department_id}",
    response_model=DepartmentResponse,
    summary="Get a department",
)
async def get_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> DepartmentResponse:
    department = await institution_svc.get_department_or_404(db, department_id)
    assert_same_institution(current_user, department.institution_id)
    hod_name = await institution_svc._resolve_hod_name(db, department)
    resp = DepartmentResponse.model_validate(department)
    resp.hod_faculty_name = hod_name
    return resp


@departments_router.delete(
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard-delete a department (admin only)",
    description=(
        "Permanently removes the department and all linked records via DB cascade. "
        "This action is irreversible. Deactivate instead when in doubt."
    ),
)
async def hard_delete_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> Response:
    existing = await institution_svc.get_department_or_404(db, department_id)
    assert_same_institution(current_user, existing.institution_id)
    await institution_svc.hard_delete_department(
        db, department_id, actor_user_id=current_user.user_uuid, actor_role=current_user.role.value
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@departments_router.patch(
    "/{department_id}",
    response_model=DepartmentResponse,
    summary="Update a department",
)
async def update_department(
    department_id: uuid.UUID,
    payload: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> DepartmentResponse:
    existing = await institution_svc.get_department_or_404(db, department_id)
    assert_same_institution(current_user, existing.institution_id)
    department, hod_name = await institution_svc.update_department(
        db, department_id, payload, actor_role=current_user.role
    )
    await db.commit()
    await db.refresh(department)
    resp = DepartmentResponse.model_validate(department)
    resp.hod_faculty_name = hod_name
    return resp


# ===========================================================================
# Academic Terms  (individual resource endpoints)
# ===========================================================================


class _SetStatusRequest(BaseModel):
    status: AcademicTermStatus


@terms_router.get(
    "/{term_id}",
    response_model=AcademicTermResponse,
    summary="Get an academic term",
)
async def get_term(
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AcademicTermResponse:
    term = await institution_svc.get_term_or_404(db, term_id)
    assert_same_institution(current_user, term.institution_id)
    return AcademicTermResponse.model_validate(term)


@terms_router.patch(
    "/{term_id}",
    response_model=AcademicTermResponse,
    summary="Update an academic term",
)
async def update_term(
    term_id: uuid.UUID,
    payload: AcademicTermUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> AcademicTermResponse:
    existing = await institution_svc.get_term_or_404(db, term_id)
    assert_same_institution(current_user, existing.institution_id)
    term = await institution_svc.update_term(db, term_id, payload)
    await db.commit()
    await db.refresh(term)
    return AcademicTermResponse.model_validate(term)


@terms_router.post(
    "/{term_id}/archive",
    response_model=AcademicTermResponse,
    summary="Archive (soft-delete) an academic term (admin only)",
    description=(
        "Soft-deletes the term by setting deleted_at. The term is hidden from "
        "normal queries but can be restored. Use GET /{term_id}/dependents to "
        "see dependent records before archiving."
    ),
)
async def archive_term(
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> AcademicTermResponse:
    term = await institution_svc.get_term_include_deleted(db, term_id)
    if term is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")
    assert_same_institution(current_user, term.institution_id)
    term = await institution_svc.archive_term(
        db, term_id, actor_user_id=current_user.user_uuid, actor_role=current_user.role.value
    )
    await db.commit()
    await db.refresh(term)
    return AcademicTermResponse.model_validate(term)


@terms_router.post(
    "/{term_id}/restore",
    response_model=AcademicTermResponse,
    summary="Restore a soft-deleted academic term (admin only)",
)
async def restore_term(
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> AcademicTermResponse:
    term = await institution_svc.get_term_include_deleted(db, term_id)
    if term is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")
    assert_same_institution(current_user, term.institution_id)
    term = await institution_svc.restore_term(
        db, term_id, actor_user_id=current_user.user_uuid, actor_role=current_user.role.value
    )
    await db.commit()
    await db.refresh(term)
    return AcademicTermResponse.model_validate(term)


@terms_router.get(
    "/{term_id}/dependents",
    response_model=DependentCountsResponse,
    summary="Get dependent record counts for an academic term",
    description=(
        "Returns counts of dependent records across all 10 tables that "
        "reference this academic_term_id. Useful before archiving or purging."
    ),
)
async def get_term_dependents(
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> DependentCountsResponse:
    term = await institution_svc.get_term_include_deleted(db, term_id)
    if term is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")
    assert_same_institution(current_user, term.institution_id)
    return await institution_svc.get_term_dependents(db, term_id)


@terms_router.delete(
    "/{term_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently purge an archived term (admin only)",
    description=(
        "Irreversibly deletes the term. The term must be archived first "
        "(deleted_at set). Fails with 409 if dependent records exist — "
        "check GET /terms/{term_id}/dependents and delete them first."
    ),
)
async def purge_term(
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> Response:
    term = await institution_svc.get_term_include_deleted(db, term_id)
    if term is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")
    assert_same_institution(current_user, term.institution_id)
    await institution_svc.purge_term(
        db, term_id, actor_user_id=current_user.user_uuid, actor_role=current_user.role.value
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@terms_router.patch(
    "/{term_id}/status",
    response_model=AcademicTermResponse,
    summary="Set academic term status (PLANNING → ACTIVE → ARCHIVED etc.)",
)
async def set_term_status(
    term_id: uuid.UUID,
    body: _SetStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> AcademicTermResponse:
    existing = await institution_svc.get_term_or_404(db, term_id)
    assert_same_institution(current_user, existing.institution_id)
    term = await institution_svc.set_term_status(db, term_id, body.status)
    await db.commit()
    await db.refresh(term)
    return AcademicTermResponse.model_validate(term)
