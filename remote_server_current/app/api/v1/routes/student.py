"""
student.py
==========
Student management — profile, FFCS registration, and wishlist.

Architecture reminder
---------------------
- Student is NOT a CP-SAT solver resource. The solver works with
  SchedulingTarget (batches). These endpoints serve the FFCS
  registration UI and the Campus Brain AI study assistant.
- FFCS registration is two-phase:
    Phase 1: StudentWishlist  (draft, no seat lock)
    Phase 2: StudentRegistration (confirmed, atomic booked_seats++)
- The register endpoint calls curriculum_svc.book_seat internally via
  student_service.register_offering — always uses SELECT FOR UPDATE.

Student Profiles router  (prefix /students)
-------------------------------------------
POST   /students/profiles                       Create a student profile (1-to-1 with user)
GET    /students/profiles/me                    Get MY profile (derived from JWT sub)
GET    /students/profiles/{profile_id}          Get a profile by ID
PATCH  /students/profiles/{profile_id}          Update profile
GET    /students/profiles/by-batch/{batch_id}   List profiles for a batch

Student Registrations router  (prefix /students)
-------------------------------------------------
GET    /students/{student_id}/registrations     List confirmed registrations
POST   /students/{student_id}/registrations     Register an offering (FFCS Phase 2)
GET    /students/registrations/{reg_id}         Get a registration
DELETE /students/registrations/{reg_id}         Drop a registration (soft-delete)

Student Wishlists router  (prefix /students)
--------------------------------------------
GET    /students/{student_id}/wishlists         List wishlists (draft plans)
POST   /students/{student_id}/wishlists         Create a wishlist
GET    /students/wishlists/{wishlist_id}         Get a wishlist
PATCH  /students/wishlists/{wishlist_id}         Update a wishlist
DELETE /students/wishlists/{wishlist_id}         Delete a wishlist
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    assert_same_institution,
    actor_institution_id,
    get_current_user,
    get_db,
    get_pagination,
    hod_dept_filter,
    require_admin,
    require_hod,
)
from app.schemas.selection import (
    BulkCourseEligibilityRequest,
    CourseEligibilityResponse,
)
from app.core.exceptions import ValidationError
from app.models.selection import EligibilitySource
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.schemas.student import (
    BulkBatchAssignRequest,
    BulkBatchAutoAllocateRequest,
    StudentAdminCreate,
    StudentAdminListResponse,
    StudentAdminResponse,
    StudentAdminUpdate,
    StudentProfileCreate,
    StudentProfileListResponse,
    StudentProfileResponse,
    StudentProfileUpdate,
    StudentSummaryResponse,
    StudentRegistrationCreate,
    StudentRegistrationListResponse,
    StudentRegistrationResponse,
    StudentWishlistCreate,
    StudentWishlistListResponse,
    StudentWishlistResponse,
    StudentWishlistUpdate,
)
import app.services.student_service as student_svc
import app.services.student_course_eligibility_service as eligibility_svc
# Bulk import
from fastapi import UploadFile
from app.schemas.bulk_upload import (
    BulkImportRequest, BulkImportResult,
    BulkUploadPreview, BulkUploadPreviewResponse,
)
from app.services.bulk import base as bulk_base
from app.services.bulk import student_import as bulk_student

# ---------------------------------------------------------------------------
# One router — all mounts share the same /students prefix
# ---------------------------------------------------------------------------

router = APIRouter()


async def _assert_student_admin_access(
    db: AsyncSession,
    profile_id: uuid.UUID,
    current_user: CurrentUser,
) -> None:
    result = await db.execute(
        select(User.institution_id, User.department_id)
        .select_from(StudentProfile)
        .join(User, StudentProfile.user_id == User.id)
        .where(StudentProfile.id == profile_id)
    )
    owner = result.first()
    if owner is None:
        raise HTTPException(status_code=404, detail="Student not found")

    assert_same_institution(current_user, owner.institution_id)
    hod_dept = hod_dept_filter(current_user)
    if hod_dept is not None and owner.department_id != hod_dept:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HOD can only manage students in their own department",
        )


async def _assert_profile_access(
    db: AsyncSession,
    profile_id: uuid.UUID,
    current_user: CurrentUser,
) -> None:
    """Staff (HOD/admin) or the profile owner may access a student profile."""
    if current_user.is_hod:
        await _assert_student_admin_access(db, profile_id, current_user)
        return
    if current_user.role == UserRole.STUDENT:
        profile = await student_svc.get_profile_or_404(db, profile_id)
        if profile.user_id != current_user.user_uuid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied",
    )


async def _assert_student_id_access(
    db: AsyncSession,
    student_id: uuid.UUID,
    current_user: CurrentUser,
) -> None:
    await _assert_profile_access(db, student_id, current_user)


async def _assert_registration_access(
    db: AsyncSession,
    registration_id: uuid.UUID,
    current_user: CurrentUser,
) -> None:
    registration = await student_svc.get_registration_or_404(db, registration_id)
    await _assert_profile_access(db, registration.student_id, current_user)


async def _assert_wishlist_access(
    db: AsyncSession,
    wishlist_id: uuid.UUID,
    current_user: CurrentUser,
) -> None:
    wishlist = await student_svc.get_wishlist_or_404(db, wishlist_id)
    await _assert_profile_access(db, wishlist.student_id, current_user)


@router.get(
    "",
    response_model=StudentAdminListResponse,
    summary="List managed students for an institution",
)
async def list_students(
    institution_id: Optional[uuid.UUID] = Query(default=None, description="Institution UUID (super_admin only)"),
    q: Optional[str] = Query(default=None, description="Search by name, email, or enrollment number"),
    department_id: Optional[uuid.UUID] = Query(default=None),
    batch_id: Optional[uuid.UUID] = Query(default=None),
    degree_type: Optional[str] = Query(default=None),
    semester: Optional[int] = Query(default=None, ge=1),
    year_of_study: Optional[int] = Query(default=None, ge=1),
    is_active: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> StudentAdminListResponse:
    inst_id = actor_institution_id(current_user, institution_id)
    effective_dept = hod_dept_filter(current_user) or department_id
    items, total = await student_svc.list_students(
        db,
        inst_id,
        q=q,
        department_id=effective_dept,
        batch_id=batch_id,
        degree_type=degree_type,
        semester=semester,
        year_of_study=year_of_study,
        is_active=is_active,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return StudentAdminListResponse(items=items, total=total, skip=pagination.skip, limit=pagination.limit)


@router.get(
    "/summary",
    response_model=StudentSummaryResponse,
    summary="Student counts grouped by department for the current filters",
)
async def student_summary(
    institution_id: Optional[uuid.UUID] = Query(default=None),
    q: Optional[str] = Query(default=None),
    department_id: Optional[uuid.UUID] = Query(default=None),
    batch_id: Optional[uuid.UUID] = Query(default=None),
    degree_type: Optional[str] = Query(default=None),
    semester: Optional[int] = Query(default=None, ge=1),
    year_of_study: Optional[int] = Query(default=None, ge=1),
    is_active: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> StudentSummaryResponse:
    inst_id = actor_institution_id(current_user, institution_id)
    effective_dept = hod_dept_filter(current_user) or department_id
    return await student_svc.student_summary_by_department(
        db,
        inst_id,
        q=q,
        department_id=effective_dept,
        batch_id=batch_id,
        degree_type=degree_type,
        semester=semester,
        year_of_study=year_of_study,
        is_active=is_active,
    )


@router.get(
    "/count",
    summary="Count students for a department (+ optional semester) — used to auto-fill cohort sizes",
)
async def count_students_endpoint(
    institution_id: Optional[uuid.UUID] = Query(default=None),
    department_id: Optional[uuid.UUID] = Query(default=None),
    semester: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> dict[str, int]:
    inst_id = actor_institution_id(current_user, institution_id)
    effective_dept = hod_dept_filter(current_user) or department_id
    count = await student_svc.count_students(
        db, inst_id, department_id=effective_dept, semester=semester,
    )
    return {"count": count}


@router.patch(
    "/bulk-batch",
    summary="Bulk-assign students to a batch (admin: all depts, HOD: own dept only)",
)
async def bulk_assign_batch(
    payload: BulkBatchAssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> dict[str, int]:
    restrict_dept = hod_dept_filter(current_user)  # None for admin, dept UUID for HOD
    try:
        updated = await student_svc.bulk_assign_batch(
            db,
            payload.student_profile_ids,
            payload.batch_id,
            restrict_to_dept_id=restrict_dept,
            academic_term_id=payload.academic_term_id,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    await db.commit()
    return {"updated": updated}


@router.patch(
    "/bulk-auto-allocate",
    summary="Bulk auto-allocate students to matching cohort batches (admin: all depts, HOD: own dept only)",
)
async def bulk_auto_allocate(
    payload: BulkBatchAutoAllocateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> dict[str, int]:
    restrict_dept = hod_dept_filter(current_user)  # None for admin, dept UUID for HOD
    try:
        updated = await student_svc.bulk_auto_allocate_batch(
            db,
            payload.student_profile_ids,
            payload.academic_term_id,
            restrict_to_dept_id=restrict_dept,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    await db.commit()
    return {"updated": updated}


@router.get(
    "/course-eligibility",
    response_model=list[CourseEligibilityResponse],
    summary="List student course eligibility rows",
)
async def list_course_eligibility(
    academic_term_id: uuid.UUID = Query(...),
    department_id: Optional[uuid.UUID] = Query(default=None),
    study_semester: Optional[int] = Query(default=None),
    course_id: Optional[uuid.UUID] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> list[CourseEligibilityResponse]:
    effective_dept = hod_dept_filter(current_user) or department_id
    rows = await eligibility_svc.list_eligibility(
        db,
        academic_term_id=academic_term_id,
        department_id=effective_dept,
        study_semester=study_semester,
        course_id=course_id,
    )
    return [CourseEligibilityResponse.model_validate(r) for r in rows]


@router.get(
    "/course-eligibility/export",
    summary="Export PE/OE eligibility data as CSV",
    description=(
        "Download a CSV file of student PE/OE eligibility records. "
        "Supports optional filtering by department, study semester, and eligibility source. "
        "Admin/HOD access required. HODs are automatically scoped to their department."
    ),
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_course_eligibility(
    academic_term_id: uuid.UUID = Query(...),
    department_id: Optional[uuid.UUID] = Query(default=None),
    study_semester: Optional[int] = Query(default=None),
    source: Optional[str] = Query(
        default=None,
        description="Filter by source: PE, OE, MANUAL, or CORE_AUTO",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> StreamingResponse:
    """Stream a CSV download of PE/OE eligibility records."""
    # HODs are automatically restricted to their own department
    effective_dept = hod_dept_filter(current_user) or department_id

    # Parse optional source filter
    from app.models.selection import EligibilitySource as ES
    parsed_source: ES | None = None
    if source:
        try:
            parsed_source = ES(source.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid source value: {source!r}. Must be one of: PE, OE, MANUAL, CORE_AUTO",
            )

    csv_content = await eligibility_svc.export_eligibility_csv(
        db,
        academic_term_id=academic_term_id,
        department_id=effective_dept,
        study_semester=study_semester,
        source=parsed_source,
    )

    # Build a descriptive filename
    filename_parts = ["pe_oe_eligibility"]
    if study_semester is not None:
        filename_parts.append(f"sem{study_semester}")
    if source:
        filename_parts.append(source.lower())
    filename = "_".join(filename_parts) + ".csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch(
    "/bulk-course-eligibility",
    summary="Bulk assign or remove PE/OE course eligibility",
)
async def bulk_course_eligibility(
    payload: BulkCourseEligibilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> dict[str, int]:
    restrict_dept = hod_dept_filter(current_user)
    source = EligibilitySource(payload.source)
    try:
        updated = await eligibility_svc.bulk_update_eligibility(
            db,
            student_profile_ids=payload.student_profile_ids,
            course_id=payload.course_id,
            academic_term_id=payload.academic_term_id,
            study_semester=payload.study_semester,
            action=payload.action,  # type: ignore[arg-type]
            source=source,
            restrict_to_dept_id=restrict_dept,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    await db.commit()
    return {"updated": updated}


@router.post(
    "",
    response_model=StudentAdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a student account plus student profile",
)
async def onboard_student(
    payload: StudentAdminCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> StudentAdminResponse:
    inst_id = actor_institution_id(current_user, payload.institution_id)
    hod_dept = hod_dept_filter(current_user)
    if hod_dept is not None and payload.department_id != hod_dept:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HOD can only create students in their own department",
        )
    student = await student_svc.onboard_student(db, payload, institution_id=inst_id)
    await db.commit()
    return student


@router.delete(
    "/{profile_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Permanently delete a student account and all linked data",
)
async def hard_delete_student(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    await _assert_student_admin_access(db, profile_id, current_user)
    await student_svc.hard_delete_student(db, profile_id)
    await db.commit()
    return None


@router.get(
    "/{profile_id}",
    response_model=StudentAdminResponse,
    summary="Get a managed student by profile ID",
)
async def get_student(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> StudentAdminResponse:
    await _assert_student_admin_access(db, profile_id, current_user)
    return await student_svc.get_student_admin(db, profile_id)


@router.patch(
    "/{profile_id}",
    response_model=StudentAdminResponse,
    summary="Update a managed student account and profile",
)
async def update_student(
    profile_id: uuid.UUID,
    payload: StudentAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> StudentAdminResponse:
    await _assert_student_admin_access(db, profile_id, current_user)
    hod_dept = hod_dept_filter(current_user)
    if hod_dept is not None and payload.department_id is not None and payload.department_id != hod_dept:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HOD can only keep students in their own department",
        )
    student = await student_svc.update_student_admin(db, profile_id, payload)
    await db.commit()
    return student


# ===========================================================================
# Student Profiles
# ===========================================================================


@router.post(
    "/profiles",
    response_model=StudentProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a student profile (1-to-1 with a user account)",
)
async def create_profile(
    payload: StudentProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentProfileResponse:
    if current_user.is_hod:
        pass
    elif current_user.role == UserRole.STUDENT:
        if payload.user_id != current_user.user_uuid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Students may only create their own profile",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    profile = await student_svc.create_profile(db, payload)
    await db.commit()
    await db.refresh(profile)
    return StudentProfileResponse.model_validate(profile)


@router.get(
    "/profiles/me",
    response_model=StudentProfileResponse,
    summary="Get MY student profile (derived from JWT sub)",
)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentProfileResponse:
    profile = await student_svc.get_profile_by_user(db, current_user.user_uuid)
    if profile is None:
        raise HTTPException(status_code=404, detail="No student profile found for this user")
    return StudentProfileResponse.model_validate(profile)


@router.get(
    "/profiles/by-batch/{batch_id}",
    response_model=StudentProfileListResponse,
    summary="List student profiles for a scheduling target (batch)",
)
async def list_profiles_by_batch(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> StudentProfileListResponse:
    items = await student_svc.list_profiles_by_batch(
        db, batch_id, skip=pagination.skip, limit=pagination.limit
    )
    return StudentProfileListResponse(
        items=[StudentProfileResponse.model_validate(p) for p in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/profiles/{profile_id}",
    response_model=StudentProfileResponse,
    summary="Get a student profile by ID",
)
async def get_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentProfileResponse:
    await _assert_profile_access(db, profile_id, current_user)
    profile = await student_svc.get_profile_or_404(db, profile_id)
    return StudentProfileResponse.model_validate(profile)


@router.patch(
    "/profiles/{profile_id}",
    response_model=StudentProfileResponse,
    summary="Update a student profile",
)
async def update_profile(
    profile_id: uuid.UUID,
    payload: StudentProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentProfileResponse:
    await _assert_profile_access(db, profile_id, current_user)
    profile = await student_svc.update_profile(db, profile_id, payload)
    await db.commit()
    await db.refresh(profile)
    return StudentProfileResponse.model_validate(profile)


# ===========================================================================
# Student Registrations  (FFCS Phase 2 — confirmed picks)
# ===========================================================================


@router.get(
    "/{student_id}/registrations",
    response_model=StudentRegistrationListResponse,
    summary="List confirmed registrations for a student",
)
async def list_registrations(
    student_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentRegistrationListResponse:
    await _assert_student_id_access(db, student_id, current_user)
    items = await student_svc.list_registrations(
        db, student_id, skip=pagination.skip, limit=pagination.limit
    )
    return StudentRegistrationListResponse(
        items=[StudentRegistrationResponse.model_validate(r) for r in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.post(
    "/{student_id}/registrations",
    response_model=StudentRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a course offering — FFCS Phase 2 (atomic seat booking)",
)
async def register_offering(
    student_id: uuid.UUID,
    payload: StudentRegistrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentRegistrationResponse:
    """
    Calls curriculum_svc.book_seat internally (SELECT FOR UPDATE).
    Raises 409 if:
    - The offering is frozen (is_frozen=True).
    - No seats left (booked_seats >= max_seats).
    - The student already has an active registration for this offering.
    """
    if payload.student_id != student_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="student_id in path and body must match",
        )
    await _assert_student_id_access(db, student_id, current_user)
    registration = await student_svc.register_offering(db, student_id, payload.offering_id)
    await db.commit()
    await db.refresh(registration)
    return StudentRegistrationResponse.model_validate(registration)


@router.get(
    "/registrations/{registration_id}",
    response_model=StudentRegistrationResponse,
    summary="Get a single registration",
)
async def get_registration(
    registration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentRegistrationResponse:
    await _assert_registration_access(db, registration_id, current_user)
    registration = await student_svc.get_registration_or_404(db, registration_id)
    return StudentRegistrationResponse.model_validate(registration)


@router.delete(
    "/registrations/{registration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Drop a registration (soft-delete, releases seat for CONFIRMED status)",
)
async def drop_registration(
    registration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    """
    Soft-deletes the registration row (status → DROPPED).
    If the registration was CONFIRMED, calls curriculum_svc.release_seat
    to decrement booked_seats atomically.
    """
    await _assert_registration_access(db, registration_id, current_user)
    await student_svc.drop_registration(db, registration_id)
    await db.commit()
    return None


# ===========================================================================
# Student Wishlists  (FFCS Phase 1 — draft shopping cart)
# ===========================================================================


@router.get(
    "/{student_id}/wishlists",
    response_model=StudentWishlistListResponse,
    summary="List all wishlists (draft plans) for a student",
)
async def list_wishlists(
    student_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentWishlistListResponse:
    await _assert_student_id_access(db, student_id, current_user)
    items = await student_svc.list_wishlists(db, student_id)
    return StudentWishlistListResponse(
        items=[StudentWishlistResponse.model_validate(w) for w in items],
        total=len(items),
        skip=0,
        limit=len(items),
    )


@router.post(
    "/{student_id}/wishlists",
    response_model=StudentWishlistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new course wishlist (draft — no seat lock)",
)
async def create_wishlist(
    student_id: uuid.UUID,
    payload: StudentWishlistCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentWishlistResponse:
    if payload.student_id != student_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="student_id in path and body must match",
        )
    await _assert_student_id_access(db, student_id, current_user)
    wishlist = await student_svc.create_wishlist(db, payload)
    await db.commit()
    await db.refresh(wishlist)
    return StudentWishlistResponse.model_validate(wishlist)


@router.get(
    "/wishlists/{wishlist_id}",
    response_model=StudentWishlistResponse,
    summary="Get a wishlist",
)
async def get_wishlist(
    wishlist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentWishlistResponse:
    await _assert_wishlist_access(db, wishlist_id, current_user)
    wishlist = await student_svc.get_wishlist_or_404(db, wishlist_id)
    return StudentWishlistResponse.model_validate(wishlist)


@router.patch(
    "/wishlists/{wishlist_id}",
    response_model=StudentWishlistResponse,
    summary="Update a wishlist (rename or change offering list)",
)
async def update_wishlist(
    wishlist_id: uuid.UUID,
    payload: StudentWishlistUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudentWishlistResponse:
    await _assert_wishlist_access(db, wishlist_id, current_user)
    wishlist = await student_svc.update_wishlist(db, wishlist_id, payload)
    await db.commit()
    await db.refresh(wishlist)
    return StudentWishlistResponse.model_validate(wishlist)


@router.delete(
    "/wishlists/{wishlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a wishlist",
)
async def delete_wishlist(
    wishlist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    await _assert_wishlist_access(db, wishlist_id, current_user)
    await student_svc.delete_wishlist(db, wishlist_id)
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


@router.post(
    "/bulk-preview",
    response_model=BulkUploadPreviewResponse,
    summary="Preview a CSV/XLSX student import",
)
async def bulk_student_preview(
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
        preview = await bulk_student.preview_import(db, parsed, institution_id)
        return BulkUploadPreviewResponse(resource="students", preview=preview)
    finally:
        bulk_base.cleanup_temp(temp_path)


@router.post(
    "/bulk-import",
    response_model=BulkImportResult,
    summary="Execute a student bulk import",
)
async def bulk_student_import(
    payload: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkImportResult:
    from fastapi import HTTPException
    from app.api.v1.deps import actor_institution_id
    institution_id = actor_institution_id(current_user)
    result = await bulk_student.execute_import(
        db, payload.rows, institution_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    return result
