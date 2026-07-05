"""
app/services/institution_service.py
=====================================
CRUD for Infrastructure layer: Institution, Department, AcademicTerm.

Responsibilities
----------------
* Institution: create, list, get, update (soft-disable via is_active).
* Department: create per institution, list, get, update.
* AcademicTerm: create per institution, list, get, update, set_status.

Architecture notes
------------------
Institutions are the root tenant object — scoping every other resource.
Departments are used for HOD access boundaries (department_id FK on User,
Faculty, SchedulingTarget, OfferingBucket).
AcademicTerms are referenced as loose UUIDs by most other tables
(scenarios, time_grids, exam_scenarios, student_wishlists).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logger import logger
import app.services.audit_log_service as audit_log_service
from app.models.analytics import AnalyticsSnapshot
from app.models.audit_log import AuditAction
from app.models.curriculum import (
    CourseShareConfig,
    OfferingBucket,
    SchedulingTarget,
    TargetCourseDemand,
    TeachingAssignment,
)
from app.models.exam import ExamScenario
from app.models.faculty import Faculty
from app.models.institution import AcademicTerm, AcademicTermStatus, Department, Institution
from app.models.scenario import Scenario
from app.models.student import StudentWishlist
from app.models.time_grid import TimeGrid
from app.models.user import User, UserRole
from app.schemas.institution import (
    AcademicTermCreate,
    AcademicTermUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    DependentCountsResponse,
    InstitutionCreate,
    InstitutionUpdate,
)


# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------


async def list_institutions(
    db: AsyncSession,
    *,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> list[Institution]:
    """Return all institutions (super-admin view)."""
    q = select(Institution)
    if active_only:
        q = q.where(Institution.is_active == True)  # noqa: E712
    q = q.order_by(Institution.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_institution_by_id(
    db: AsyncSession, institution_id: uuid.UUID
) -> Optional[Institution]:
    result = await db.execute(
        select(Institution).where(Institution.id == institution_id)
    )
    return result.scalars().first()


async def get_institution_or_404(
    db: AsyncSession, institution_id: uuid.UUID
) -> Institution:
    inst = await get_institution_by_id(db, institution_id)
    if inst is None:
        raise NotFoundError(f"Institution {institution_id} not found")
    return inst


async def get_institution_by_domain(
    db: AsyncSession, domain: str
) -> Optional[Institution]:
    result = await db.execute(
        select(Institution).where(Institution.domain == domain)
    )
    return result.scalars().first()


async def create_institution(
    db: AsyncSession,
    payload: InstitutionCreate,
) -> Institution:
    if payload.domain:
        existing = await get_institution_by_domain(db, payload.domain)
        if existing is not None:
            raise ConflictError(f"Domain '{payload.domain}' is already registered")

    inst = Institution(**payload.model_dump())
    db.add(inst)
    await db.flush()
    logger.info("Institution created", institution_id=str(inst.id), name=inst.name)
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="Institution",
        entity_id=inst.id,
        entity_label=inst.name,
        institution_id=inst.id,
    )
    return inst


async def update_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    payload: InstitutionUpdate,
) -> Institution:
    inst = await get_institution_or_404(db, institution_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "domain" in update_data and update_data["domain"]:
        existing = await get_institution_by_domain(db, update_data["domain"])
        if existing is not None and existing.id != institution_id:
            raise ConflictError(f"Domain '{update_data['domain']}' is already taken")
    for field, value in update_data.items():
        setattr(inst, field, value)
    await db.flush()
    logger.info("Institution updated", institution_id=str(institution_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="Institution",
        entity_id=institution_id,
        entity_label=inst.name,
        institution_id=institution_id,
    )
    return inst


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------


async def list_departments(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[Department]:
    q = select(Department).where(Department.institution_id == institution_id)
    if active_only:
        q = q.where(Department.is_active == True)  # noqa: E712
    q = q.order_by(Department.code).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_department_by_id(
    db: AsyncSession, dept_id: uuid.UUID
) -> Optional[Department]:
    result = await db.execute(select(Department).where(Department.id == dept_id))
    return result.scalars().first()


async def get_department_or_404(
    db: AsyncSession, dept_id: uuid.UUID
) -> Department:
    dept = await get_department_by_id(db, dept_id)
    if dept is None:
        raise NotFoundError(f"Department {dept_id} not found")
    return dept


async def create_department(
    db: AsyncSession,
    payload: DepartmentCreate,
) -> Department:
    # Unique code per institution
    existing = await db.execute(
        select(Department).where(
            Department.institution_id == payload.institution_id,
            Department.code == payload.code,
        )
    )
    if existing.scalars().first() is not None:
        raise ConflictError(
            f"Department code '{payload.code}' already exists in this institution"
        )
    dept = Department(**payload.model_dump())
    db.add(dept)
    await db.flush()
    logger.info(
        "Department created",
        dept_id=str(dept.id),
        code=dept.code,
        institution_id=str(payload.institution_id),
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="Department",
        entity_id=dept.id,
        entity_label=f"{dept.code} — {dept.name}",
        institution_id=dept.institution_id,
    )
    return dept


async def hard_delete_department(
    db: AsyncSession,
    dept_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> None:
    """
    Permanently delete a department and all its child records via DB cascade.

    Only callable by SUPER_ADMIN (enforced at the route layer).
    Audit-logs the deletion before the row is gone.
    """
    dept = await get_department_or_404(db, dept_id)
    label = f"{dept.code} — {dept.name}"
    institution_id = dept.institution_id

    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="Department",
        entity_id=dept_id,
        entity_label=label,
        institution_id=institution_id,
    )

    await db.delete(dept)
    await db.flush()
    logger.warning(
        "Department hard-deleted",
        dept_id=str(dept_id),
        label=label,
        actor=str(actor_user_id),
    )


async def archive_term(
    db: AsyncSession,
    term_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> AcademicTerm:
    """Soft-delete an academic term by setting deleted_at."""
    term = await get_term_include_deleted(db, term_id)
    if term is None:
        raise NotFoundError(f"AcademicTerm {term_id} not found")
    if term.deleted_at is not None:
        raise ConflictError(f"AcademicTerm {term_id} is already archived")
    label = term.name
    institution_id = term.institution_id

    term.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="AcademicTerm",
        entity_id=term_id,
        entity_label=label,
        institution_id=institution_id,
    )

    logger.warning(
        "AcademicTerm archived (soft-delete)",
        term_id=str(term_id),
        label=label,
        actor=str(actor_user_id),
    )
    return term


async def restore_term(
    db: AsyncSession,
    term_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> AcademicTerm:
    """Restore a soft-deleted academic term by clearing deleted_at."""
    term = await get_term_include_deleted(db, term_id)
    if term is None:
        raise NotFoundError(f"AcademicTerm {term_id} not found")
    if term.deleted_at is None:
        raise ConflictError(f"AcademicTerm {term_id} is not archived")
    label = term.name
    institution_id = term.institution_id

    term.deleted_at = None
    await db.flush()

    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.RESTORED,
        entity_type="AcademicTerm",
        entity_id=term_id,
        entity_label=label,
        institution_id=institution_id,
    )

    logger.info(
        "AcademicTerm restored",
        term_id=str(term_id),
        label=label,
        actor=str(actor_user_id),
    )
    return term


async def get_term_dependents(
    db: AsyncSession, term_id: uuid.UUID
) -> DependentCountsResponse:
    """Count dependent records across all 10 tables referencing academic_term_id."""
    queries: dict[str, type] = {
        "teaching_assignments": TeachingAssignment,
        "scheduling_targets": SchedulingTarget,
        "offering_buckets": OfferingBucket,
        "target_course_demands": TargetCourseDemand,
        "course_share_configs": CourseShareConfig,
        "student_wishlists": StudentWishlist,
        "time_grids": TimeGrid,
        "scenarios": Scenario,
        "exam_scenarios": ExamScenario,
        "analytics_snapshots": AnalyticsSnapshot,
    }

    counts: dict[str, int] = {}
    for field_name, model in queries.items():
        result = await db.execute(
            select(func.count()).where(model.academic_term_id == term_id)  # type: ignore[arg-type]
        )
        counts[field_name] = result.scalar() or 0

    return DependentCountsResponse(**counts)


async def purge_term(
    db: AsyncSession,
    term_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> None:
    """Permanently delete an academic term.

    Raises ConflictError if dependent records exist. User must delete
    dependent records first. When the FK RESTRICT migrations are applied,
    this will also fail at the DB level if any dependents remain,
    providing a double safety net.
    """
    term = await get_term_include_deleted(db, term_id)
    if term is None:
        raise NotFoundError(f"AcademicTerm {term_id} not found")
    if term.deleted_at is None:
        raise ConflictError("Term must be archived before purging. Archive it first.")

    dependents = await get_term_dependents(db, term_id)
    if dependents.total > 0:
        raise ConflictError(
            f"Cannot purge term '{term.name}': {dependents.total} dependent record(s) exist. "
            f"Delete them first. Check GET /terms/{term_id}/dependents for details.",
            details=dependents.model_dump(),
        )

    label = term.name
    institution_id = term.institution_id

    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="AcademicTerm",
        entity_id=term_id,
        entity_label=label,
        institution_id=institution_id,
    )

    await db.delete(term)
    await db.flush()
    logger.warning(
        "AcademicTerm permanently purged",
        term_id=str(term_id),
        label=label,
        actor=str(actor_user_id),
    )


async def _resolve_hod_name(db: AsyncSession, dept: Department) -> str | None:
    if dept.hod_faculty_id is None:
        return None
    result = await db.execute(
        select(Faculty.name).where(Faculty.id == dept.hod_faculty_id)
    )
    return result.scalar_one_or_none()


async def bulk_hod_names(
    db: AsyncSession, depts: list[Department]
) -> dict[uuid.UUID, str]:
    ids = [d.hod_faculty_id for d in depts if d.hod_faculty_id is not None]
    if not ids:
        return {}
    rows = await db.execute(
        select(Faculty.id, Faculty.name).where(Faculty.id.in_(ids))
    )
    return {r.id: r.name for r in rows}


async def update_department(
    db: AsyncSession,
    dept_id: uuid.UUID,
    payload: DepartmentUpdate,
    actor_role: str | None = None,
) -> tuple[Department, str | None]:
    dept = await get_department_or_404(db, dept_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "hod_faculty_id" in update_data and actor_role not in ("admin", "super_admin"):
        raise ValidationError("Admin or super_admin access required to assign HOD.")

    if update_data.get("hod_faculty_id") is not None:
        result = await db.execute(
            select(Faculty).join(User, Faculty.user_id == User.id).where(
                Faculty.id == update_data["hod_faculty_id"],
                User.department_id == dept_id,
            )
        )
        if result.scalars().first() is None:
            raise ValidationError("HOD faculty must belong to this department.")

    old_hod_faculty_id = dept.hod_faculty_id

    for field, value in update_data.items():
        setattr(dept, field, value)
    await db.flush()

    # Sync the linked User's role when hod_faculty_id changes
    new_hod_faculty_id = dept.hod_faculty_id
    if new_hod_faculty_id != old_hod_faculty_id:
        if old_hod_faculty_id is not None:
            old_result = await db.execute(
                select(User).join(Faculty, Faculty.user_id == User.id).where(
                    Faculty.id == old_hod_faculty_id
                )
            )
            old_user = old_result.scalar_one_or_none()
            if old_user is not None and old_user.role == UserRole.HOD:
                old_user.role = UserRole.TEACHER
                logger.info(
                    "HOD cleared — user demoted to teacher",
                    user_id=str(old_user.id),
                    faculty_id=str(old_hod_faculty_id),
                )

        if new_hod_faculty_id is not None:
            new_result = await db.execute(
                select(User).join(Faculty, Faculty.user_id == User.id).where(
                    Faculty.id == new_hod_faculty_id
                )
            )
            new_user = new_result.scalar_one_or_none()
            if new_user is not None:
                new_user.role = UserRole.HOD
                logger.info(
                    "HOD set — user promoted to hod",
                    user_id=str(new_user.id),
                    faculty_id=str(new_hod_faculty_id),
                )

    hod_name = await _resolve_hod_name(db, dept)
    logger.info("Department updated", dept_id=str(dept_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="Department",
        entity_id=dept_id,
        entity_label=f"{dept.code} — {dept.name}",
        institution_id=dept.institution_id,
    )
    return dept, hod_name


# ---------------------------------------------------------------------------
# AcademicTerm
# ---------------------------------------------------------------------------


async def list_terms(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    active_only: bool = True,
    include_deleted: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> list[AcademicTerm]:
    q = select(AcademicTerm).where(AcademicTerm.institution_id == institution_id)
    if not include_deleted:
        q = q.where(AcademicTerm.deleted_at.is_(None))
    if active_only:
        q = q.where(AcademicTerm.is_active == True)  # noqa: E712
    q = q.order_by(AcademicTerm.start_date.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def resolve_active_academic_term(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> Optional[AcademicTerm]:
    """
    Resolve the institution's current academic term.

    Priority: status ACTIVE → today's date within range → most recent start_date.
    """
    stmt = (
        select(AcademicTerm)
        .where(
            AcademicTerm.institution_id == institution_id,
            AcademicTerm.is_active.is_(True),
            AcademicTerm.deleted_at.is_(None),
        )
        .order_by(AcademicTerm.start_date.desc())
        .limit(10)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return None

    for row in rows:
        if row.status == AcademicTermStatus.ACTIVE:
            return row

    today = date.today()
    for row in rows:
        if row.start_date and row.end_date and row.start_date <= today <= row.end_date:
            return row

    return rows[0]


async def get_term_by_id(
    db: AsyncSession, term_id: uuid.UUID
) -> Optional[AcademicTerm]:
    result = await db.execute(
        select(AcademicTerm).where(
            AcademicTerm.id == term_id,
            AcademicTerm.deleted_at.is_(None),
        )
    )
    return result.scalars().first()


async def get_term_include_deleted(
    db: AsyncSession, term_id: uuid.UUID
) -> Optional[AcademicTerm]:
    """Fetch a term regardless of its deleted_at status."""
    result = await db.execute(
        select(AcademicTerm).where(AcademicTerm.id == term_id)
    )
    return result.scalars().first()


async def get_term_or_404(
    db: AsyncSession, term_id: uuid.UUID
) -> AcademicTerm:
    term = await get_term_by_id(db, term_id)
    if term is None:
        raise NotFoundError(f"AcademicTerm {term_id} not found")
    return term


async def create_term(
    db: AsyncSession,
    payload: AcademicTermCreate,
) -> AcademicTerm:
    term = AcademicTerm(**payload.model_dump())
    db.add(term)
    await db.flush()
    logger.info(
        "AcademicTerm created",
        term_id=str(term.id),
        name=term.name,
        institution_id=str(payload.institution_id),
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="AcademicTerm",
        entity_id=term.id,
        entity_label=term.name,
        institution_id=term.institution_id,
    )
    return term


async def update_term(
    db: AsyncSession,
    term_id: uuid.UUID,
    payload: AcademicTermUpdate,
) -> AcademicTerm:
    term = await get_term_or_404(db, term_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(term, field, value)
    await db.flush()
    logger.info("AcademicTerm updated", term_id=str(term_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="AcademicTerm",
        entity_id=term_id,
        entity_label=term.name,
        institution_id=term.institution_id,
    )
    return term


async def set_term_status(
    db: AsyncSession,
    term_id: uuid.UUID,
    status: AcademicTermStatus,
) -> AcademicTerm:
    """
    Transition an AcademicTerm's lifecycle status.

    Allowed transitions (enforced by caller; not database-level):
      PLANNING → ACTIVE → COMPLETED → ARCHIVED
    """
    term = await get_term_or_404(db, term_id)
    old_status = term.status.value if term.status else None
    term.status = status
    await db.flush()
    logger.info("AcademicTerm status set", term_id=str(term_id), status=status.value)
    action = AuditAction.ARCHIVED if status == AcademicTermStatus.ARCHIVED else AuditAction.TOGGLED
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=action,
        entity_type="AcademicTerm",
        entity_id=term_id,
        entity_label=term.name,
        institution_id=term.institution_id,
        before={"status": old_status},
        after={"status": status.value},
    )
    return term
