"""
app/services/teaching_assignment_service.py
============================================
CRUD for TeachingAssignment + workload preview.

TeachingAssignment: HOD persists "teacher takes course this term" BEFORE
creating a COHORT. Survives page refresh. COHORT creation reads these rows.

Two TA states:
  faculty_id=None  → pending request (service dept not yet assigned a teacher)
  faculty_id=UUID  → fulfilled (teacher assigned, feeds into solver)

Public functions:
  list_teaching_assignments()   — list rows with filters (incl. requested_dept_id)
  get_teaching_assignment_or_404()
  create_teaching_assignment()  — idempotent on unique constraint
  update_teaching_assignment()
  delete_teaching_assignment()
  get_workload_preview()        — per-course teacher coverage vs requirement
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logger import logger
from app.models.curriculum import TeachingAssignment
from app.models.audit_log import AuditAction

if TYPE_CHECKING:
    from app.models.user import User
from app.schemas.curriculum import (
    DeptPlanningStats,
    InstitutionPlanningStats,
    SemesterSessionCount,
    TeachingAssignmentCreate,
    TeachingAssignmentResponse,
    TeachingAssignmentUpdate,
    WorkloadPreview,
    WorkloadPreviewCourse,
    WorkloadPreviewTeacher,
)


async def _get_dept_hod_user(db: AsyncSession, dept_id: uuid.UUID) -> User | None:
    """Return the User who is HOD of `dept_id`, or None if no HOD is assigned."""
    from app.models.user import User
    from app.models.faculty import Faculty
    from app.models.institution import Department
    result = await db.execute(
        select(User)
        .join(Faculty, Faculty.user_id == User.id)
        .join(Department, Department.hod_faculty_id == Faculty.id)
        .where(Department.id == dept_id)
    )
    return result.scalar_one_or_none()


async def list_teaching_assignments(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    *,
    department_id: Optional[uuid.UUID] = None,
    requested_dept_id: Optional[uuid.UUID] = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[TeachingAssignment]:
    q = select(TeachingAssignment).where(
        TeachingAssignment.institution_id == institution_id,
        TeachingAssignment.academic_term_id == academic_term_id,
    )
    if department_id is not None:
        q = q.where(TeachingAssignment.department_id == department_id)
    if requested_dept_id is not None:
        q = q.where(TeachingAssignment.requested_dept_id == requested_dept_id)
    if active_only:
        q = q.where(TeachingAssignment.is_active == True)  # noqa: E712
    q = q.order_by(TeachingAssignment.created_at).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def enrich_assignments(
    db: AsyncSession,
    assignments: list[TeachingAssignment],
) -> list[TeachingAssignmentResponse]:
    """
    Batch-fetch faculty names/emails, course codes/names, and department names,
    then return enriched TeachingAssignmentResponse objects.
    """
    if not assignments:
        return []

    from app.models.faculty import Faculty
    from app.models.course import Course
    from app.models.institution import Department

    faculty_ids = list({a.faculty_id for a in assignments if a.faculty_id is not None})
    course_ids  = list({a.course_id  for a in assignments})
    acad_dept_ids = list({a.department_id for a in assignments if a.department_id is not None})
    svc_dept_ids  = list({a.requested_dept_id for a in assignments if a.requested_dept_id is not None})

    from app.models.user import User

    faculty_map: dict[str, str] = {}        # id → name
    faculty_dept_map: dict[str, str] = {}   # id → department_id
    if faculty_ids:
        rows = await db.execute(
            select(Faculty.id, Faculty.name, User.department_id)
            .outerjoin(User, Faculty.user_id == User.id)
            .where(Faculty.id.in_(faculty_ids))
        )
        for row in rows.all():
            faculty_map[str(row.id)] = row.name or ""
            if row.department_id:
                faculty_dept_map[str(row.id)] = str(row.department_id)

    course_map: dict[str, tuple[str, str, str, str, str, int | None]] = {}
    # id → (code, name, session_type, dept_id, elective_type, elective_semester)
    if course_ids:
        rows = await db.execute(
            select(
                Course.id, Course.code, Course.name, Course.session_type,
                Course.department_id, Course.elective_type, Course.elective_semester,
            ).where(Course.id.in_(course_ids))
        )
        for row in rows.all():
            stype = row.session_type.value if hasattr(row.session_type, "value") else str(row.session_type or "")
            etype = row.elective_type.value if row.elective_type else ""
            course_map[str(row.id)] = (
                row.code or "", row.name or "", stype,
                str(row.department_id) if row.department_id else "",
                etype, row.elective_semester,
            )

    pool_ids = list({a.elective_pool_id for a in assignments if a.elective_pool_id is not None})
    pool_map: dict[str, str] = {}  # pool_id → label
    if pool_ids:
        from app.models.elective_pool import ElectivePool
        pool_rows = await db.execute(
            select(ElectivePool.id, ElectivePool.label).where(ElectivePool.id.in_(pool_ids))
        )
        for row in pool_rows.all():
            pool_map[str(row.id)] = row.label

    all_dept_ids = list({*acad_dept_ids, *svc_dept_ids})
    dept_map: dict[str, str] = {}  # dept_id → dept name
    if all_dept_ids:
        rows = await db.execute(
            select(Department.id, Department.name).where(Department.id.in_(all_dept_ids))
        )
        for row in rows.all():
            dept_map[str(row.id)] = row.name or ""

    enriched: list[TeachingAssignmentResponse] = []
    for a in assignments:
        base = TeachingAssignmentResponse.model_validate(a)
        if a.faculty_id is not None:
            fac_name = faculty_map.get(str(a.faculty_id), "")
            base.faculty_name  = fac_name or None
            fac_dept = faculty_dept_map.get(str(a.faculty_id))
            if fac_dept:
                base.faculty_department_id = uuid.UUID(fac_dept)
                base.faculty_department_name = dept_map.get(fac_dept)
            else:
                base.faculty_department_id = None
                base.faculty_department_name = None
        course_row = course_map.get(str(a.course_id), ("", "", "", "", "", None))
        code, cname, stype, cdept, etype, esem = course_row
        base.course_code              = code or None
        base.course_name              = cname or None
        base.course_session_type      = stype or None
        base.course_elective_type     = etype or None
        base.course_elective_semester = esem
        if cdept:
            base.course_department_id = uuid.UUID(cdept)
        if a.department_id is not None:
            base.department_name = dept_map.get(str(a.department_id))
        if a.requested_dept_id is not None:
            base.requested_dept_name = dept_map.get(str(a.requested_dept_id))
        # Enrich pool label if assigned
        if a.elective_pool_id is not None:
            base.elective_pool_id = a.elective_pool_id
            base.elective_pool_label = pool_map.get(str(a.elective_pool_id))
        enriched.append(base)

    return enriched


async def get_teaching_assignment_or_404(
    db: AsyncSession, assignment_id: uuid.UUID
) -> TeachingAssignment:
    result = await db.execute(
        select(TeachingAssignment).where(TeachingAssignment.id == assignment_id)
    )
    obj = result.scalars().first()
    if obj is None:
        raise NotFoundError(f"TeachingAssignment {assignment_id} not found")
    return obj


async def _mark_scenario_dirty(db: AsyncSession, scenario_id: uuid.UUID) -> None:
    """Best-effort: mark scenario is_dirty=True after a teaching assignment mutation."""
    from sqlalchemy import update
    from app.models.scenario import Scenario
    await db.execute(
        update(Scenario)
        .where(Scenario.id == scenario_id)
        .values(is_dirty=True)
    )


async def _resolve_faculty_dept(db: AsyncSession, faculty_id: uuid.UUID) -> uuid.UUID | None:
    """Return the department_id of the User linked to this faculty profile."""
    from sqlalchemy.orm import selectinload
    from app.models.faculty import Faculty
    fac = await db.scalar(
        select(Faculty)
        .where(Faculty.id == faculty_id)
        .options(selectinload(Faculty.user_rel))
    )
    if fac and fac.user_rel:
        return fac.user_rel.department_id
    return None


async def _check_plan_lock(
    db: AsyncSession,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    actor_role: str | None,
) -> None:
    """Raise ConflictError if the department plan is locked for the given role."""
    from app.core.exceptions import ConflictError
    from app.models.department_plan import DepartmentPlan, PlanStatus

    plan = await db.scalar(
        select(DepartmentPlan).where(
            DepartmentPlan.academic_term_id == academic_term_id,
            DepartmentPlan.department_id == department_id,
        )
    )
    if plan is None:
        return

    role = (actor_role or "").lower()
    if plan.status == PlanStatus.ADMIN_APPROVED:
        raise ConflictError(
            "This plan is approved and locked. Admin must unpublish before edits."
        )
    if plan.status == PlanStatus.HOD_PUBLISHED and role not in ("admin", "super_admin"):
        raise ConflictError(
            "Plan has been submitted for review. Only an admin can edit at this stage."
        )


async def create_teaching_assignment(
    db: AsyncSession,
    payload: TeachingAssignmentCreate,
    *,
    scenario_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> TeachingAssignment:
    """
    Create a pending or fulfilled teaching assignment.

    Idempotent for fulfilled TAs (same term+dept+faculty+course): updates section_count.
    Pending TAs (faculty_id=None) always create a new row (PostgreSQL NULL ≠ NULL in UQ).
    Fires audit log + notifications after flush.
    """
    import app.services.audit_log_service as audit_svc
    import app.services.notification_service as notif_svc
    from app.models.notification import NotificationType

    # Idempotency check only applies to fulfilled (faculty_id set) TAs
    existing = None
    if payload.faculty_id is not None:
        stmt = select(TeachingAssignment).where(
            TeachingAssignment.academic_term_id == payload.academic_term_id,
            TeachingAssignment.department_id == payload.department_id,
            TeachingAssignment.faculty_id == payload.faculty_id,
            TeachingAssignment.course_id == payload.course_id,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

    if existing is not None:
        if existing.section_count != payload.section_count:
            existing.section_count = payload.section_count
        if payload.pinned_section_label is not None:
            existing.pinned_section_label = payload.pinned_section_label
        if payload.notes is not None:
            existing.notes = payload.notes
        existing.is_active = payload.is_active
        await db.flush()
        if scenario_id is not None:
            await _mark_scenario_dirty(db, scenario_id)
        return existing

    # Plan-status guard — block edits on locked plans
    await _check_plan_lock(
        db,
        academic_term_id=payload.academic_term_id,
        department_id=payload.department_id,
        actor_role=actor_role,
    )

    # Auto-infer requested_dept_id when faculty is from a different department
    if payload.faculty_id is not None and not payload.requested_dept_id:
        fac_dept = await _resolve_faculty_dept(db, payload.faculty_id)
        if fac_dept and fac_dept != payload.department_id:
            payload = payload.model_copy(update={"requested_dept_id": fac_dept})

    assignment = TeachingAssignment(**payload.model_dump())
    db.add(assignment)
    await db.flush()

    if scenario_id is not None:
        await _mark_scenario_dirty(db, scenario_id)

    logger.info(
        "TeachingAssignment created",
        assignment_id=str(assignment.id),
        faculty_id=str(assignment.faculty_id) if assignment.faculty_id else None,
        course_id=str(assignment.course_id),
    )

    # Audit log
    await audit_svc.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.CREATED,
        entity_type="TeachingAssignment",
        entity_id=assignment.id,
        entity_label=f"{assignment.course_id} → {assignment.department_id}",
        institution_id=assignment.institution_id,
        after={
            "faculty_id": str(assignment.faculty_id) if assignment.faculty_id else None,
            "requested_dept_id": str(assignment.requested_dept_id) if assignment.requested_dept_id else None,
            "section_count": assignment.section_count,
        },
    )

    # Notify service dept HOD when a pending request is created
    if assignment.faculty_id is None and assignment.requested_dept_id is not None:
        try:
            service_hod = await _get_dept_hod_user(db, assignment.requested_dept_id)
            if service_hod:
                await notif_svc.send(
                    db,
                    institution_id=assignment.institution_id,
                    notification_type=NotificationType.TEACHER_REQUEST_RECEIVED,
                    recipients=[service_hod],
                    title="New Teacher Request",
                    body="A department has requested a teacher for a course this term.",
                    metadata={"ta_id": str(assignment.id), "deep_link": "/planning"},
                )
        except Exception:
            logger.warning("Failed to notify service HOD of new teacher request", exc_info=True)

    return assignment


async def update_teaching_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    payload: TeachingAssignmentUpdate,
    *,
    scenario_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> TeachingAssignment:
    import app.services.audit_log_service as audit_svc
    import app.services.notification_service as notif_svc
    from app.models.notification import NotificationType

    assignment = await get_teaching_assignment_or_404(db, assignment_id)

    # Plan-status guard — block edits on locked plans
    await _check_plan_lock(
        db,
        academic_term_id=assignment.academic_term_id,
        department_id=assignment.department_id,
        actor_role=actor_role,
    )

    # Capture before state for audit + fulfillment detection
    before_snapshot = {
        "faculty_id": str(assignment.faculty_id) if assignment.faculty_id else None,
        "requested_dept_id": str(assignment.requested_dept_id) if assignment.requested_dept_id else None,
        "section_count": assignment.section_count,
    }
    was_pending = assignment.faculty_id is None

    # Capture values needed for conflict lookup before we mutate the ORM object
    _assigning_faculty_id = payload.faculty_id
    _ta_term_id = assignment.academic_term_id
    _ta_dept_id = assignment.department_id
    _ta_course_id = assignment.course_id

    # Auto-infer requested_dept_id when faculty is changing to cross-dept (or back)
    if (
        payload.faculty_id is not None
        and payload.faculty_id != assignment.faculty_id
        and "requested_dept_id" not in payload.model_fields_set
    ):
        fac_dept = await _resolve_faculty_dept(db, payload.faculty_id)
        if fac_dept is not None:
            if fac_dept != assignment.department_id:
                assignment.requested_dept_id = fac_dept
            else:
                assignment.requested_dept_id = None

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(assignment, field, value)

    if assignment.section_count <= 1:
        assignment.is_merged_session = False

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        conflict_row = None
        if _assigning_faculty_id is not None:
            conflict_row = await db.scalar(
                select(TeachingAssignment).where(
                    TeachingAssignment.academic_term_id == _ta_term_id,
                    TeachingAssignment.department_id == _ta_dept_id,
                    TeachingAssignment.faculty_id == _assigning_faculty_id,
                    TeachingAssignment.course_id == _ta_course_id,
                )
            )
        raise HTTPException(status_code=409, detail={
            "message": "Faculty already assigned to this course for this term.",
            "existing_ta_id": str(conflict_row.id) if conflict_row else None,
            "existing_section_count": conflict_row.section_count if conflict_row else None,
        })

    if scenario_id is not None:
        await _mark_scenario_dirty(db, scenario_id)

    logger.info("TeachingAssignment updated", assignment_id=str(assignment_id))

    after_snapshot = {
        "faculty_id": str(assignment.faculty_id) if assignment.faculty_id else None,
        "requested_dept_id": str(assignment.requested_dept_id) if assignment.requested_dept_id else None,
        "section_count": assignment.section_count,
    }

    await audit_svc.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="TeachingAssignment",
        entity_id=assignment_id,
        entity_label=f"{assignment.course_id} → {assignment.department_id}",
        institution_id=assignment.institution_id,
        before=before_snapshot,
        after=after_snapshot,
    )

    # Notify academic dept HOD when a pending request is fulfilled
    now_fulfilled = assignment.faculty_id is not None
    if was_pending and now_fulfilled and assignment.department_id is not None:
        try:
            academic_hod = await _get_dept_hod_user(db, assignment.department_id)
            if academic_hod:
                await notif_svc.send(
                    db,
                    institution_id=assignment.institution_id,
                    notification_type=NotificationType.TEACHER_REQUEST_FULFILLED,
                    recipients=[academic_hod],
                    title="Teacher Assigned",
                    body="Your teacher request has been fulfilled.",
                    metadata={"ta_id": str(assignment_id), "deep_link": "/planning"},
                )
        except Exception:
            logger.warning("Failed to notify academic HOD of fulfilled request", exc_info=True)

    return assignment


async def delete_teaching_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    *,
    scenario_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> None:
    import app.services.audit_log_service as audit_svc

    assignment = await get_teaching_assignment_or_404(db, assignment_id)

    # Plan-status guard — block deletes on locked plans
    await _check_plan_lock(
        db,
        academic_term_id=assignment.academic_term_id,
        department_id=assignment.department_id,
        actor_role=actor_role,
    )

    entity_label = f"{assignment.course_id} → {assignment.department_id}"
    institution_id = assignment.institution_id

    await db.delete(assignment)
    await db.flush()

    if scenario_id is not None:
        await _mark_scenario_dirty(db, scenario_id)

    logger.info("TeachingAssignment deleted", assignment_id=str(assignment_id))

    await audit_svc.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="TeachingAssignment",
        entity_id=assignment_id,
        entity_label=entity_label,
        institution_id=institution_id,
    )


async def get_workload_preview(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: Optional[uuid.UUID] = None,
    class_count: Optional[int] = None,
    include_service_load: bool = True,
) -> WorkloadPreview:
    """
    Return per-course teacher coverage vs. required slots.

    Loads TeachingAssignment rows + Course names + Faculty names (by UUID lookup
    from catalogue tables where available; falls back to raw UUID strings).

    include_service_load: when True, also includes fulfilled cross-dept TAs where
    this dept is the service provider (requested_dept_id = department_id).
    """
    from app.models.course import Course
    from app.models.faculty import Faculty

    assignments = await list_teaching_assignments(
        db, institution_id, academic_term_id,
        department_id=department_id, active_only=True, skip=0, limit=10000,
    )

    if include_service_load and department_id is not None:
        cross_dept = await list_teaching_assignments(
            db, institution_id, academic_term_id,
            requested_dept_id=department_id, active_only=True, skip=0, limit=10000,
        )
        fulfilled_cross = [ta for ta in cross_dept if ta.faculty_id is not None]
        seen = {a.id for a in assignments}
        assignments = assignments + [ta for ta in fulfilled_cross if ta.id not in seen]

    # Resolve class_count if not provided — try COHORT target for this dept/term
    import math
    resolved_class_count: Optional[int] = class_count
    cohort = None
    if resolved_class_count is None and department_id is not None:
        from app.models.curriculum import SchedulingTarget, TargetType
        cohort_result = await db.execute(
            select(SchedulingTarget).where(
                SchedulingTarget.institution_id == institution_id,
                SchedulingTarget.academic_term_id == academic_term_id,
                SchedulingTarget.department_id == department_id,
                SchedulingTarget.target_type == TargetType.COHORT,
                SchedulingTarget.is_active == True,  # noqa: E712
            ).order_by(SchedulingTarget.created_at.desc()).limit(1)
        )
        cohort = cohort_result.scalar_one_or_none()
        if cohort is not None:
            resolved_class_count = cohort.class_count

    # Resolve student context for recommendation banner
    students_total: Optional[int] = cohort.size if cohort is not None else None
    effective_class_size: Optional[int] = None
    if department_id is not None:
        from app.models.institution import Department
        dept = await db.get(Department, department_id)
        if dept and dept.class_size is not None:
            effective_class_size = dept.class_size
    if effective_class_size is None:
        from app.models.institution import Institution
        institution_obj = await db.get(Institution, institution_id)
        if institution_obj and institution_obj.default_class_size is not None:
            effective_class_size = institution_obj.default_class_size
    recommended_sections: Optional[int] = (
        math.ceil(students_total / effective_class_size)
        if students_total and effective_class_size else None
    )
    students_per_section: Optional[int] = (
        round(students_total / resolved_class_count)
        if students_total and resolved_class_count else None
    )

    # Collect all course / faculty IDs referenced
    course_ids = list({a.course_id for a in assignments})
    faculty_ids = list({a.faculty_id for a in assignments if a.faculty_id is not None})

    course_map: dict[str, str] = {}
    faculty_map: dict[str, str] = {}

    if course_ids:
        courses_result = await db.execute(
            select(Course).where(Course.id.in_(course_ids))
        )
        for c in courses_result.scalars().all():
            course_map[str(c.id)] = getattr(c, "name", str(c.id))

    if faculty_ids:
        faculty_result = await db.execute(
            select(Faculty).where(Faculty.id.in_(faculty_ids))
        )
        for f in faculty_result.scalars().all():
            faculty_map[str(f.id)] = getattr(f, "name", str(f.id))

    # Resolve department names for cross-dept TAs — show the "other" dept name
    cross_dept_ids: set[uuid.UUID] = set()
    for a in assignments:
        if a.requested_dept_id is not None:
            if a.department_id is not None:
                cross_dept_ids.add(a.department_id)
            if a.requested_dept_id is not None:
                cross_dept_ids.add(a.requested_dept_id)
    dept_name_map: dict[str, str] = {}
    if cross_dept_ids:
        from app.models.institution import Department
        dept_rows = await db.execute(
            select(Department).where(Department.id.in_(list(cross_dept_ids)))
        )
        for d in dept_rows.scalars().all():
            dept_name_map[str(d.id)] = getattr(d, "name", str(d.id))

    def _other_dept_name(r: TeachingAssignment) -> str | None:
        if r.requested_dept_id is None:
            return None
        viewer_id = str(department_id) if department_id else None
        owning_id = str(r.department_id) if r.department_id else None
        service_id = str(r.requested_dept_id) if r.requested_dept_id else None
        other_id = owning_id if service_id == viewer_id else service_id
        return dept_name_map.get(other_id) if other_id else None

    def _our_faculty_servicing(r: TeachingAssignment) -> bool:
        """True if our department's faculty is teaching for another dept."""
        if r.requested_dept_id is None:
            return False
        viewer_id = str(department_id) if department_id else None
        service_id = str(r.requested_dept_id) if r.requested_dept_id else None
        return service_id == viewer_id

    # Group by course, and track which (study_year, study_semester) each course belongs to
    by_course: dict[str, list[TeachingAssignment]] = {}
    course_sem: dict[str, tuple[int | None, int | None]] = {}
    for a in assignments:
        cid = str(a.course_id)
        by_course.setdefault(cid, []).append(a)
        # First non-null semester wins (all TAs for the same course share the same semester)
        if cid not in course_sem or course_sem[cid] == (None, None):
            course_sem[cid] = (a.study_year, a.study_semester)

    # Fetch student counts per distinct semester so required_slots reflects the
    # actual cohort for THAT semester, not the whole-department headcount.
    sem_student_count: dict[int, int] = {}  # study_semester → student count
    if effective_class_size and department_id is not None:
        unique_sems = {sem for (_, sem) in course_sem.values() if sem is not None}
        if unique_sems:
            from app.services.student_service import count_students as _count_students
            for sem in unique_sems:
                cnt = await _count_students(db, institution_id, department_id=department_id, semester=sem)
                if cnt > 0:
                    sem_student_count[sem] = cnt

    courses_out: list[WorkloadPreviewCourse] = []
    warnings: list[str] = []

    for course_id_str, rows in by_course.items():
        course_name = course_map.get(course_id_str, course_id_str)
        study_year, study_semester = course_sem.get(course_id_str, (None, None))

        # Per-course required slots: use semester-specific student count when available,
        # otherwise fall back to the whole-dept class_count.
        course_required: int
        course_students_per_section: int | None = None
        if (
            study_semester is not None
            and study_semester in sem_student_count
            and effective_class_size
        ):
            sem_count = sem_student_count[study_semester]
            course_required = math.ceil(sem_count / effective_class_size)
            course_students_per_section = round(sem_count / course_required) if course_required else None
        else:
            course_required = resolved_class_count or 1
            course_students_per_section = students_per_section

        teachers = [
            WorkloadPreviewTeacher(
                faculty_id=r.faculty_id,
                faculty_name=faculty_map.get(str(r.faculty_id), str(r.faculty_id)) if r.faculty_id else None,
                section_count=r.section_count,
                pinned_section_label=r.pinned_section_label,
                owning_dept_name=(n := _other_dept_name(r)),
                cross_dept_label=(
                    f"Teaching for {n}" if _our_faculty_servicing(r)
                    else f"Faculty from {n}"
                ) if n else None,
            )
            for r in rows
            if r.faculty_id is not None  # only fulfilled TAs count as coverage
        ]
        total_covered = sum(r.section_count for r in rows if r.faculty_id is not None)
        is_sufficient = total_covered >= course_required
        if not is_sufficient:
            warnings.append(
                f"{course_name}: {total_covered} section(s) covered, need {course_required}"
            )
        courses_out.append(WorkloadPreviewCourse(
            course_id=uuid.UUID(course_id_str),
            course_name=course_name,
            teachers=teachers,
            total_sections_covered=total_covered,
            required_slots=course_required,
            is_sufficient=is_sufficient,
            study_year=study_year,
            study_semester=study_semester,
            students_per_section=course_students_per_section,
        ))

    return WorkloadPreview(
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        class_count=resolved_class_count,
        courses=courses_out,
        warnings=warnings,
        students_total=students_total,
        effective_class_size=effective_class_size,
        recommended_sections=recommended_sections,
        students_per_section=students_per_section,
    )


