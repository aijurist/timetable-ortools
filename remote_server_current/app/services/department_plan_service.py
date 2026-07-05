"""
app/services/department_plan_service.py
========================================
HOD → Admin plan submission workflow.

Status transitions:
  DRAFT → HOD_PUBLISHED  (submit_plan — HOD action)
  HOD_PUBLISHED → DRAFT  (hod_recall_plan — HOD action)
  HOD_PUBLISHED → ADMIN_APPROVED  (approve_plan — Admin action)
  HOD_PUBLISHED → DRAFT            (send_back_plan — Admin action)
  ADMIN_APPROVED → HOD_PUBLISHED   (admin_unpublish_plan — Admin action)
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logger import logger
from app.models.audit_log import AuditAction
from app.models.curriculum import TeachingAssignment
from app.models.department_plan import DepartmentPlan, PlanStatus
from app.models.institution import Department


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _assert_dept_in_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    department_id: uuid.UUID,
) -> Department:
    """Raise 403 if department_id does not belong to institution_id."""
    dept = await db.get(Department, department_id)
    if dept is None or dept.institution_id != institution_id:
        raise HTTPException(status_code=403, detail="Department not in your institution.")
    return dept


async def _get_plan(
    db: AsyncSession,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
) -> DepartmentPlan | None:
    return await db.scalar(
        select(DepartmentPlan).where(
            DepartmentPlan.academic_term_id == academic_term_id,
            DepartmentPlan.department_id == department_id,
        )
    )


async def _get_admin_users(db: AsyncSession, institution_id: uuid.UUID) -> list:
    from app.models.user import User, UserRole
    result = await db.execute(
        select(User).where(
            User.institution_id == institution_id,
            User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]),
            User.is_active.is_(True),
        )
    )
    return list(result.scalars().all())


async def _get_dept_hod_and_faculty(db: AsyncSession, institution_id: uuid.UUID, dept_id: uuid.UUID) -> list:
    """Return HOD + active faculty users for a department."""
    from app.models.user import User, UserRole
    from app.models.faculty import Faculty

    hod_result = await db.execute(
        select(User)
        .join(Faculty, Faculty.user_id == User.id)
        .join(Department, Department.hod_faculty_id == Faculty.id)
        .where(Department.id == dept_id)
    )
    hod = hod_result.scalar_one_or_none()

    faculty_result = await db.execute(
        select(User)
        .join(Faculty, Faculty.user_id == User.id)
        .where(
            Faculty.institution_id == institution_id,
            Faculty.department_id == dept_id,
            User.is_active.is_(True),
        )
    )
    faculty_users = list(faculty_result.scalars().all())

    recipients: list = faculty_users[:]
    if hod and hod not in faculty_users:
        recipients.insert(0, hod)
    return recipients


async def _ta_summary(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
) -> dict[str, Any]:
    """Return aggregate counts of TAs for a dept+term."""
    tas_result = await db.execute(
        select(TeachingAssignment).where(
            TeachingAssignment.institution_id == institution_id,
            TeachingAssignment.academic_term_id == academic_term_id,
            TeachingAssignment.department_id == department_id,
            TeachingAssignment.is_active.is_(True),
        )
    )
    tas = list(tas_result.scalars().all())

    total = len(tas)
    assigned = sum(1 for t in tas if t.faculty_id is not None)
    pending = total - assigned

    # Cross-dept: own-dept courses where faculty comes from another dept (requested_dept_id set)
    cross_dept_pending = sum(
        1 for t in tas
        if t.faculty_id is None and t.requested_dept_id is not None
    )

    # Own-dept courses without faculty (not a cross-dept request)
    own_pending_courses = [
        t for t in tas
        if t.faculty_id is None and t.requested_dept_id is None
    ]

    return {
        "total": total,
        "assigned": assigned,
        "pending": pending,
        "cross_dept_pending": cross_dept_pending,
        "own_pending": own_pending_courses,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_or_create_plan(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
) -> DepartmentPlan:
    """Idempotent — returns the existing plan or creates a DRAFT."""
    plan = await _get_plan(db, academic_term_id, department_id)
    if plan is not None:
        return plan

    plan = DepartmentPlan(
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        status=PlanStatus.DRAFT,
    )
    db.add(plan)
    await db.flush()
    return plan


async def get_plan_status(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
) -> DepartmentPlan | None:
    await _assert_dept_in_institution(db, institution_id, department_id)
    return await _get_plan(db, academic_term_id, department_id)


async def submit_plan(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_role: str | None = None,
) -> dict[str, Any]:
    """
    HOD submits their department plan.

    Validates that all own-dept courses have faculty assigned.
    Returns a summary dict on success.
    Raises ValidationError (400) with structured detail on validation failure.
    """
    import app.services.audit_log_service as audit_svc
    import app.services.notification_service as notif_svc
    from app.models.notification import NotificationType

    await _assert_dept_in_institution(db, institution_id, department_id)
    summary = await _ta_summary(db, institution_id, academic_term_id, department_id)

    if summary["total"] == 0:
        raise ValidationError("No teaching assignments found for this department and term.")

    if summary["own_pending"]:
        course_ids = [str(t.course_id) for t in summary["own_pending"]]
        # Enrich with course codes
        from app.models.course import Course
        courses_result = await db.execute(
            select(Course.id, Course.code, Course.name).where(
                Course.id.in_([t.course_id for t in summary["own_pending"]])
            )
        )
        course_map = {str(r.id): f"{r.code} — {r.name}" for r in courses_result.all()}
        courses_without_faculty = [
            course_map.get(str(t.course_id), str(t.course_id))
            for t in summary["own_pending"]
        ]
        raise ValidationError(
            f"{len(courses_without_faculty)} course(s) still need a faculty member. "
            "Assign faculty to all courses before submitting.",
            detail={
                "courses_without_faculty": courses_without_faculty,
                "pending_cross_dept": summary["cross_dept_pending"],
            },
        )

    plan = await get_or_create_plan(db, institution_id, academic_term_id, department_id)

    if plan.status == PlanStatus.ADMIN_APPROVED:
        raise ConflictError("Plan is already approved. Admin must unpublish before resubmitting.")

    plan.status = PlanStatus.HOD_PUBLISHED
    plan.submitted_at = datetime.now(tz=timezone.utc)
    plan.submitted_by_user_id = actor_user_id
    plan.sent_back_reason = None
    plan.sent_back_at = None
    await db.flush()

    await audit_svc.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.PUBLISHED,
        entity_type="DepartmentPlan",
        entity_id=plan.id,
        entity_label=f"dept={department_id} term={academic_term_id}",
        institution_id=institution_id,
        after={"status": PlanStatus.HOD_PUBLISHED.value},
    )

    try:
        admins = await _get_admin_users(db, institution_id)
        if admins:
            dept = await db.get(Department, department_id)
            dept_name = dept.name if dept else str(department_id)
            await notif_svc.send(
                db,
                institution_id=institution_id,
                notification_type=NotificationType.PLAN_SUBMITTED,
                recipients=admins,
                title="Department Plan Submitted",
                body=f"{dept_name} has submitted their teaching plan for review.",
                metadata={
                    "plan_id": str(plan.id),
                    "department_id": str(department_id),
                    "deep_link": "/planning",
                },
            )
    except Exception:
        logger.warning("Failed to notify admins of plan submission", exc_info=True)

    return {
        "status": plan.status.value,
        "summary": {
            "total_courses": summary["total"],
            "assigned": summary["assigned"],
            "pending": summary["pending"],
            "cross_dept_pending": summary["cross_dept_pending"],
        },
    }


async def approve_plan(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_role: str | None = None,
) -> DepartmentPlan:
    """Admin approves HOD_PUBLISHED → ADMIN_APPROVED."""
    import app.services.audit_log_service as audit_svc
    import app.services.notification_service as notif_svc
    from app.models.notification import NotificationType

    await _assert_dept_in_institution(db, institution_id, department_id)
    plan = await _get_plan(db, academic_term_id, department_id)
    if plan is None:
        raise NotFoundError("No plan found for this department and term.")
    if plan.status != PlanStatus.HOD_PUBLISHED:
        raise ConflictError(
            f"Plan must be in HOD_PUBLISHED status to approve. Current: {plan.status.value}"
        )

    plan.status = PlanStatus.ADMIN_APPROVED
    plan.approved_at = datetime.now(tz=timezone.utc)
    plan.approved_by_user_id = actor_user_id
    plan.sent_back_reason = None
    plan.sent_back_at = None
    await db.flush()

    await audit_svc.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.PUBLISHED,
        entity_type="DepartmentPlan",
        entity_id=plan.id,
        entity_label=f"dept={department_id} term={academic_term_id}",
        institution_id=institution_id,
        after={"status": PlanStatus.ADMIN_APPROVED.value},
    )

    try:
        recipients = await _get_dept_hod_and_faculty(db, institution_id, department_id)
        if recipients:
            dept = await db.get(Department, department_id)
            dept_name = dept.name if dept else str(department_id)
            await notif_svc.send(
                db,
                institution_id=institution_id,
                notification_type=NotificationType.PLAN_APPROVED,
                recipients=recipients,
                title="Department Plan Approved",
                body=f"The {dept_name} teaching plan has been approved for this term.",
                metadata={
                    "plan_id": str(plan.id),
                    "department_id": str(department_id),
                    "deep_link": "/planning",
                },
            )
    except Exception:
        logger.warning("Failed to notify dept of plan approval", exc_info=True)

    return plan


async def send_back_plan(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str | None = None,
    actor_role: str | None = None,
) -> DepartmentPlan:
    """Admin sends back HOD_PUBLISHED → DRAFT."""
    import app.services.audit_log_service as audit_svc
    import app.services.notification_service as notif_svc
    from app.models.notification import NotificationType

    await _assert_dept_in_institution(db, institution_id, department_id)
    plan = await _get_plan(db, academic_term_id, department_id)
    if plan is None:
        raise NotFoundError("No plan found for this department and term.")
    if plan.status != PlanStatus.HOD_PUBLISHED:
        raise ConflictError(
            f"Plan must be in HOD_PUBLISHED status to send back. Current: {plan.status.value}"
        )

    plan.status = PlanStatus.DRAFT
    plan.sent_back_at = datetime.now(tz=timezone.utc)
    plan.sent_back_reason = reason
    await db.flush()

    await audit_svc.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="DepartmentPlan",
        entity_id=plan.id,
        entity_label=f"dept={department_id} term={academic_term_id}",
        institution_id=institution_id,
        after={"status": PlanStatus.DRAFT.value, "sent_back_reason": reason},
    )

    try:
        from app.models.user import User
        from app.models.faculty import Faculty
        hod_result = await db.execute(
            select(User)
            .join(Faculty, Faculty.user_id == User.id)
            .join(Department, Department.hod_faculty_id == Faculty.id)
            .where(Department.id == department_id)
        )
        hod = hod_result.scalar_one_or_none()
        if hod:
            body = "Your department plan has been sent back for revision."
            if reason:
                body += f" Reason: {reason}"
            await notif_svc.send(
                db,
                institution_id=institution_id,
                notification_type=NotificationType.PLAN_SENT_BACK,
                recipients=[hod],
                title="Plan Sent Back for Revision",
                body=body,
                metadata={
                    "plan_id": str(plan.id),
                    "department_id": str(department_id),
                    "reason": reason,
                    "deep_link": "/planning",
                },
            )
    except Exception:
        logger.warning("Failed to notify HOD of plan send-back", exc_info=True)

    return plan


async def hod_recall_plan(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_role: str | None = None,
) -> DepartmentPlan:
    """HOD recalls their submitted plan back to DRAFT for further editing."""
    import app.services.audit_log_service as audit_svc
    import app.services.notification_service as notif_svc
    from app.models.notification import NotificationType

    await _assert_dept_in_institution(db, institution_id, department_id)
    plan = await _get_plan(db, academic_term_id, department_id)
    if plan is None:
        raise NotFoundError("No plan found for this department and term.")
    if plan.status != PlanStatus.HOD_PUBLISHED:
        raise ConflictError(
            f"Plan can only be recalled when in HOD_PUBLISHED status. Current: {plan.status.value}"
        )

    plan.status = PlanStatus.DRAFT
    plan.submitted_at = None
    plan.submitted_by_user_id = None
    await db.flush()

    await audit_svc.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="DepartmentPlan",
        entity_id=plan.id,
        entity_label=f"dept={department_id} term={academic_term_id}",
        institution_id=institution_id,
        after={"status": PlanStatus.DRAFT.value},
    )

    try:
        admins = await _get_admin_users(db, institution_id)
        if admins:
            dept = await db.get(Department, department_id)
            dept_name = dept.name if dept else str(department_id)
            await notif_svc.send(
                db,
                institution_id=institution_id,
                notification_type=NotificationType.PLAN_SENT_BACK,
                recipients=admins,
                title="Department Plan Recalled",
                body=f"{dept_name} has recalled their teaching plan submission for further edits.",
                metadata={
                    "plan_id": str(plan.id),
                    "department_id": str(department_id),
                    "deep_link": "/planning",
                },
            )
    except Exception:
        logger.warning("Failed to notify admins of plan recall", exc_info=True)

    return plan


async def admin_unpublish_plan(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_role: str | None = None,
) -> DepartmentPlan:
    """Admin reverts ADMIN_APPROVED → HOD_PUBLISHED so corrections can be made."""
    import app.services.audit_log_service as audit_svc
    import app.services.notification_service as notif_svc
    from app.models.notification import NotificationType

    await _assert_dept_in_institution(db, institution_id, department_id)
    plan = await _get_plan(db, academic_term_id, department_id)
    if plan is None:
        raise NotFoundError("No plan found for this department and term.")
    if plan.status != PlanStatus.ADMIN_APPROVED:
        raise ConflictError(
            f"Plan must be ADMIN_APPROVED to unpublish. Current: {plan.status.value}"
        )

    plan.status = PlanStatus.HOD_PUBLISHED
    plan.approved_at = None
    plan.approved_by_user_id = None
    await db.flush()

    await audit_svc.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="DepartmentPlan",
        entity_id=plan.id,
        entity_label=f"dept={department_id} term={academic_term_id}",
        institution_id=institution_id,
        after={"status": PlanStatus.HOD_PUBLISHED.value},
    )

    try:
        from app.models.user import User
        from app.models.faculty import Faculty
        hod_result = await db.execute(
            select(User)
            .join(Faculty, Faculty.user_id == User.id)
            .join(Department, Department.hod_faculty_id == Faculty.id)
            .where(Department.id == department_id)
        )
        hod = hod_result.scalar_one_or_none()
        if hod:
            await notif_svc.send(
                db,
                institution_id=institution_id,
                notification_type=NotificationType.PLAN_SENT_BACK,
                recipients=[hod],
                title="Plan Approval Reverted",
                body="Your department plan approval has been reverted. It is back in submitted state — the admin may follow up with feedback.",
                metadata={
                    "plan_id": str(plan.id),
                    "department_id": str(department_id),
                    "deep_link": "/planning",
                },
            )
    except Exception:
        logger.warning("Failed to notify HOD of plan unpublish", exc_info=True)

    return plan


async def get_institution_overview(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Admin dashboard — one row per department with plan status + TA aggregates."""
    # All plans for this institution+term
    plans_result = await db.execute(
        select(DepartmentPlan).where(
            DepartmentPlan.institution_id == institution_id,
            DepartmentPlan.academic_term_id == academic_term_id,
        )
    )
    plans = {p.department_id: p for p in plans_result.scalars().all()}

    # All TAs for this institution+term
    tas_result = await db.execute(
        select(TeachingAssignment).where(
            TeachingAssignment.institution_id == institution_id,
            TeachingAssignment.academic_term_id == academic_term_id,
            TeachingAssignment.is_active.is_(True),
        )
    )
    tas = list(tas_result.scalars().all())

    # Group TAs by department
    ta_by_dept: dict[uuid.UUID, list[TeachingAssignment]] = {}
    for ta in tas:
        ta_by_dept.setdefault(ta.department_id, []).append(ta)

    # All departments in this institution
    depts_result = await db.execute(
        select(Department).where(
            Department.institution_id == institution_id,
            Department.is_active.is_(True),
        )
    )
    depts = list(depts_result.scalars().all())

    rows = []
    for dept in depts:
        plan = plans.get(dept.id)
        dept_tas = ta_by_dept.get(dept.id, [])
        total = len(dept_tas)
        assigned = sum(1 for t in dept_tas if t.faculty_id is not None)
        pending = total - assigned

        rows.append({
            "dept_id": str(dept.id),
            "dept_code": dept.code,
            "dept_name": dept.name,
            "dept_type": (dept.dept_type if isinstance(dept.dept_type, str) else dept.dept_type.value) if dept.dept_type else "ACADEMIC",
            "status": plan.status.value if plan else PlanStatus.DRAFT.value,
            "submitted_at": plan.submitted_at.isoformat() if plan and plan.submitted_at else None,
            "approved_at": plan.approved_at.isoformat() if plan and plan.approved_at else None,
            "sent_back_reason": plan.sent_back_reason if plan else None,
            "total_courses": total,
            "assigned": assigned,
            "pending": pending,
        })

    return rows


