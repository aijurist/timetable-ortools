"""
app/services/student_service.py
=================================
Student academic profile management and FFCS two-phase registration.

Responsibilities
----------------
* StudentProfile  — create, get, update (1-to-1 extension of User).
* StudentRegistration — Phase 2 FFCS: confirmed seat deduction.
* StudentWishlist — Phase 1 FFCS: draft plan, no seat lock.

FFCS two-phase flow
--------------------
  Phase 1 (Wishlist):
    ``create_wishlist`` / ``update_wishlist`` — student adds/removes
    CourseOffering UUIDs from their named plan. No seat is locked.

  Phase 2 (Registration):
    ``register_offering`` — atomically calls curriculum_service.book_seat,
    then creates a StudentRegistration row. Verifies is_frozen=False and
    booked_seats < max_seats before confirming.

  Drop:
    ``drop_registration`` — sets status=DROPPED and calls release_seat.

Architecture notes
------------------
- StudentProfile.user_id is 1-to-1 with users.id (CASCADE). Never create
  a StudentProfile without a corresponding STUDENT-role User.
- StudentProfile.batch_id → scheduling_targets.id (SET NULL on delete).
  The solver reads scheduling_targets, NOT individual students.
- StudentRegistration has a unique constraint on (student_id, offering_id),
  so re-registration after a DROP requires the service to check for an
  existing DROPPED row before creating a new one.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError, AuthorizationError
from app.core.logger import logger
from app.models.user import User, UserRole
from app.models.student import RegistrationStatus, StudentProfile, StudentRegistration, StudentWishlist
from app.models.institution import AcademicTerm
from app.models.selection_access_config import SelectionAccessConfig
from app.models.selection import DepartmentSelectionWindow, SelectionWindowStatus
import app.services.curriculum_service as curriculum_svc
import app.services.user_service as user_svc
from app.schemas.student import (
    StudentAdminCreate,
    StudentAdminResponse,
    StudentAdminUpdate,
    StudentDepartmentCount,
    StudentProfileCreate,
    StudentProfileUpdate,
    StudentSummaryResponse,
    StudentWishlistCreate,
    StudentWishlistUpdate,
)
from app.schemas.user import UserCreate, UserUpdate


async def count_students(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    department_id: Optional[uuid.UUID] = None,
    semester: Optional[int] = None,
    active_only: bool = True,
) -> int:
    """Count student profiles for a dept (+ optional semester). Used to auto-fill
    cohort sizes from real student records instead of a typed guess."""
    filters = [
        User.institution_id == institution_id,
        User.role == UserRole.STUDENT,
    ]
    if department_id is not None:
        filters.append(User.department_id == department_id)
    if semester is not None:
        filters.append(StudentProfile.semester == semester)
    if active_only:
        filters.append(User.is_active == True)  # noqa: E712

    stmt = (
        select(func.count())
        .select_from(StudentProfile)
        .join(User, StudentProfile.user_id == User.id)
        .where(*filters)
    )
    return int((await db.execute(stmt)).scalar_one())


async def auto_allocate_unassigned_students_for_published_scenarios(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> None:
    """
    Find all published scenarios for the institution, and if there are unassigned students,
    automatically auto-allocate them to their correct batches/cohorts.
    """
    try:
        from app.models.scenario import Scenario

        # 1. Find all published scenarios for this institution
        scenarios_res = await db.execute(
            select(Scenario.academic_term_id)
            .where(
                Scenario.institution_id == institution_id,
                Scenario.published_job_id.is_not(None),
                Scenario.deleted_at.is_(None)
            )
        )
        academic_term_ids = list(scenarios_res.scalars().all())
        if not academic_term_ids:
            return

        # 2. Find unassigned student profiles
        unassigned_res = await db.execute(
            select(StudentProfile.id)
            .join(User, StudentProfile.user_id == User.id)
            .where(
                User.institution_id == institution_id,
                StudentProfile.batch_id.is_(None)
            )
        )
        unassigned_ids = list(unassigned_res.scalars().all())
        if not unassigned_ids:
            return

        # 3. Auto-allocate
        allocated_any = False
        for term_id in academic_term_ids:
            allocated = await bulk_auto_allocate_batch(db, unassigned_ids, term_id)
            if allocated > 0:
                allocated_any = True

        if allocated_any:
            await db.commit()
    except Exception:
        logger.warning(
            "Failed to auto-allocate unassigned students for published scenarios",
            institution_id=str(institution_id),
            exc_info=True
        )


def _student_admin_filters(
    institution_id: uuid.UUID,
    *,
    q: Optional[str] = None,
    department_id: Optional[uuid.UUID] = None,
    batch_id: Optional[uuid.UUID] = None,
    degree_type: Optional[str] = None,
    semester: Optional[int] = None,
    year_of_study: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> list:
    base_filters = [
        User.institution_id == institution_id,
        User.role == UserRole.STUDENT,
    ]
    if q:
        pattern = f"%{q.strip()}%"
        base_filters.append(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                StudentProfile.enrollment_number.ilike(pattern),
            )
        )
    if department_id is not None:
        base_filters.append(User.department_id == department_id)
    if batch_id is not None:
        base_filters.append(StudentProfile.batch_id == batch_id)
    if degree_type is not None:
        base_filters.append(StudentProfile.degree_type == degree_type)
    if semester is not None:
        base_filters.append(StudentProfile.semester == semester)
    if year_of_study is not None:
        base_filters.append(StudentProfile.year_of_study == year_of_study)
    if is_active is not None:
        base_filters.append(User.is_active == is_active)
    return base_filters


async def list_students(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    q: Optional[str] = None,
    department_id: Optional[uuid.UUID] = None,
    batch_id: Optional[uuid.UUID] = None,
    degree_type: Optional[str] = None,
    semester: Optional[int] = None,
    year_of_study: Optional[int] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[StudentAdminResponse], int]:
    await auto_allocate_unassigned_students_for_published_scenarios(db, institution_id)
    base_filters = _student_admin_filters(
        institution_id,
        q=q,
        department_id=department_id,
        batch_id=batch_id,
        degree_type=degree_type,
        semester=semester,
        year_of_study=year_of_study,
        is_active=is_active,
    )

    count_stmt = (
        select(func.count())
        .select_from(StudentProfile)
        .join(User, StudentProfile.user_id == User.id)
        .where(*base_filters)
    )
    total = int((await db.execute(count_stmt)).scalar_one())

    stmt = (
        select(StudentProfile, User)
        .join(User, StudentProfile.user_id == User.id)
        .where(*base_filters)
        .order_by(User.full_name.asc(), StudentProfile.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return ([
        StudentAdminResponse(
            student_profile_id=profile.id,
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            gender=user.gender,
            department_id=user.department_id,
            batch_id=profile.batch_id,
            enrollment_number=profile.enrollment_number,
            degree_type=profile.degree_type,
            program=profile.program,
            semester=profile.semester,
            year_of_study=profile.year_of_study,
            is_active=user.is_active,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
        for profile, user in rows
    ], total)


async def student_summary_by_department(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    q: Optional[str] = None,
    department_id: Optional[uuid.UUID] = None,
    batch_id: Optional[uuid.UUID] = None,
    degree_type: Optional[str] = None,
    semester: Optional[int] = None,
    year_of_study: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> StudentSummaryResponse:
    from app.models.institution import Department

    base_filters = _student_admin_filters(
        institution_id,
        q=q,
        department_id=department_id,
        batch_id=batch_id,
        degree_type=degree_type,
        semester=semester,
        year_of_study=year_of_study,
        is_active=is_active,
    )

    stmt = (
        select(User.department_id, Department.name, func.count())
        .select_from(StudentProfile)
        .join(User, StudentProfile.user_id == User.id)
        .outerjoin(Department, User.department_id == Department.id)
        .where(*base_filters)
        .group_by(User.department_id, Department.name)
        .order_by(func.count().desc(), Department.name)
    )
    rows = (await db.execute(stmt)).all()
    by_department = [
        StudentDepartmentCount(
            department_id=dept_id,
            department_name=name or "Unassigned",
            count=int(count),
        )
        for dept_id, name, count in rows
    ]
    return StudentSummaryResponse(
        total=sum(item.count for item in by_department),
        by_department=by_department,
        semester=semester,
        year_of_study=year_of_study,
        degree_type=degree_type,
        batch_id=batch_id,
        is_active=is_active,
    )


async def onboard_student(
    db: AsyncSession,
    payload: StudentAdminCreate,
    *,
    institution_id: uuid.UUID,
) -> StudentAdminResponse:
    import app.services.audit_log_service as audit_svc
    from app.models.audit_log import AuditAction

    user = await user_svc.create(
        db,
        UserCreate(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            role=UserRole.STUDENT,
            institution_id=institution_id,
            department_id=payload.department_id,
            phone=payload.phone,
            gender=payload.gender,
        ),
    )
    profile = await create_profile(
        db,
        StudentProfileCreate(
            user_id=user.id,
            batch_id=payload.batch_id,
            enrollment_number=payload.enrollment_number,
            degree_type=payload.degree_type,
            program=payload.program,
            semester=payload.semester,
            year_of_study=payload.year_of_study,
        ),
    )
    await audit_svc.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="Student",
        entity_id=profile.id,
        entity_label=payload.email,
        institution_id=institution_id,
        after={"enrollment_number": payload.enrollment_number, "user_id": str(user.id)},
    )
    return await get_student_admin(db, profile.id)


async def update_student_admin(
    db: AsyncSession,
    profile_id: uuid.UUID,
    payload: StudentAdminUpdate,
) -> StudentAdminResponse:
    import app.services.audit_log_service as audit_svc
    from app.models.audit_log import AuditAction

    profile = await get_profile_or_404(db, profile_id)
    user = await user_svc.get_or_404(db, profile.user_id)

    user_fields = {}
    if payload.full_name is not None:
        user_fields["full_name"] = payload.full_name
    if payload.email is not None:
        user_fields["email"] = payload.email
    if payload.phone is not None:
        user_fields["phone"] = payload.phone
    if payload.gender is not None:
        user_fields["gender"] = payload.gender
    if payload.department_id is not None:
        user_fields["department_id"] = payload.department_id
    if payload.is_active is not None:
        user_fields["is_active"] = payload.is_active
    if user_fields:
        user = await user_svc.update(db, user.id, UserUpdate(**user_fields))

    profile_fields = payload.model_dump(
        exclude_unset=True,
        exclude={"full_name", "email", "phone", "gender", "department_id", "is_active"},
    )
    if profile_fields:
        profile = await update_profile(db, profile.id, StudentProfileUpdate(**profile_fields))
    else:
        await auto_allocate_profile_if_timetable_published(db, profile)

    await audit_svc.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="Student",
        entity_id=profile.id,
        entity_label=user.email,
        institution_id=user.institution_id,
        after={k: str(v) if v is not None else None for k, v in payload.model_dump(exclude_unset=True).items()},
    )
    return await get_student_admin(db, profile_id)


async def hard_delete_student(
    db: AsyncSession,
    profile_id: uuid.UUID,
) -> None:
    import app.services.audit_log_service as audit_svc
    from app.models.audit_log import AuditAction

    profile = await get_profile_or_404(db, profile_id)
    user = await user_svc.get_or_404(db, profile.user_id)
    _institution_id = user.institution_id
    _email_label = user.email
    # Profile must be deleted before the User to avoid SQLAlchemy trying to
    # SET user_id = NULL (the column is NOT NULL, causing an IntegrityError).
    await db.delete(profile)
    await db.delete(user)
    await db.flush()
    await audit_svc.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="Student",
        entity_id=profile_id,
        entity_label=_email_label,
        institution_id=_institution_id,
    )


async def get_student_admin(
    db: AsyncSession,
    profile_id: uuid.UUID,
) -> StudentAdminResponse:
    profile = await get_profile_or_404(db, profile_id)
    user = await user_svc.get_or_404(db, profile.user_id)
    return StudentAdminResponse(
        student_profile_id=profile.id,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        gender=user.gender,
        department_id=user.department_id,
        batch_id=profile.batch_id,
        enrollment_number=profile.enrollment_number,
        degree_type=profile.degree_type,
        program=profile.program,
        semester=profile.semester,
        year_of_study=profile.year_of_study,
        is_active=user.is_active,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


# ---------------------------------------------------------------------------
# StudentProfile
# ---------------------------------------------------------------------------


async def get_profile_by_user(
    db: AsyncSession, user_id: uuid.UUID
) -> Optional[StudentProfile]:
    """Return the StudentProfile for *user_id*, or None."""
    result = await db.execute(
        select(StudentProfile).where(StudentProfile.user_id == user_id)
    )
    profile = result.scalars().first()
    if profile is not None:
        await auto_allocate_profile_if_timetable_published(db, profile)
    return profile


async def get_profile_or_404(
    db: AsyncSession, profile_id: uuid.UUID
) -> StudentProfile:
    result = await db.execute(
        select(StudentProfile).where(StudentProfile.id == profile_id)
    )
    profile = result.scalars().first()
    if profile is None:
        raise NotFoundError(f"StudentProfile {profile_id} not found")
    await auto_allocate_profile_if_timetable_published(db, profile)
    return profile


async def auto_allocate_profile_if_timetable_published(
    db: AsyncSession,
    profile: StudentProfile,
    *,
    commit: bool = True,
) -> None:
    """
    If there is an already completed and published timetable scenario for this student's
    institution, automatically map the student to the matching cohort (scheduling target).
    """
    from app.models.scenario import Scenario
    from app.models.curriculum import SchedulingTarget

    # 1. Fetch user institution and department info
    user_res = await db.execute(
        select(User.institution_id, User.department_id)
        .where(User.id == profile.user_id)
    )
    user_info = user_res.first()
    if not user_info:
        return
    institution_id, department_id = user_info

    if not institution_id or not department_id or profile.semester is None:
        return

    # 2. Verify current batch is valid. Mismatched semester or department triggers clearing/re-allocation.
    if profile.batch_id is not None:
        target_res = await db.execute(
            select(SchedulingTarget).where(SchedulingTarget.id == profile.batch_id)
        )
        target = target_res.scalar_one_or_none()
        if target:
            if target.department_id == department_id and target.study_semester == profile.semester:
                # Matches current semester and department
                return
            # Mismatched, clear to allow auto allocation
            profile.batch_id = None

    # 3. Find published scenarios for this institution (published_job_id is not None)
    scenarios_res = await db.execute(
        select(Scenario.academic_term_id)
        .where(
            Scenario.institution_id == institution_id,
            Scenario.published_job_id.is_not(None),
            Scenario.deleted_at.is_(None),
        )
    )
    academic_term_ids = list(scenarios_res.scalars().all())

    # 4. Auto-allocate this student for each matching academic term
    old_batch_id = profile.batch_id
    for term_id in academic_term_ids:
        await bulk_auto_allocate_batch(db, [profile.id], term_id)
    if commit and profile.batch_id != old_batch_id:
        await db.commit()


async def create_profile(
    db: AsyncSession,
    payload: StudentProfileCreate,
) -> StudentProfile:
    """
    Create a StudentProfile for a STUDENT-role User.

    Raises ConflictError if a profile already exists for *user_id*
    (one-to-one constraint).
    """
    existing = await get_profile_by_user(db, payload.user_id)
    if existing is not None:
        raise ConflictError(
            f"StudentProfile already exists for user {payload.user_id}"
        )

    user = await user_svc.get_or_404(db, payload.user_id)
    if user.role != UserRole.STUDENT:
        raise ValidationError(
            f"User {payload.user_id} must have STUDENT role before creating a StudentProfile"
        )

    if payload.enrollment_number is not None:
        dup = await db.execute(
            select(StudentProfile).where(
                StudentProfile.enrollment_number == payload.enrollment_number
            )
        )
        if dup.scalars().first() is not None:
            raise ConflictError(
                f"Enrollment number '{payload.enrollment_number}' is already taken"
            )

    profile = StudentProfile(**payload.model_dump())
    db.add(profile)
    await db.flush()
    logger.info(
        "StudentProfile created",
        profile_id=str(profile.id),
        user_id=str(profile.user_id),
    )
    # Auto-allocate if there's an already published timetable scenario
    await auto_allocate_profile_if_timetable_published(db, profile)
    return profile


async def update_profile(
    db: AsyncSession,
    profile_id: uuid.UUID,
    payload: StudentProfileUpdate,
) -> StudentProfile:
    profile = await get_profile_or_404(db, profile_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.flush()
    logger.info("StudentProfile updated", profile_id=str(profile_id))
    # Auto-allocate if there's an already published timetable scenario
    await auto_allocate_profile_if_timetable_published(db, profile)
    return profile


async def bulk_assign_batch(
    db: AsyncSession,
    profile_ids: list[uuid.UUID],
    batch_id: uuid.UUID | None,
    *,
    restrict_to_dept_id: uuid.UUID | None = None,
    academic_term_id: uuid.UUID | None = None,
) -> int:
    """
    Set ``batch_id`` on multiple student profiles in a single UPDATE.

    If *restrict_to_dept_id* is provided (HOD path), every profile must
    belong to a user whose ``department_id`` matches; a ``ValidationError``
    is raised for any violation.

    Returns the number of rows actually updated.
    """
    if not profile_ids:
        return 0

    if restrict_to_dept_id is not None:
        # Verify all profiles belong to the HOD's department
        rows = await db.execute(
            select(StudentProfile.id, User.department_id)
            .join(User, StudentProfile.user_id == User.id)
            .where(StudentProfile.id.in_(profile_ids))
        )
        for row in rows.all():
            if row.department_id != restrict_to_dept_id:
                raise ValidationError(
                    f"Student profile {row.id} does not belong to your department"
                )

    if batch_id is not None:
        from app.models.curriculum import SchedulingTarget
        target_res = await db.execute(
            select(SchedulingTarget.study_semester).where(SchedulingTarget.id == batch_id)
        )
        target_sem = target_res.scalar_one_or_none()
        if target_sem is not None:
            mismatched_res = await db.execute(
                select(StudentProfile.id, StudentProfile.semester)
                .where(StudentProfile.id.in_(profile_ids))
            )
            for pid, sem in mismatched_res.all():
                if sem is not None and sem != target_sem:
                    raise ValidationError(
                        f"Student profile {pid} is in Sem {sem}, but the target batch is in Sem {target_sem}"
                    )

    result = await db.execute(
        update(StudentProfile)
        .where(StudentProfile.id.in_(profile_ids))
        .values(batch_id=batch_id)
        .returning(StudentProfile.id)
    )
    updated = len(result.fetchall())
    await db.flush()
    logger.info(
        "Bulk batch assigned",
        batch_id=str(batch_id) if batch_id else None,
        count=updated,
    )

    if academic_term_id is not None:
        import app.services.student_course_eligibility_service as eligibility_svc

        profiles_result = await db.execute(
            select(StudentProfile, User.department_id)
            .join(User, StudentProfile.user_id == User.id)
            .where(StudentProfile.id.in_(profile_ids))
        )
        by_scope: dict[tuple[uuid.UUID, int], list[uuid.UUID]] = {}
        for profile, dept_id in profiles_result.all():
            if profile.semester is None or dept_id is None:
                continue
            key = (dept_id, profile.semester)
            by_scope.setdefault(key, []).append(profile.id)

        for (dept_id, study_semester), ids in by_scope.items():
            if batch_id is None:
                await eligibility_svc.clear_core_eligibility(
                    db,
                    ids,
                    academic_term_id=academic_term_id,
                    study_semester=study_semester,
                )
            else:
                await eligibility_svc.seed_core_eligibility_for_profiles(
                    db,
                    ids,
                    academic_term_id=academic_term_id,
                    department_id=dept_id,
                    study_semester=study_semester,
                )

    return updated


async def bulk_auto_allocate_batch(
    db: AsyncSession,
    profile_ids: list[uuid.UUID],
    academic_term_id: uuid.UUID,
    *,
    restrict_to_dept_id: uuid.UUID | None = None,
) -> int:
    """
    Automatically assign multiple student profiles to their matching scheduling targets (cohorts/batches)
    based on the student's department and semester for the active academic term.
    """
    if not profile_ids:
        return 0

    # 1. Fetch all student profiles with their linked User details
    query = (
        select(StudentProfile, User.department_id)
        .join(User, StudentProfile.user_id == User.id)
        .where(StudentProfile.id.in_(profile_ids))
    )
    result = await db.execute(query)
    students = result.all()

    # If restrict_to_dept_id is provided, validate that all profiles belong to that department
    if restrict_to_dept_id is not None:
        for profile, dept_id in students:
            if dept_id != restrict_to_dept_id:
                raise ValidationError(
                    f"Student profile {profile.id} does not belong to your department"
                )

    # 2. Fetch all scheduling targets of type COHORT or BATCH for the term
    from app.models.curriculum import SchedulingTarget
    from sqlalchemy import or_
    targets_query = select(SchedulingTarget).where(
        SchedulingTarget.academic_term_id == academic_term_id,
        SchedulingTarget.is_active.is_(True),
        or_(
            SchedulingTarget.target_type == "COHORT",
            SchedulingTarget.target_type == "BATCH"
        )
    )
    targets_result = await db.execute(targets_query)
    targets = targets_result.scalars().all()

    # Create a mapping helper: (department_id_str, study_semester) -> target_id
    target_map = {}
    for t in targets:
        if t.department_id and t.study_semester is not None:
            key = (str(t.department_id), t.study_semester)
            # Prefer COHORT target type for automatic planning assignments
            if key not in target_map or t.target_type == "COHORT":
                target_map[key] = t.id

    # 3. Process allocation and group by batch for eligibility seeding
    updated_count = 0
    assigned_by_batch_scope: dict[tuple[uuid.UUID, uuid.UUID, int], list[uuid.UUID]] = {}
    
    for profile, dept_id in students:
        if not dept_id or profile.semester is None:
            continue
        
        target_id = target_map.get((str(dept_id), profile.semester))
        if target_id:
            profile.batch_id = target_id
            updated_count += 1
            
            # Group for eligibility seeding: (batch_id, dept_id, study_semester) -> student_profile_ids
            scope_key = (target_id, dept_id, profile.semester)
            assigned_by_batch_scope.setdefault(scope_key, []).append(profile.id)

    await db.flush()
    logger.info(
        "Bulk auto-allocated batch",
        count=updated_count,
    )

    # 4. Seed core eligibility for successfully assigned profiles
    if updated_count > 0:
        import app.services.student_course_eligibility_service as eligibility_svc
        for (batch_id, dept_id, study_semester), ids in assigned_by_batch_scope.items():
            await eligibility_svc.seed_core_eligibility_for_profiles(
                db,
                ids,
                academic_term_id=academic_term_id,
                department_id=dept_id,
                study_semester=study_semester,
            )

    return updated_count


async def list_profiles_by_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[StudentProfile]:
    """Return all student profiles in a given batch (scheduling target)."""
    result = await db.execute(
        select(StudentProfile)
        .where(StudentProfile.batch_id == batch_id)
        .order_by(StudentProfile.enrollment_number)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# StudentRegistration  (FFCS Phase 2 — confirmed picks)
# ---------------------------------------------------------------------------


async def list_registrations(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    status: Optional[RegistrationStatus] = None,
    skip: int = 0,
    limit: int = 20,
) -> list[StudentRegistration]:
    """Return all registrations for *student_id*."""
    q = select(StudentRegistration).where(
        StudentRegistration.student_id == student_id
    )
    if status is not None:
        q = q.where(StudentRegistration.status == status)
    q = q.order_by(StudentRegistration.registered_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def list_registrations_by_offering(
    db: AsyncSession,
    offering_id: uuid.UUID,
    *,
    status: Optional[RegistrationStatus] = None,
) -> list[StudentRegistration]:
    """Return all student registrations for a specific CourseOffering."""
    q = select(StudentRegistration).where(
        StudentRegistration.offering_id == offering_id
    )
    if status is not None:
        q = q.where(StudentRegistration.status == status)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_registration_or_404(
    db: AsyncSession, registration_id: uuid.UUID
) -> StudentRegistration:
    result = await db.execute(
        select(StudentRegistration).where(StudentRegistration.id == registration_id)
    )
    reg = result.scalars().first()
    if reg is None:
        raise NotFoundError(f"StudentRegistration {registration_id} not found")
    return reg


async def register_offering(
    db: AsyncSession,
    student_id: uuid.UUID,
    offering_id: uuid.UUID,
) -> StudentRegistration:
    """
    FFCS Phase 2: confirm a course offering registration.

    Flow:
      1. Check for any existing registration for this student × offering.
         - CONFIRMED  → raise ConflictError (already active).
         - DROPPED    → reactivate (re-book seat, reset status to CONFIRMED).
         - None found → create a new row.
      2. Call curriculum_service.book_seat (SELECT FOR UPDATE + increment).
      3. Create or reactivate the StudentRegistration row.

    Raises
    ------
    ConflictError   if student already has a CONFIRMED registration for this offering.
    ValidationError if the offering is frozen.
    ConflictError   if no seats are available.
    """
    # 0. Check Access Config & Selection Window
    profile_res = await db.execute(
        select(StudentProfile, User).join(User, StudentProfile.user_id == User.id).where(StudentProfile.id == student_id)
    )
    row = profile_res.first()
    if not row:
        raise NotFoundError(f"StudentProfile {student_id} not found")
    
    profile, user = row

    term_res = await db.execute(
        select(AcademicTerm).where(AcademicTerm.institution_id == user.institution_id, AcademicTerm.is_active == True)
    )
    active_term = term_res.scalars().first()

    if active_term:
        cfg_res = await db.execute(
            select(SelectionAccessConfig).where(
                SelectionAccessConfig.institution_id == user.institution_id,
                SelectionAccessConfig.academic_term_id == active_term.id
            )
        )
        cfg = cfg_res.scalars().first()

        # Check early access emails
        is_early_access = cfg and cfg.early_access_emails and user.email in cfg.early_access_emails

        if not is_early_access:
            if cfg:
                # Check booking gates. Empty arrays mean "block all" for that dimension.
                if profile.year_of_study not in (cfg.allowed_booking_years or []):
                    raise AuthorizationError("Booking is not yet open for your batch.")
                if not user.department_id or str(user.department_id) not in (cfg.allowed_booking_departments or []):
                    raise AuthorizationError("Booking is not yet open for your department.")

            # Check Selection Window
            if user.department_id and profile.semester:
                window_res = await db.execute(
                    select(DepartmentSelectionWindow).where(
                        DepartmentSelectionWindow.academic_term_id == active_term.id,
                        DepartmentSelectionWindow.department_id == user.department_id,
                        DepartmentSelectionWindow.study_semester == profile.semester
                    )
                )
                window = window_res.scalars().first()
                if not window or window.status != SelectionWindowStatus.OPEN:
                    raise AuthorizationError("The registration window is not open for your batch.")

        # Extract seat override
        dept_override = None
        if cfg and user.department_id:
            for override in cfg.group_seat_overrides:
                if override.get("department_id") == str(user.department_id):
                    dept_override = override.get("max_seats")
                    break

    # 1. Check for any existing registration (CONFIRMED or DROPPED)
    result = await db.execute(
        select(StudentRegistration).where(
            StudentRegistration.student_id == student_id,
            StudentRegistration.offering_id == offering_id,
        )
    )
    existing_reg = result.scalars().first()

    import app.services.audit_log_service as audit_svc
    from app.models.audit_log import AuditAction

    if existing_reg is not None:
        if existing_reg.status == RegistrationStatus.CONFIRMED:
            raise ConflictError(
                f"Student {student_id} is already registered for offering {offering_id}"
            )
        # Re-registration after drop: reactivate the existing row
        await curriculum_svc.book_seat(db, offering_id, user.department_id, dept_override)
        existing_reg.status = RegistrationStatus.CONFIRMED
        await db.flush()
        logger.info(
            "Registration reactivated",
            registration_id=str(existing_reg.id),
            student_id=str(student_id),
            offering_id=str(offering_id),
        )
        await audit_svc.record(
            db,
            actor_user_id=student_id,
            actor_role=None,
            action=AuditAction.UPDATED,
            entity_type="StudentRegistration",
            entity_id=existing_reg.id,
            entity_label=str(offering_id),
            after={"status": "CONFIRMED", "reactivated": True},
        )
        return existing_reg

    # 2. Book the seat (raises on frozen / full)
    await curriculum_svc.book_seat(db, offering_id, user.department_id, dept_override)

    # 3. Create registration row
    reg = StudentRegistration(
        student_id=student_id,
        offering_id=offering_id,
        status=RegistrationStatus.CONFIRMED,
    )
    db.add(reg)
    await db.flush()
    logger.info(
        "Student registered",
        registration_id=str(reg.id),
        student_id=str(student_id),
        offering_id=str(offering_id),
    )
    await audit_svc.record(
        db,
        actor_user_id=student_id,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="StudentRegistration",
        entity_id=reg.id,
        entity_label=str(offering_id),
        after={"status": "CONFIRMED"},
    )
    return reg


async def drop_registration(
    db: AsyncSession,
    registration_id: uuid.UUID,
) -> StudentRegistration:
    """
    Drop a CONFIRMED or WAITLISTED registration.

    Decrements booked_seats on the offering (Phase 2 reversal).
    Sets status = DROPPED (soft delete — history is preserved).
    """
    import app.services.audit_log_service as audit_svc
    from app.models.audit_log import AuditAction

    reg = await get_registration_or_404(db, registration_id)

    if reg.status == RegistrationStatus.DROPPED:
        raise ValidationError("Registration is already dropped")

    # Only decrement for CONFIRMED (WAITLISTED was never seated)
    if reg.status == RegistrationStatus.CONFIRMED:
        await curriculum_svc.release_seat(db, reg.offering_id)

    reg.status = RegistrationStatus.DROPPED
    await db.flush()
    logger.info(
        "Registration dropped",
        registration_id=str(registration_id),
        student_id=str(reg.student_id),
        offering_id=str(reg.offering_id),
    )
    await audit_svc.record(
        db,
        actor_user_id=reg.student_id,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="StudentRegistration",
        entity_id=registration_id,
        entity_label=str(reg.offering_id),
        after={"status": "DROPPED"},
    )
    return reg


# ---------------------------------------------------------------------------
# StudentWishlist  (FFCS Phase 1 — draft plan, no seat lock)
# ---------------------------------------------------------------------------


async def list_wishlists(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    academic_term_id: Optional[uuid.UUID] = None,
) -> list[StudentWishlist]:
    q = select(StudentWishlist).where(StudentWishlist.student_id == student_id)
    if academic_term_id is not None:
        q = q.where(StudentWishlist.academic_term_id == academic_term_id)
    q = q.order_by(StudentWishlist.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_wishlist_or_404(
    db: AsyncSession, wishlist_id: uuid.UUID
) -> StudentWishlist:
    result = await db.execute(
        select(StudentWishlist).where(StudentWishlist.id == wishlist_id)
    )
    wl = result.scalars().first()
    if wl is None:
        raise NotFoundError(f"StudentWishlist {wishlist_id} not found")
    return wl


async def create_wishlist(
    db: AsyncSession,
    payload: StudentWishlistCreate,
) -> StudentWishlist:
    """Create a named wishlist plan. offering_ids are not FK-validated here."""
    wl = StudentWishlist(
        student_id=payload.student_id,
        academic_term_id=payload.academic_term_id,
        name=payload.name,
        offering_ids=[str(oid) for oid in payload.offering_ids],
    )
    db.add(wl)
    await db.flush()
    logger.info(
        "StudentWishlist created",
        wishlist_id=str(wl.id),
        student_id=str(payload.student_id),
        count=len(payload.offering_ids),
    )
    return wl


async def update_wishlist(
    db: AsyncSession,
    wishlist_id: uuid.UUID,
    payload: StudentWishlistUpdate,
) -> StudentWishlist:
    wl = await get_wishlist_or_404(db, wishlist_id)
    if payload.name is not None:
        wl.name = payload.name
    if payload.offering_ids is not None:
        wl.offering_ids = [str(oid) for oid in payload.offering_ids]
    await db.flush()
    logger.info("StudentWishlist updated", wishlist_id=str(wishlist_id))
    return wl


async def delete_wishlist(db: AsyncSession, wishlist_id: uuid.UUID) -> None:
    wl = await get_wishlist_or_404(db, wishlist_id)
    await db.delete(wl)
    await db.flush()
    logger.info("StudentWishlist deleted", wishlist_id=str(wishlist_id))