async def get_institution_planning_stats(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
) -> InstitutionPlanningStats:
    """
    Return per-dept planning aggregates for the admin dashboard.
    Two SQL queries, all aggregation done in Python.
    """
    from collections import defaultdict
    from app.models.course import Course
    from sqlalchemy import func

    # Q1: all active TAs for this term
    tas_result = await db.execute(
        select(TeachingAssignment).where(
            TeachingAssignment.institution_id == institution_id,
            TeachingAssignment.academic_term_id == academic_term_id,
            TeachingAssignment.is_active.is_(True),
        )
    )
    tas = tas_result.scalars().all()

    # Q2: active course count per dept
    course_counts_result = await db.execute(
        select(Course.department_id, func.count().label("cnt"))
        .where(
            Course.institution_id == institution_id,
            Course.is_active.is_(True),
        )
        .group_by(Course.department_id)
    )
    course_counts: dict[uuid.UUID, int] = {
        row.department_id: row.cnt for row in course_counts_result
    }

    # Aggregate per dept in a single pass
    dept_sessions: dict[uuid.UUID, int] = defaultdict(int)
    dept_pending: dict[uuid.UUID, int] = defaultdict(int)
    dept_course_ids: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    dept_faculty_load: dict[uuid.UUID, dict[uuid.UUID, int]] = defaultdict(lambda: defaultdict(int))
    dept_sem_map: dict[uuid.UUID, dict[tuple[int, int], int]] = defaultdict(lambda: defaultdict(int))
    dept_merged: dict[uuid.UUID, int] = defaultdict(int)

    for ta in tas:
        dept_id = ta.department_id
        if dept_id is None:
            continue
        if ta.faculty_id is not None:
            dept_sessions[dept_id] += ta.section_count
            dept_course_ids[dept_id].add(ta.course_id)
            dept_faculty_load[dept_id][ta.faculty_id] += ta.section_count
            if ta.study_year is not None and ta.study_semester is not None:
                dept_sem_map[dept_id][(ta.study_year, ta.study_semester)] += ta.section_count
        else:
            dept_pending[dept_id] += 1
        if ta.is_merged_session:
            dept_merged[dept_id] += 1

    all_dept_ids = set(dept_sessions) | set(dept_pending) | set(course_counts)

    dept_stats: list[DeptPlanningStats] = []
    total_sessions = 0
    total_pending = 0

    for dept_id in all_dept_ids:
        sessions = dept_sessions.get(dept_id, 0)
        pending = dept_pending.get(dept_id, 0)
        total_sessions += sessions
        total_pending += pending

        faculty_load = dept_faculty_load.get(dept_id, {})
        loads = list(faculty_load.values())
        max_load = max(loads, default=0)
        avg_load = sum(loads) / len(loads) if loads else 0.0
        is_imbalanced = avg_load > 0 and (max_load / avg_load) > 2.5

        sem_breakdown: list[SemesterSessionCount] = [
            SemesterSessionCount(
                study_year=yr,
                study_semester=sem,
                label=f"Y{yr}·S{sem}",
                sessions_assigned=count,
            )
            for (yr, sem), count in sorted(dept_sem_map.get(dept_id, {}).items())
        ]

        dept_stats.append(DeptPlanningStats(
            department_id=dept_id,
            sessions_assigned=sessions,
            courses_with_sessions=len(dept_course_ids.get(dept_id, set())),
            total_courses=course_counts.get(dept_id, 0),
            pending_count=pending,
            sem_breakdown=sem_breakdown,
            max_faculty_load=max_load,
            avg_faculty_load=round(avg_load, 2),
            is_load_imbalanced=is_imbalanced,
            unassigned_faculty_count=0,
            merged_session_count=dept_merged.get(dept_id, 0),
        ))

    return InstitutionPlanningStats(
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        total_sessions_assigned=total_sessions,
        total_pending=total_pending,
        dept_stats=dept_stats,
    )