async def export_plan_csv(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
) -> str:
    """Return a CSV string of all teaching assignments for this dept+term."""
    from app.models.faculty import Faculty
    from app.models.course import Course

    await _assert_dept_in_institution(db, institution_id, department_id)
    tas_result = await db.execute(
        select(TeachingAssignment).where(
            TeachingAssignment.institution_id == institution_id,
            TeachingAssignment.academic_term_id == academic_term_id,
            TeachingAssignment.department_id == department_id,
            TeachingAssignment.is_active.is_(True),
        )
    )
    tas = list(tas_result.scalars().all())

    # Batch-fetch faculty and courses
    fac_ids = [t.faculty_id for t in tas if t.faculty_id]
    course_ids = [t.course_id for t in tas]

    fac_map: dict[str, str] = {}
    if fac_ids:
        rows = await db.execute(select(Faculty.id, Faculty.name).where(Faculty.id.in_(fac_ids)))
        fac_map = {str(r.id): r.name or "" for r in rows.all()}

    course_map: dict[str, tuple[str, str]] = {}
    if course_ids:
        rows = await db.execute(select(Course.id, Course.code, Course.name).where(Course.id.in_(course_ids)))
        course_map = {str(r.id): (r.code or "", r.name or "") for r in rows.all()}

    svc_dept_ids = [t.requested_dept_id for t in tas if t.requested_dept_id]
    svc_dept_map: dict[str, str] = {}
    if svc_dept_ids:
        rows = await db.execute(select(Department.id, Department.code).where(Department.id.in_(svc_dept_ids)))
        svc_dept_map = {str(r.id): r.code or "" for r in rows.all()}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "course_code", "course_name", "faculty_name", "section_count",
        "is_cross_dept", "service_dept_code", "is_pending", "notes",
    ])
    for ta in tas:
        code, name = course_map.get(str(ta.course_id), ("", ""))
        writer.writerow([
            code,
            name,
            fac_map.get(str(ta.faculty_id), "") if ta.faculty_id else "",
            ta.section_count,
            "yes" if ta.requested_dept_id else "no",
            svc_dept_map.get(str(ta.requested_dept_id), "") if ta.requested_dept_id else "",
            "yes" if ta.faculty_id is None else "no",
            ta.notes or "",
        ])

    return buf.getvalue()


