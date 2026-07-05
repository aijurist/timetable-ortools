"""
Courses router — course catalogue CRUD.

GET    /courses          List courses for an institution (paginated).
POST   /courses          Create a course.
GET    /courses/{id}     Get a course.
PATCH  /courses/{id}     Update a course.
DELETE /courses/{id}     Soft-delete (sets is_active=False).
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser, PaginationParams, get_db, get_pagination,
    assert_same_institution, actor_institution_id, hod_dept_filter, require_hod, require_admin,
)
from app.schemas.course import CourseCreate, CourseListResponse, CourseResponse, CourseUpdate
import app.services.course_service as course_svc
# Bulk import
from fastapi import UploadFile
from app.schemas.bulk_upload import (
    BulkImportRequest, BulkImportResult,
    BulkUploadPreview, BulkUploadPreviewResponse,
)
from app.services.bulk import base as bulk_base
from app.services.bulk import course_import as bulk_course

router = APIRouter()


@router.get(
    "",
    response_model=CourseListResponse,
    summary="List courses for an institution",
)
async def list_courses(
    institution_id: uuid.UUID,
    department_id: Optional[uuid.UUID] = Query(default=None, description="Filter by department"),
    search: Optional[str] = Query(default=None, description="Search by code or name"),
    active_only: bool = Query(default=True, description="Return only active courses"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseListResponse:
    assert_same_institution(current_user, institution_id)
    # HODs can browse the full institution catalog (read-only for other depts).
    # Write operations (create/update/delete) enforce dept ownership individually.
    total = await course_svc.count_by_institution(
        db,
        institution_id,
        department_id=department_id,
        search=search,
        active_only=active_only,
    )
    items = await course_svc.list_by_institution(
        db,
        institution_id,
        department_id=department_id,
        search=search,
        active_only=active_only,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    session_counts = await course_svc.get_session_counts(
        db,
        institution_id,
        department_id=department_id,
        search=search,
        active_only=active_only,
    )
    response_items = await course_svc.to_response_list(db, items)
    return CourseListResponse(
        items=response_items,
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
        session_counts=session_counts,
    )


@router.post(
    "",
    response_model=CourseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a course",
)
async def create_course(
    payload: CourseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseResponse:
    from fastapi import HTTPException
    inst_id = actor_institution_id(current_user, payload.institution_id)
    if hod_dept_filter(current_user) is not None and payload.department_id != current_user.department_uuid:
        raise HTTPException(status_code=403, detail="HOD can only create courses in their own department")
    course = await course_svc.create(
        db, inst_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(course)
    return await course_svc.to_response(db, course)


@router.get(
    "/{course_id}",
    response_model=CourseResponse,
    summary="Get a course",
)
async def get_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseResponse:
    course = await course_svc.get_or_404(db, course_id)
    assert_same_institution(current_user, course.institution_id)
    return await course_svc.to_response(db, course)


@router.patch(
    "/{course_id}",
    response_model=CourseResponse,
    summary="Update a course",
)
async def update_course(
    course_id: uuid.UUID,
    payload: CourseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseResponse:
    from fastapi import HTTPException
    existing = await course_svc.get_or_404(db, course_id)
    assert_same_institution(current_user, existing.institution_id)
    if hod_dept_filter(current_user) is not None and existing.department_id != current_user.department_uuid:
        raise HTTPException(status_code=403, detail="HOD can only update courses in their own department")
    course = await course_svc.update(
        db, course_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(course)
    return await course_svc.to_response(db, course)


@router.delete(
    "/{course_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Hard-delete a course (admin only) — irreversible",
    description="Permanently removes the course and all linked records via DB cascade.",
)
async def hard_delete_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    existing = await course_svc.get_or_404(db, course_id)
    assert_same_institution(current_user, existing.institution_id)
    await course_svc.hard_delete(db, course_id, actor_user_id=current_user.user_uuid)
    await db.commit()
    return None


@router.delete(
    "/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Soft-delete a course (sets is_active=False)",
)
async def delete_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    from fastapi import HTTPException
    existing = await course_svc.get_or_404(db, course_id)
    assert_same_institution(current_user, existing.institution_id)
    if hod_dept_filter(current_user) is not None and existing.department_id != current_user.department_uuid:
        raise HTTPException(status_code=403, detail="HOD can only delete courses in their own department")
    await course_svc.soft_delete(
        db, course_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


@router.post(
    "/bulk-preview",
    response_model=BulkUploadPreviewResponse,
    summary="Preview a CSV/XLSX course import",
)
async def bulk_course_preview(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkUploadPreviewResponse:
    from fastapi import HTTPException
    from app.core.upload import ALLOWED_EXTENSIONS
    from app.api.v1.deps import actor_institution_id
    ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if f".{ext}" not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    institution_id = actor_institution_id(current_user)
    temp_path = await bulk_base.save_upload_to_temp(file)
    try:
        parsed = bulk_base.parse_file(temp_path)
        if len(parsed) > 1000:
            parsed = parsed[:1000]
        if not parsed:
            raise HTTPException(status_code=400, detail="File contains no data rows")
        preview = await bulk_course.preview_import(db, parsed, institution_id)
        return BulkUploadPreviewResponse(resource="courses", preview=preview)
    finally:
        bulk_base.cleanup_temp(temp_path)


@router.post(
    "/bulk-import",
    response_model=BulkImportResult,
    summary="Execute a course bulk import",
)
async def bulk_course_import(
    payload: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkImportResult:
    from fastapi import HTTPException
    from app.api.v1.deps import actor_institution_id
    institution_id = actor_institution_id(current_user)
    result = await bulk_course.execute_import(
        db, payload.rows, institution_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    return result
