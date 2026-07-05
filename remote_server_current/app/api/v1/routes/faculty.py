"""
Faculty router — faculty profile CRUD and availability management.

GET    /faculty                       List faculty for an institution (paginated).
POST   /faculty                       Create a faculty record.
GET    /faculty/{id}                  Get a faculty member.
PATCH  /faculty/{id}                  Update profile fields.
DELETE /faculty/{id}                  Soft-delete (sets is_active=False).
PATCH  /faculty/{id}/availability     Update slot availability blacklist.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser, PaginationParams, get_db, get_pagination,
    assert_same_institution, actor_institution_id, hod_dept_filter, require_hod,
    require_admin,
)
from app.models.user import User
from app.schemas.faculty import (
    FacultyAvailabilityUpdate,
    FacultyCreate,
    FacultyListResponse,
    FacultyResponse,
    FacultyUpdate,
    FacultyWithUserCreate,
    FacultyWithUserResponse,
)
from app.schemas.user import UserResponse
import app.services.faculty_service as faculty_svc

# Bulk import
from fastapi import UploadFile
from app.core.upload import ALLOWED_EXTENSIONS
from app.schemas.bulk_upload import (
    BulkImportRequest, BulkImportResult,
    BulkUploadPreviewResponse,
)
from app.services.bulk import base as bulk_base
from app.services.bulk import faculty_import as bulk_faculty

router = APIRouter()


@router.get(
    "",
    response_model=FacultyListResponse,
    summary="List faculty members for an institution",
)
async def list_faculty(
    institution_id: uuid.UUID,
    department_id: Optional[uuid.UUID] = Query(default=None, description="Filter by department"),
    search: Optional[str] = Query(default=None, description="Search by name or email"),
    active_only: Optional[bool] = Query(default=True),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> FacultyListResponse:
    assert_same_institution(current_user, institution_id)
    # HOD can only see their own department's faculty; ADMIN+ sees all
    effective_dept = hod_dept_filter(current_user) or department_id
    total = await faculty_svc.count_by_institution(
        db,
        institution_id,
        department_id=effective_dept,
        search=search,
        active_only=active_only,
    )
    items = await faculty_svc.list_by_institution(
        db,
        institution_id,
        department_id=effective_dept,
        search=search,
        active_only=active_only,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    summary = await faculty_svc.get_summary(
        db,
        institution_id,
        department_id=effective_dept,
        search=search,
        active_only=active_only,
    )
    response_items = await faculty_svc.to_response_list(db, items)
    return FacultyListResponse(
        items=response_items,
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
        employment_counts=summary["employment_counts"],
        total_max_weekly_hours=summary["total_max_weekly_hours"],
        avg_load_percent=summary["avg_load_percent"],
    )


@router.post(
    "/with-user",
    response_model=FacultyWithUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a faculty record and linked TEACHER user account atomically",
)
async def create_faculty_with_user(
    payload: FacultyWithUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> FacultyWithUserResponse:
    from fastapi import HTTPException
    inst_id = actor_institution_id(current_user, payload.institution_id)
    if hod_dept_filter(current_user) is not None and payload.department_id != current_user.department_uuid:
        raise HTTPException(status_code=403, detail="HOD can only create faculty in their own department")
    payload = payload.model_copy(update={"institution_id": inst_id})
    faculty, user = await faculty_svc.create_with_user(db, payload)
    await db.commit()
    await db.refresh(faculty)
    await db.refresh(user)
    faculty_resp = await faculty_svc.to_response(db, faculty)
    from app.schemas.user import UserResponse
    return FacultyWithUserResponse(faculty=faculty_resp, user=UserResponse.model_validate(user))


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


@router.post(
    "/bulk-preview",
    response_model=BulkUploadPreviewResponse,
    summary="Preview a CSV/XLSX faculty import",
)
async def bulk_faculty_preview(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkUploadPreviewResponse:
    from fastapi import HTTPException
    ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if f".{ext}" not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    from app.core.upload import MAX_BULK_ROWS
    from app.api.v1.deps import actor_institution_id
    institution_id = actor_institution_id(current_user)
    temp_path = await bulk_base.save_upload_to_temp(file)
    try:
        parsed = bulk_base.parse_file(temp_path)
        if len(parsed) > 1000:
            parsed = parsed[:1000]
        if not parsed:
            raise HTTPException(status_code=400, detail="File contains no data rows")
        preview = await bulk_faculty.preview_import(db, parsed, institution_id)
        return BulkUploadPreviewResponse(resource="faculty", preview=preview)
    finally:
        bulk_base.cleanup_temp(temp_path)


@router.post(
    "/bulk-import",
    response_model=BulkImportResult,
    summary="Execute a faculty bulk import",
)
async def bulk_faculty_import(
    payload: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkImportResult:
    from app.api.v1.deps import actor_institution_id
    from fastapi import HTTPException
    institution_id = actor_institution_id(current_user)
    result = await bulk_faculty.execute_import(
        db, payload.rows, institution_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    return result


@router.delete(
    "/{faculty_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Permanently delete a faculty record and all linked data",
)
async def hard_delete_faculty(
    faculty_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    from fastapi import HTTPException
    existing = await faculty_svc.get_or_404(db, faculty_id)
    assert_same_institution(current_user, existing.institution_id)
    await faculty_svc.hard_delete(db, faculty_id)
    await db.commit()
    return None


@router.get(
    "/{faculty_id}",
    response_model=FacultyResponse,
    summary="Get a faculty member",
)
async def get_faculty(
    faculty_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> FacultyResponse:
    faculty = await faculty_svc.get_or_404(db, faculty_id)
    assert_same_institution(current_user, faculty.institution_id)
    return await faculty_svc.to_response(db, faculty)


@router.patch(
    "/{faculty_id}",
    response_model=FacultyResponse,
    summary="Update faculty profile",
)
async def update_faculty(
    faculty_id: uuid.UUID,
    payload: FacultyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> FacultyResponse:
    from fastapi import HTTPException
    existing = await faculty_svc.get_or_404(db, faculty_id)
    assert_same_institution(current_user, existing.institution_id)
    # Resolve faculty's department from linked User (single source of truth)
    if hod_dept_filter(current_user) is not None:
        user_dept = await db.execute(
            select(User.department_id).where(User.id == existing.user_id)
        )
        faculty_dept_id = user_dept.scalar_one_or_none()
        if faculty_dept_id != current_user.department_uuid:
            raise HTTPException(status_code=403, detail="HOD can only update faculty in their own department")
    faculty = await faculty_svc.update(
        db, faculty_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(faculty)
    return await faculty_svc.to_response(db, faculty)


@router.delete(
    "/{faculty_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Soft-delete a faculty record (sets is_active=False)",
)
async def delete_faculty(
    faculty_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    from fastapi import HTTPException
    existing = await faculty_svc.get_or_404(db, faculty_id)
    assert_same_institution(current_user, existing.institution_id)
    if hod_dept_filter(current_user) is not None:
        user_dept = await db.execute(
            select(User.department_id).where(User.id == existing.user_id)
        )
        if user_dept.scalar_one_or_none() != current_user.department_uuid:
            raise HTTPException(status_code=403, detail="HOD can only delete faculty in their own department")
    await faculty_svc.soft_delete(
        db, faculty_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return None


@router.patch(
    "/{faculty_id}/availability",
    response_model=FacultyResponse,
    summary="Update slot availability blacklist",
)
async def update_availability(
    faculty_id: uuid.UUID,
    payload: FacultyAvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> FacultyResponse:
    """
    Replace the faculty member's unavailable slot blacklist.
    e.g. `{ "blacklist": ["A3", "B5"] }` — empty list clears all restrictions.
    """
    from fastapi import HTTPException
    existing = await faculty_svc.get_or_404(db, faculty_id)
    assert_same_institution(current_user, existing.institution_id)
    if hod_dept_filter(current_user) is not None:
        user_dept = await db.execute(
            select(User.department_id).where(User.id == existing.user_id)
        )
        if user_dept.scalar_one_or_none() != current_user.department_uuid:
            raise HTTPException(status_code=403, detail="HOD can only update availability for faculty in their own department")
    faculty = await faculty_svc.update_availability(
        db, faculty_id, payload.availability_blacklist,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(faculty)
    return await faculty_svc.to_response(db, faculty)