async def export_plan_html(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
) -> str:
    """Return a printer-friendly HTML table of teaching assignments."""
    from app.models.faculty import Faculty
    from app.models.course import Course

    dept = await _assert_dept_in_institution(db, institution_id, department_id)
    dept_name = dept.name or str(department_id)

    tas_result = await db.execute(
        select(TeachingAssignment).where(
            TeachingAssignment.institution_id == institution_id,
            TeachingAssignment.academic_term_id == academic_term_id,
            TeachingAssignment.department_id == department_id,
            TeachingAssignment.is_active.is_(True),
        )
    )
    tas = list(tas_result.scalars().all())

    fac_ids = [t.faculty_id for t in tas if t.faculty_id]
    course_ids = [t.course_id for t in tas]
    fac_map: dict[str, str] = {}
    if fac_ids:
        rows = await db.execute(select(Faculty.id, Faculty.name).where(Faculty.id.in_(fac_ids)))
        fac_map = {str(r.id): r.name or "" for r in rows.all()}
    course_map: dict[str, tuple[str, str]] = {}
    if course_ids:
        rows = await db.execute(select(Course.id, Course.code, Course.name).where(Course.id.in_(course_ids)))
        course_map = {str(r.id): (r.code or "", r.name or "") for r in rows.all()}

    rows_html = ""
    for ta in tas:
        code, name = course_map.get(str(ta.course_id), ("", ""))
        fac = fac_map.get(str(ta.faculty_id), "—") if ta.faculty_id else "<em>Pending</em>"
        pending_style = " color:#b45309;" if ta.faculty_id is None else ""
        rows_html += (
            f"<tr><td>{code}</td><td>{name}</td>"
            f"<td style='{pending_style}'>{fac}</td>"
            f"<td style='text-align:center'>{ta.section_count}</td>"
            f"<td>{ta.notes or ''}</td></tr>\n"
        )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{dept_name} Teaching Plan</title>
