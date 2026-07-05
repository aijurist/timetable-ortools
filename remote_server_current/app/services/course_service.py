"""
app/services/course_service.py
================================
CRUD operations for Course solver resources.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logger import logger
from app.models.course import Course, SessionType
from app.models.institution import Department
from app.schemas.course import CourseCreate, CourseResponse, CourseUpdate


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _effective_session_type(
    session_type: SessionType | str,
    structure: dict | None,
) -> str:
    if structure and isinstance(structure, dict):
        theory_hours = int(structure.get("L", 0) or 0) + int(structure.get("T", 0) or 0)
        practical_hours = int(structure.get("P", 0) or 0)
        if theory_hours > 0 and practical_hours > 0:
            return SessionType.BOTH.value
        if practical_hours > 0:
            return SessionType.LAB.value
        return SessionType.THEORY.value

    return session_type.value if hasattr(session_type, "value") else str(session_type)


async def get_session_counts(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    department_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    active_only: bool = True,
) -> dict[str, int]:
    q = select(Course.session_type, Course.structure).where(
        Course.institution_id == institution_id
    )
    if department_id is not None:
        q = q.where(Course.department_id == department_id)
    if active_only:
        q = q.where(Course.is_active == True)  # noqa: E712
    if search:
        term = f"%{search.lower()}%"
        q = q.where(
            Course.code.ilike(term) | Course.name.ilike(term)
        )

    result = await db.execute(q)
    counts: dict[str, int] = {}
    for session_type, structure in result.all():
        key = _effective_session_type(session_type, structure)
        counts[key] = counts.get(key, 0) + 1
    return counts


async def list_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    department_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[Course]:
    q = select(Course).where(Course.institution_id == institution_id)
    if department_id is not None:
        q = q.where(Course.department_id == department_id)
    if active_only:
        q = q.where(Course.is_active == True)  # noqa: E712
    if search:
        term = f"%{search.lower()}%"
        q = q.where(
            Course.code.ilike(term) | Course.name.ilike(term)
        )
    q = q.order_by(Course.code).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    department_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    active_only: bool = True,
) -> int:
    q = select(func.count()).select_from(Course).where(Course.institution_id == institution_id)
    if department_id is not None:
        q = q.where(Course.department_id == department_id)
    if active_only:
        q = q.where(Course.is_active == True)  # noqa: E712
    if search:
        term = f"%{search.lower()}%"
        q = q.where(
            Course.code.ilike(term) | Course.name.ilike(term)
        )
    result = await db.execute(q)
    return result.scalar_one()


async def _get_department_name_map(
    db: AsyncSession,
    department_ids: set[uuid.UUID],
) -> dict[uuid.UUID, str]:
    if not department_ids:
        return {}

    result = await db.execute(
        select(Department.id, Department.name).where(Department.id.in_(department_ids))
    )
    return {department_id: name for department_id, name in result.all()}


async def to_response(
    db: AsyncSession,
    course: Course,
) -> CourseResponse:
    department_name: str | None = None
    if course.department_id is not None:
      department_name = (
          await db.scalar(
              select(Department.name).where(Department.id == course.department_id)
          )
      )

    return CourseResponse(
        id=course.id,
        institution_id=course.institution_id,
        department_id=course.department_id,
        department_name=department_name,
        code=course.code,
        name=course.name,
        weekly_hours=course.weekly_hours,
        session_type=course.session_type,
        credits=course.credits,
        structure=course.structure,
        room_tags=course.room_tags or [],
        room_tags_soft=course.room_tags_soft,
        preferred_room_ids=course.preferred_room_ids,
        preferred_room_ids_soft=course.preferred_room_ids_soft,
        lab_preferred_room_ids=course.lab_preferred_room_ids,
        lab_preferred_room_ids_soft=course.lab_preferred_room_ids_soft,
        lab_room_tags=course.lab_room_tags,
        lab_room_tags_soft=course.lab_room_tags_soft,
        elective_type=course.elective_type,
        elective_semester=course.elective_semester,
        is_active=course.is_active,
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


async def to_response_list(
    db: AsyncSession,
    course_items: list[Course],
) -> list[CourseResponse]:
    department_name_map = await _get_department_name_map(
        db,
        {
            course.department_id
            for course in course_items
            if course.department_id is not None
        },
    )

    return [
        CourseResponse(
            id=course.id,
            institution_id=course.institution_id,
            department_id=course.department_id,
            department_name=(
                department_name_map.get(course.department_id)
                if course.department_id is not None
                else None
            ),
            code=course.code,
            name=course.name,
            weekly_hours=course.weekly_hours,
            session_type=course.session_type,
            credits=course.credits,
            structure=course.structure,
            room_tags=course.room_tags or [],
            room_tags_soft=course.room_tags_soft,
            preferred_room_ids=course.preferred_room_ids,
            preferred_room_ids_soft=course.preferred_room_ids_soft,
            lab_preferred_room_ids=course.lab_preferred_room_ids,
            lab_preferred_room_ids_soft=course.lab_preferred_room_ids_soft,
            lab_room_tags=course.lab_room_tags,
            lab_room_tags_soft=course.lab_room_tags_soft,
            elective_type=course.elective_type,
            elective_semester=course.elective_semester,
            is_active=course.is_active,
            created_at=course.created_at,
            updated_at=course.updated_at,
        )
        for course in course_items
    ]


async def get_by_id(db: AsyncSession, course_id: uuid.UUID) -> Optional[Course]:
    result = await db.execute(select(Course).where(Course.id == course_id))
    return result.scalars().first()


async def get_or_404(db: AsyncSession, course_id: uuid.UUID) -> Course:
    course = await get_by_id(db, course_id)
    if course is None:
        raise NotFoundError(f"Course {course_id} not found")
    return course


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    institution_id: uuid.UUID,
    payload: CourseCreate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Course:
    # Enforce unique code per institution
    existing = await db.execute(
        select(Course).where(
            Course.institution_id == institution_id,
            Course.code == payload.code,
        )
    )
    if existing.scalars().first() is not None:
        raise ConflictError(f"Course code '{payload.code}' already exists in this institution")

    course = Course(
        institution_id=institution_id,
        **payload.model_dump(exclude={"institution_id"}),
    )
    db.add(course)
    await db.flush()
    logger.info("Course created", course_id=str(course.id), code=course.code)

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.CREATED,
        entity_type="Course",
        entity_id=course.id,
        entity_label=course.code,
        institution_id=institution_id,
    )
    return course


async def update(
    db: AsyncSession,
    course_id: uuid.UUID,
    payload: CourseUpdate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Course:
    course = await get_or_404(db, course_id)
    before = {k: getattr(course, k) for k in payload.model_dump(exclude_unset=True)}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    await db.flush()
    logger.info("Course updated", course_id=str(course_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    after = {k: getattr(course, k) for k in before}
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="Course",
        entity_id=course_id,
        entity_label=course.code,
        institution_id=course.institution_id,
        before=before,
        after=after,
    )
    return course


async def hard_delete(
    db: AsyncSession,
    course_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Permanently delete a course and all linked records via DB cascade."""
    course = await get_or_404(db, course_id)
    institution_id = course.institution_id
    code = course.code
    await db.delete(course)
    await db.flush()
    logger.info("Course hard-deleted", course_id=str(course_id), code=code)

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="Course",
        entity_id=course_id,
        entity_label=code,
        institution_id=institution_id,
    )


async def soft_delete(
    db: AsyncSession,
    course_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Course:
    """Set is_active=False.  Does not cascade to existing schedule sessions."""
    course = await get_or_404(db, course_id)
    course.is_active = False
    await db.flush()
    logger.info("Course deactivated", course_id=str(course_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="Course",
        entity_id=course_id,
        entity_label=course.code,
        institution_id=course.institution_id,
    )
    return course
