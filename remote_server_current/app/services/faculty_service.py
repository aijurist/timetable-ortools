"""
app/services/faculty_service.py
=================================
CRUD and availability management for Faculty solver resources.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logger import logger
from app.models.faculty import Faculty
from app.models.institution import Department
from app.models.user import User, UserRole
from app.schemas.faculty import FacultyCreate, FacultyResponse, FacultyUpdate


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _apply_faculty_filters(
    q,
    *,
    institution_id: uuid.UUID,
    department_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    active_only: bool = True,
):
    q = q.where(Faculty.institution_id == institution_id)
    if active_only:
        q = q.where(Faculty.is_active == True)  # noqa: E712
    if department_id is not None or search:
        q = q.join(User, Faculty.user_id == User.id, isouter=True)
    if department_id is not None:
        q = q.where(User.department_id == department_id)
    if search:
        term = f"%{search.lower()}%"
        q = q.where(Faculty.name.ilike(term) | User.email.ilike(term))
    return q


async def get_summary(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    department_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    active_only: bool = True,
) -> dict[str, object]:
    counts_q = _apply_faculty_filters(
        select(Faculty.employment_type, func.count()).group_by(Faculty.employment_type),
        institution_id=institution_id,
        department_id=department_id,
        search=search,
        active_only=active_only,
    )
    counts_result = await db.execute(counts_q)
    employment_counts: dict[str, int] = {}
    for employment_type, count in counts_result.all():
        key = employment_type.value if hasattr(employment_type, "value") else str(employment_type)
        employment_counts[key] = count

    hours_q = _apply_faculty_filters(
        select(func.coalesce(func.sum(Faculty.max_weekly_hours), 0)),
        institution_id=institution_id,
        department_id=department_id,
        search=search,
        active_only=active_only,
    )
    hours_result = await db.execute(hours_q)

    return {
        "employment_counts": employment_counts,
        "total_max_weekly_hours": int(hours_result.scalar_one() or 0),
        "avg_load_percent": 0,
    }


async def list_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    department_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[Faculty]:
    q = _apply_faculty_filters(
        select(Faculty),
        institution_id=institution_id,
        department_id=department_id,
        search=search,
        active_only=active_only,
    )
    q = q.order_by(Faculty.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.unique().scalars().all())


async def count_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    department_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    active_only: bool = True,
) -> int:
    q = _apply_faculty_filters(
        select(func.count()).select_from(Faculty),
        institution_id=institution_id,
        department_id=department_id,
        search=search,
        active_only=active_only,
    )
    result = await db.execute(q)
    return result.scalar_one()


async def _get_hod_department_map(
    db: AsyncSession,
    faculty_ids: set[uuid.UUID],
) -> dict[uuid.UUID, tuple[str, str]]:
    """Return {faculty_id: (dept_code, dept_name)} for faculty who are HODs."""
    if not faculty_ids:
        return {}
    result = await db.execute(
        select(Department.hod_faculty_id, Department.code, Department.name).where(
            Department.hod_faculty_id.in_(faculty_ids)
        )
    )
    return {row.hod_faculty_id: (row.code, row.name) for row in result}


async def to_response(
    db: AsyncSession,
    faculty: Faculty,
) -> FacultyResponse:
    # Resolve all user fields (dept, email, phone, gender) without touching lazy relationships
    dept_id: uuid.UUID | None = None
    department_name: str | None = None
    user_email: str | None = None
    user_phone: str | None = None
    user_gender = None
    if faculty.user_id is not None:
        user_result = await db.execute(
            select(User.department_id, User.email, User.phone, User.gender)
            .where(User.id == faculty.user_id)
        )
        user_row = user_result.first()
        if user_row:
            dept_id = user_row.department_id
            user_email = user_row.email
            user_phone = user_row.phone
            user_gender = user_row.gender

    if dept_id is not None:
        department_name = await db.scalar(
            select(Department.name).where(Department.id == dept_id)
        )

    hod_dept = await db.execute(
        select(Department.code, Department.name).where(
            Department.hod_faculty_id == faculty.id
        )
    )
    hod_row = hod_dept.first()

    return FacultyResponse(
        id=faculty.id,
        institution_id=faculty.institution_id,
        department_id=dept_id,
        department_name=department_name,
        name=faculty.name,
        email=user_email or "",
        phone=user_phone,
        gender=user_gender,
        staff_code=faculty.staff_code,
        employee_id=faculty.employee_id,
        age=faculty.age,
        employment_type=faculty.employment_type,
        designation=faculty.designation,
        max_weekly_hours=faculty.max_weekly_hours,
        current_load_hours=0,
        availability_blacklist=faculty.availability_blacklist or [],
        preferences=faculty.preferences,
        is_active=faculty.is_active,
        created_at=faculty.created_at,
        updated_at=faculty.updated_at,
        hod_of_department_code=hod_row.code if hod_row else None,
        hod_of_department_name=hod_row.name if hod_row else None,
    )


async def to_response_list(
    db: AsyncSession,
    faculty_items: list[Faculty],
) -> list[FacultyResponse]:
    faculty_ids = {f.id for f in faculty_items}
    hod_map = await _get_hod_department_map(db, faculty_ids)

    # Batch-resolve all user fields (department, email, phone, gender) in one query
    linked_user_ids = [f.user_id for f in faculty_items if f.user_id is not None]
    dept_map: dict[uuid.UUID, uuid.UUID | None] = {}
    email_map: dict[uuid.UUID, str] = {}
    phone_map: dict[uuid.UUID, str | None] = {}
    gender_map: dict[uuid.UUID, object] = {}
    if linked_user_ids:
        user_rows = await db.execute(
            select(User.id, User.department_id, User.email, User.phone, User.gender)
            .where(User.id.in_(linked_user_ids))
        )
        for row in user_rows:
            dept_map[row.id] = row.department_id
            email_map[row.id] = row.email
            phone_map[row.id] = row.phone
            gender_map[row.id] = row.gender

    all_department_ids = {d for d in dept_map.values() if d is not None}
    department_name_map: dict[uuid.UUID, str] = {}
    if all_department_ids:
        dept_rows = await db.execute(
            select(Department.id, Department.name).where(
                Department.id.in_(all_department_ids)
            )
        )
        department_name_map = {dept_id: name for dept_id, name in dept_rows.all()}

    return [
        FacultyResponse(
            id=faculty.id,
            institution_id=faculty.institution_id,
            department_id=dept_map.get(faculty.user_id) if faculty.user_id else None,
            department_name=(
                department_name_map.get(dept_map[faculty.user_id])
                if faculty.user_id and dept_map.get(faculty.user_id)
                else None
            ),
            name=faculty.name,
            email=(email_map.get(faculty.user_id) if faculty.user_id else "") or "",
            phone=phone_map.get(faculty.user_id) if faculty.user_id else None,
            gender=gender_map.get(faculty.user_id) if faculty.user_id else None,
            staff_code=faculty.staff_code,
            employee_id=faculty.employee_id,
            age=faculty.age,
            employment_type=faculty.employment_type,
            designation=faculty.designation,
            max_weekly_hours=faculty.max_weekly_hours,
            current_load_hours=0,
            availability_blacklist=faculty.availability_blacklist or [],
            preferences=faculty.preferences,
            is_active=faculty.is_active,
            created_at=faculty.created_at,
            updated_at=faculty.updated_at,
            hod_of_department_code=hod_map[faculty.id][0] if faculty.id in hod_map else None,
            hod_of_department_name=hod_map[faculty.id][1] if faculty.id in hod_map else None,
        )
        for faculty in faculty_items
    ]


async def get_by_id(db: AsyncSession, faculty_id: uuid.UUID) -> Optional[Faculty]:
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    return result.scalars().first()


async def get_or_404(db: AsyncSession, faculty_id: uuid.UUID) -> Faculty:
    faculty = await get_by_id(db, faculty_id)
    if faculty is None:
        raise NotFoundError(f"Faculty {faculty_id} not found")
    return faculty


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    institution_id: uuid.UUID,
    payload: FacultyCreate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Faculty:
    faculty = Faculty(
        institution_id=institution_id,
        **payload.model_dump(exclude={"institution_id"}),
    )
    db.add(faculty)
    await db.flush()
    logger.info("Faculty created", faculty_id=str(faculty.id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.CREATED,
        entity_type="Faculty",
        entity_id=faculty.id,
        entity_label=faculty.name,
        institution_id=institution_id,
    )
    return faculty


async def update(
    db: AsyncSession,
    faculty_id: uuid.UUID,
    payload: FacultyUpdate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Faculty:
    faculty = await get_or_404(db, faculty_id)
    update_data = payload.model_dump(exclude_unset=True)

    # Route department_id to the linked User (single source of truth)
    new_dept_id = update_data.pop("department_id", None)
    if new_dept_id is not None and faculty.user_id:
        user_result = await db.execute(
            select(User).where(User.id == faculty.user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            user.department_id = new_dept_id

    before = {k: getattr(faculty, k) for k in update_data}
    for field, value in update_data.items():
        setattr(faculty, field, value)
    await db.flush()
    logger.info("Faculty updated", faculty_id=str(faculty_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    after = {k: getattr(faculty, k) for k in before}
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="Faculty",
        entity_id=faculty_id,
        entity_label=faculty.name,
        institution_id=faculty.institution_id,
        before=before,
        after=after,
    )
    return faculty


async def update_availability(
    db: AsyncSession,
    faculty_id: uuid.UUID,
    blacklist: list[str],
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Faculty:
    """
    Replace the faculty's ``availability_blacklist`` with *blacklist*.

    *blacklist* is a list of slot codes (e.g. ``["A3", "B5"]``) that map to
    time_grids.slots keys.  An empty list clears all restrictions.
    """
    faculty = await get_or_404(db, faculty_id)
    before_blacklist = list(faculty.availability_blacklist or [])
    faculty.availability_blacklist = blacklist
    await db.flush()
    logger.info(
        "Faculty availability updated",
        faculty_id=str(faculty_id),
        blacklisted_slots=len(blacklist),
    )
    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="Faculty",
        entity_id=faculty_id,
        entity_label=faculty.name,
        institution_id=faculty.institution_id,
        before={"availability_blacklist": before_blacklist},
        after={"availability_blacklist": blacklist},
    )
    return faculty


async def soft_delete(
    db: AsyncSession,
    faculty_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Faculty:
    faculty = await get_or_404(db, faculty_id)
    faculty.is_active = False
    await db.flush()
    logger.info("Faculty deactivated", faculty_id=str(faculty_id))
    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="Faculty",
        entity_id=faculty_id,
        entity_label=faculty.name,
        institution_id=faculty.institution_id,
    )
    return faculty


async def hard_delete(
    db: AsyncSession,
    faculty_id: uuid.UUID,
) -> None:
    faculty = await get_or_404(db, faculty_id)
    linked_user: User | None = None
    if faculty.user_id is not None:
        user_result = await db.execute(
            select(User).where(User.id == faculty.user_id)
        )
        linked_user = user_result.scalar_one_or_none()
        # Only delete if pure TEACHER (faculty-only account).
        # For ADMIN/HOD/SUPER_ADMIN, just unlink.
        if linked_user and linked_user.role != UserRole.TEACHER:
            linked_user = None  # don't delete, just leave the user
    if linked_user:
        await db.delete(linked_user)
    await db.delete(faculty)
    await db.flush()


async def create_with_user(
    db: AsyncSession,
    payload: "FacultyWithUserCreate",
) -> tuple[Faculty, "User"]:
    """Atomically create a Faculty record and a linked TEACHER User account.

    Email is stored only on the User table (single source of truth).
    ``user_service.create()`` handles the email uniqueness check.

    Args:
        db: Async SQLAlchemy session. Caller must ``await db.commit()``.
        payload: Combined faculty + user creation payload.

    Returns:
        Tuple of (Faculty, User) both flushed but not committed.

    Raises:
        ConflictError: If a User with the given email already exists.
    """
    from app.schemas.faculty import FacultyWithUserCreate
    from app.schemas.user import UserCreate
    import app.services.user_service as user_svc

    # 1. Create Faculty first so we get its id (no email — it lives on User)
    faculty = Faculty(
        institution_id=payload.institution_id,
        name=payload.name,
        staff_code=payload.staff_code,
        employee_id=payload.employee_id,
        age=payload.age,
        employment_type=payload.employment_type,
        max_weekly_hours=payload.max_weekly_hours,
        availability_blacklist=payload.availability_blacklist,
        preferences=payload.preferences.model_dump() if payload.preferences else None,
    )
    db.add(faculty)
    await db.flush()  # faculty.id is now available

    # 2. Create linked User — user_service.create does its own email conflict check
    user = await user_svc.create(
        db,
        UserCreate(
            email=payload.email,
            password=payload.password,
            full_name=payload.name,
            role=UserRole.TEACHER,
            institution_id=payload.institution_id,
            department_id=payload.department_id,
            phone=payload.phone,
            gender=payload.gender,
        ),
    )
    # 3. Link Faculty → User (mirrors StudentProfile.user_id pattern)
    faculty.user_id = user.id
    await db.flush()

    logger.info(
        "Faculty+User created atomically",
        faculty_id=str(faculty.id),
        user_id=str(user.id),
        email=payload.email,
    )
    return faculty, user