<style>
  body{{font-family:sans-serif;padding:32px;color:#111}}
  h1{{font-size:18px;margin-bottom:4px}}
  p{{font-size:13px;color:#555;margin-bottom:20px}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{background:#f3f4f6;text-align:left;padding:8px 12px;border:1px solid #e5e7eb;font-weight:600}}
  td{{padding:8px 12px;border:1px solid #e5e7eb}}
  tr:nth-child(even){{background:#fafafa}}
</style>
</head>
<body>
<h1>{dept_name} — Teaching Plan</h1>
<p>Generated {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
<table>
<thead>
  <tr>
    <th>Course Code</th>
    <th>Course Name</th>
    <th>Faculty</th>
    <th>Sections</th>
    <th>Notes</th>
  </tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Excel export helpers (openpyxl — imported lazily)
# ---------------------------------------------------------------------------

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_HEADER_FILL = "4F46E5"
_HEADER_FONT = "FFFFFF"
_FILL_TBA = "FEF3C7"
_FILL_CROSS = "DBEAFE"
_FILL_ODD = "F9FAFB"
_FILL_TITLE = "F0F4FF"

_STATUS_COLORS = {
    "DRAFT": "6B7280",
    "HOD_PUBLISHED": "B45309",
    "ADMIN_APPROVED": "16A34A",
}

# 13 columns: (header label, column width in chars)
_COLUMNS: list[tuple[str, int]] = [
    ("Sr. No", 6),
    ("Course Code", 13),
    ("Course Name", 32),
    ("Session Type", 13),
    ("L-T-P", 9),
    ("Credits", 8),
    ("Faculty Name", 22),
    ("Home Dept", 14),
    ("Sections", 9),
    ("Year", 6),
    ("Semester", 9),
    ("Notes", 28),
    ("Status", 10),
]


def _ltp_string(structure: Any, session_type: str | None, weekly_hours: int) -> str:
    if isinstance(structure, dict) and any(k in structure for k in ("L", "T", "P")):
        l = int(structure.get("L", 0))
        t = int(structure.get("T", 0))
        p = int(structure.get("P", 0))
        return f"{l}-{t}-{p}"
    st = (session_type or "").upper()
    if st == "LAB":
        return f"0-0-{weekly_hours}"
    return f"{weekly_hours}-0-0"


def _safe_sheet_name(name: str, used: set[str] | None = None) -> str:
    import re
    safe = re.sub(r"[\[\]:*?/\\]", "", str(name))[:31].strip()
    if not safe:
        safe = "Sheet"
    if used is None:
        return safe
    original = safe
    counter = 2
    while safe in used:
        suffix = f"_{counter}"
        safe = original[: 31 - len(suffix)] + suffix
        counter += 1
    used.add(safe)
    return safe


def _build_dept_sheet(
    ws: Any,
    rows: list[dict[str, Any]],
    dept_name: str,
    institution_name: str,
    term_name: str,
    plan_status: str,
) -> None:
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    n_cols = len(_COLUMNS)
    last_col = get_column_letter(n_cols)

    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def _fill(hex_color: str) -> PatternFill:
        return PatternFill("solid", fgColor=hex_color)

    def _font(bold=False, color="111827", size=10) -> Font:
        return Font(bold=bold, color=color, size=size)

    # ── Row 1: title ─────────────────────────────────────────────────────────
    ws.merge_cells(f"A1:{last_col}1")
    title_cell = ws["A1"]
    title_cell.value = f"{institution_name} — {dept_name} Teaching Plan"
    title_cell.font = Font(bold=True, size=13, color="1A1A2E")
    title_cell.fill = _fill(_FILL_TITLE)
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    # ── Row 2: metadata ───────────────────────────────────────────────────────
    ws["A2"].value = f"Term: {term_name}"
    ws["A2"].font = _font(color="6B7280")
    ws["E2"].value = f"Status: {plan_status}"
    ws["E2"].font = Font(size=10, color=_STATUS_COLORS.get(plan_status, "6B7280"))
    ws["I2"].value = f"Generated: {datetime.now(tz=timezone.utc).strftime('%d %b %Y, %H:%M UTC')}"
    ws["I2"].font = _font(color="6B7280")

    # ── Row 3: blank spacer ───────────────────────────────────────────────────
    ws.row_dimensions[3].height = 6

    # ── Row 4: column headers ─────────────────────────────────────────────────
    for col_idx, (label, _) in enumerate(_COLUMNS, start=1):
        cell = ws.cell(row=4, column=col_idx, value=label)
        cell.font = Font(bold=True, color=_HEADER_FONT, size=10)
        cell.fill = _fill(_HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.row_dimensions[4].height = 18

    # ── Rows 5+: data ─────────────────────────────────────────────────────────
    for i, row in enumerate(rows):
        excel_row = 5 + i

        is_tba = not row.get("faculty_id")
        is_cross = row.get("is_cross_dept", False)
        if is_tba:
            row_fill = _fill(_FILL_TBA)
        elif is_cross:
            row_fill = _fill(_FILL_CROSS)
        elif i % 2 == 0:
            row_fill = _fill(_FILL_ODD)
        else:
            row_fill = _fill("FFFFFF")

        values = [
            i + 1,
            row.get("course_code", ""),
            row.get("course_name", ""),
            row.get("session_type", ""),
            row.get("ltp", ""),
            row.get("credits", ""),
            row.get("faculty_name", "—") if not is_tba else "—",
            row.get("home_dept", "—"),
            row.get("section_count", 1),
            row.get("study_year") or "—",
            row.get("study_semester") or "—",
            row.get("notes", ""),
            "TBA" if is_tba else "Assigned",
        ]

        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=excel_row, column=col_idx, value=value)
            cell.fill = row_fill
            cell.border = border
            cell.font = _font(color="111827")
            cell.alignment = Alignment(vertical="center", wrap_text=col_idx == 3)

        # TBA status cell: bold amber
        if is_tba:
            ws.cell(row=excel_row, column=13).font = Font(bold=True, color="B45309", size=10)

    # ── Column widths ─────────────────────────────────────────────────────────
    for col_idx, (_, preset_width) in enumerate(_COLUMNS, start=1):
        col_letter = get_column_letter(col_idx)
        # Use preset width as baseline; expand if content is wider
        max_content = max(
            (len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(4, 5 + len(rows))),
            default=0,
        )
        ws.column_dimensions[col_letter].width = min(max(preset_width, max_content + 2), 60)

    # ── Freeze top 4 rows ─────────────────────────────────────────────────────
    ws.freeze_panes = "A5"


def _build_summary_sheet(
    ws: Any,
    overview_rows: list[dict[str, Any]],
    institution_name: str,
    term_name: str,
) -> None:
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def _fill(hex_color: str) -> PatternFill:
        return PatternFill("solid", fgColor=hex_color)

    sum_cols = ["Department", "Code", "Status", "Total Courses", "Assigned", "Pending"]
    last_col = get_column_letter(len(sum_cols))

    # Title
    ws.merge_cells(f"A1:{last_col}1")
    ws["A1"].value = f"{institution_name} — All Departments Summary"
    ws["A1"].font = Font(bold=True, size=13, color="1A1A2E")
    ws["A1"].fill = _fill(_FILL_TITLE)
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    # Metadata
    ws["A2"].value = f"Term: {term_name}"
    ws["A2"].font = Font(size=10, color="6B7280")
    ws["D2"].value = f"Generated: {datetime.now(tz=timezone.utc).strftime('%d %b %Y, %H:%M UTC')}"
    ws["D2"].font = Font(size=10, color="6B7280")
    ws.row_dimensions[3].height = 6

    # Headers
    for col_idx, label in enumerate(sum_cols, start=1):
        cell = ws.cell(row=4, column=col_idx, value=label)
        cell.font = Font(bold=True, color=_HEADER_FONT, size=10)
        cell.fill = _fill(_HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.row_dimensions[4].height = 18

    sorted_rows = sorted(overview_rows, key=lambda r: r.get("dept_name") or "")
    total_courses = total_assigned = total_pending = 0

    for i, row in enumerate(sorted_rows):
        excel_row = 5 + i
        status = row.get("status", "DRAFT")
        row_fill = _fill(_FILL_ODD) if i % 2 == 0 else _fill("FFFFFF")

        tc = row.get("total_courses", 0)
        asgn = row.get("assigned", 0)
        pend = row.get("pending", 0)
        total_courses += tc
        total_assigned += asgn
        total_pending += pend

        row_values = [
            row.get("dept_name", ""),
            row.get("dept_code", ""),
            status,
            tc,
            asgn,
            pend,
        ]
        for col_idx, value in enumerate(row_values, start=1):
            cell = ws.cell(row=excel_row, column=col_idx, value=value)
            cell.fill = row_fill
            cell.border = border
            cell.font = Font(size=10, color="111827")
            cell.alignment = Alignment(vertical="center")

        # Color-code status cell
        status_cell = ws.cell(row=excel_row, column=3)
        status_cell.font = Font(size=10, color=_STATUS_COLORS.get(status, "6B7280"), bold=True)

    # Totals row
    totals_row = 5 + len(sorted_rows)
    totals = ["INSTITUTION TOTAL", "", "", total_courses, total_assigned, total_pending]
    for col_idx, value in enumerate(totals, start=1):
        cell = ws.cell(row=totals_row, column=col_idx, value=value)
        cell.font = Font(bold=True, size=10, color="111827")
        cell.fill = _fill("E0E7FF")
        cell.border = border
        cell.alignment = Alignment(vertical="center")

    # Column widths
    preset_widths = [28, 8, 16, 13, 10, 10]
    for col_idx, w in enumerate(preset_widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = w

    ws.freeze_panes = "A5"


# ---------------------------------------------------------------------------
# Excel export service functions
# ---------------------------------------------------------------------------


async def export_plan_excel(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    semester_filter: int | None = None,
) -> bytes:
    """Return an Excel (.xlsx) workbook for a single dept teaching plan."""
    from openpyxl import Workbook
    from app.models.faculty import Faculty
    from app.models.course import Course
    from app.models.institution import Institution, AcademicTerm

    dept = await _assert_dept_in_institution(db, institution_id, department_id)

    # Fetch institution + term names
    inst = await db.get(Institution, institution_id)
    term = await db.get(AcademicTerm, academic_term_id)
    institution_name = (inst.name if inst else "") or str(institution_id)
    term_name = (term.name if term else "") or str(academic_term_id)

    # Fetch plan status
    plan = await _get_plan(db, academic_term_id, department_id)
    plan_status = plan.status.value if plan else PlanStatus.DRAFT.value

    # Fetch TAs
    filters = [
        TeachingAssignment.institution_id == institution_id,
        TeachingAssignment.academic_term_id == academic_term_id,
        TeachingAssignment.department_id == department_id,
        TeachingAssignment.is_active.is_(True),
    ]
    if semester_filter is not None:
        filters.append(TeachingAssignment.study_semester == semester_filter)
    tas = list((await db.execute(select(TeachingAssignment).where(*filters))).scalars().all())

    rows = await _enrich_tas_for_excel(db, tas, department_id)

    wb = Workbook()
    ws = wb.active
    ws.title = _safe_sheet_name(dept.code or dept.name or "Plan")
    _build_dept_sheet(ws, rows, dept.name or str(department_id), institution_name, term_name, plan_status)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def export_all_depts_excel(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    semester_filter: int | None = None,
) -> bytes:
    """Return an Excel (.xlsx) workbook with one sheet per department + a Summary sheet."""
    from openpyxl import Workbook
    from app.models.faculty import Faculty
    from app.models.course import Course
    from app.models.institution import Institution, AcademicTerm
    from app.models.user import User

    inst = await db.get(Institution, institution_id)
    term = await db.get(AcademicTerm, academic_term_id)
    institution_name = (inst.name if inst else "") or str(institution_id)
    term_name = (term.name if term else "") or str(academic_term_id)

    # All ACADEMIC depts
    depts = list((await db.execute(
        select(Department).where(
            Department.institution_id == institution_id,
            Department.is_active.is_(True),
        )
    )).scalars().all())
    depts.sort(key=lambda d: d.name or "")

    # All TAs for institution+term in one query
    ta_filters = [
        TeachingAssignment.institution_id == institution_id,
        TeachingAssignment.academic_term_id == academic_term_id,
        TeachingAssignment.is_active.is_(True),
    ]
    if semester_filter is not None:
        ta_filters.append(TeachingAssignment.study_semester == semester_filter)
    all_tas = list((await db.execute(select(TeachingAssignment).where(*ta_filters))).scalars().all())

    ta_by_dept: dict[uuid.UUID, list[TeachingAssignment]] = {}
    for ta in all_tas:
        ta_by_dept.setdefault(ta.department_id, []).append(ta)

    # Batch-fetch all enrichment data across all TAs at once
    all_fac_ids = [t.faculty_id for t in all_tas if t.faculty_id]
    all_course_ids = list({t.course_id for t in all_tas})
    all_svc_dept_ids = [t.requested_dept_id for t in all_tas if t.requested_dept_id]

    fac_map: dict[str, tuple[str, str | None]] = {}
    if all_fac_ids:
        # department_id lives on User, not Faculty — join to get it
        for r in (await db.execute(
            select(Faculty.id, Faculty.name, User.department_id)
            .outerjoin(User, Faculty.user_id == User.id)
            .where(Faculty.id.in_(all_fac_ids))
        )).all():
            fac_map[str(r.id)] = (r.name or "", str(r.department_id) if r.department_id else None)

    course_map: dict[str, tuple[str, str, Any, int, str, int]] = {}
    if all_course_ids:
        for r in (await db.execute(
            select(Course.id, Course.code, Course.name, Course.structure, Course.credits, Course.session_type, Course.weekly_hours)
            .where(Course.id.in_(all_course_ids))
        )).all():
            course_map[str(r.id)] = (
                r.code or "", r.name or "", r.structure or {}, int(r.credits or 3),
                str(r.session_type.value if hasattr(r.session_type, "value") else r.session_type or ""),
                int(r.weekly_hours or 3),
            )

    # dept_name_map covers own depts + service depts + faculty home depts (for cross-dept display)
    dept_name_map: dict[str, str] = {str(d.id): d.name or d.code or str(d.id) for d in depts}
    extra_dept_ids = list(
        {str(fac_dept) for _, fac_dept in fac_map.values() if fac_dept} |
        {str(sid) for sid in all_svc_dept_ids}
    )
    if extra_dept_ids:
        for r in (await db.execute(
            select(Department.id, Department.name).where(Department.id.in_(extra_dept_ids))
        )).all():
            dept_name_map[str(r.id)] = r.name or str(r.id)

    # All plan statuses
    plans_result = await db.execute(
        select(DepartmentPlan).where(
            DepartmentPlan.institution_id == institution_id,
            DepartmentPlan.academic_term_id == academic_term_id,
        )
    )
    plans = {p.department_id: p for p in plans_result.scalars().all()}

    # Build workbook
    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Summary"

    overview_rows: list[dict[str, Any]] = []
    used_names: set[str] = {"Summary"}

    for dept in depts:
        dept_tas = ta_by_dept.get(dept.id, [])
        total = len(dept_tas)
        assigned = sum(1 for t in dept_tas if t.faculty_id is not None)
        pending = total - assigned
        plan = plans.get(dept.id)
        status = plan.status.value if plan else PlanStatus.DRAFT.value

        overview_rows.append({
            "dept_name": dept.name or dept.code,
            "dept_code": dept.code,
            "status": status,
            "total_courses": total,
            "assigned": assigned,
            "pending": pending,
        })

        rows = _enrich_tas_for_excel_sync(dept_tas, dept.id, fac_map, course_map, dept_name_map)
        sheet_name = _safe_sheet_name(dept.code or dept.name or "Dept", used_names)
        ws = wb.create_sheet(sheet_name)
        _build_dept_sheet(ws, rows, dept.name or str(dept.id), institution_name, term_name, status)

    _build_summary_sheet(summary_ws, overview_rows, institution_name, term_name)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _enrich_tas_for_excel(
    db: AsyncSession,
    tas: list[TeachingAssignment],
    owning_dept_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Enrich a list of TAs with faculty/course/dept data for a single dept export."""
    from app.models.faculty import Faculty
    from app.models.course import Course
    from app.models.user import User

    fac_ids = [t.faculty_id for t in tas if t.faculty_id]
    course_ids = list({t.course_id for t in tas})
    svc_dept_ids = [t.requested_dept_id for t in tas if t.requested_dept_id]

    fac_map: dict[str, tuple[str, str | None]] = {}
    if fac_ids:
        # department_id lives on User, not Faculty — join to get it
        for r in (await db.execute(
            select(Faculty.id, Faculty.name, User.department_id)
            .outerjoin(User, Faculty.user_id == User.id)
            .where(Faculty.id.in_(fac_ids))
        )).all():
            fac_map[str(r.id)] = (r.name or "", str(r.department_id) if r.department_id else None)

    course_map: dict[str, tuple[str, str, Any, int, str, int]] = {}
    if course_ids:
        for r in (await db.execute(
            select(Course.id, Course.code, Course.name, Course.structure, Course.credits, Course.session_type, Course.weekly_hours)
            .where(Course.id.in_(course_ids))
        )).all():
            course_map[str(r.id)] = (
                r.code or "", r.name or "", r.structure or {}, int(r.credits or 3),
                str(r.session_type.value if hasattr(r.session_type, "value") else r.session_type or ""),
                int(r.weekly_hours or 3),
            )

    # dept_name_map covers service depts (requested_dept_id) + faculty home depts (cross-dept display)
    dept_name_map: dict[str, str] = {}
    extra_dept_ids = list(
        {str(fac_dept) for _, fac_dept in fac_map.values() if fac_dept} |
        {str(sid) for sid in svc_dept_ids}
    )
    if extra_dept_ids:
        for r in (await db.execute(
            select(Department.id, Department.name).where(Department.id.in_(extra_dept_ids))
        )).all():
            dept_name_map[str(r.id)] = r.name or str(r.id)

    return _enrich_tas_for_excel_sync(tas, owning_dept_id, fac_map, course_map, dept_name_map)


def _enrich_tas_for_excel_sync(
    tas: list[TeachingAssignment],
    owning_dept_id: uuid.UUID,
    fac_map: dict[str, tuple[str, str | None]],
    course_map: dict[str, tuple[str, str, Any, int, str, int]],
    dept_name_map: dict[str, str],
) -> list[dict[str, Any]]:
    """Build enriched row dicts from pre-fetched maps. Synchronous."""
    owning_dept_id_str = str(owning_dept_id)

    def sort_key(t: TeachingAssignment) -> tuple:
        yr = t.study_year if t.study_year is not None else 9999
        sem = t.study_semester if t.study_semester is not None else 9999
        c = course_map.get(str(t.course_id), ("zzz",))[0]
        return (yr, sem, c)

    rows = []
    for ta in sorted(tas, key=sort_key):
        course_data = course_map.get(str(ta.course_id), ("", "", {}, 3, "", 3))
        code, name, structure, credits, session_type, weekly_hours = course_data

        fac_name = ""
        fac_dept_id: str | None = None
        if ta.faculty_id:
            fac_name, fac_dept_id = fac_map.get(str(ta.faculty_id), ("", None))

        is_cross = fac_dept_id is not None and fac_dept_id != owning_dept_id_str
        home_dept = ""
        if is_cross and fac_dept_id:
            home_dept = dept_name_map.get(fac_dept_id, fac_dept_id)
        elif ta.requested_dept_id and not ta.faculty_id:
            # Pending cross-dept request
            home_dept = dept_name_map.get(str(ta.requested_dept_id), "")
            is_cross = bool(home_dept)

        rows.append({
            "faculty_id": str(ta.faculty_id) if ta.faculty_id else None,
            "course_code": code,
            "course_name": name,
            "session_type": session_type,
            "ltp": _ltp_string(structure, session_type, weekly_hours),
            "credits": credits,
            "faculty_name": fac_name,
            "home_dept": home_dept or "—",
            "is_cross_dept": is_cross,
            "section_count": ta.section_count,
            "study_year": ta.study_year,
            "study_semester": ta.study_semester,
            "notes": ta.notes or "",
        })
    return rows
