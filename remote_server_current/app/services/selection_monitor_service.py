"""Registration monitor stats for admin/HOD dashboards."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.selection_cache_service as cache_svc
import app.services.selection_window_service as window_svc
import app.services.student_service as student_svc
from app.models.course import Course
from app.models.curriculum import CourseOffering, OfferingBucket
from app.models.faculty import Faculty
from app.models.institution import Department
from app.models.selection import (
    DepartmentSelectionWindow,
    GroupSelectionStatus,
    StudentGroupSelection,
)
from app.services.hybrid_selection_service import _resolve_effective_max_seats


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _completion_pct(confirmed: int, eligible: int) -> float:
    if eligible <= 0:
        return 0.0
    return round(min(100.0, confirmed / eligible * 100.0), 1)


async def _count_selections(
    db: AsyncSession,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> tuple[int, int, int]:
    """Return (confirmed_count, draft_count, confirms_last_minute)."""
    base = (
        select(StudentGroupSelection.status, func.count())
        .where(
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.department_id == department_id,
            StudentGroupSelection.study_semester == study_semester,
        )
        .group_by(StudentGroupSelection.status)
    )
    result = await db.execute(base)
    status_counts = {row[0]: row[1] for row in result.all()}

    confirmed = int(status_counts.get(GroupSelectionStatus.CONFIRMED, 0))
    draft = int(status_counts.get(GroupSelectionStatus.DRAFT, 0))

    minute_ago = _utcnow() - timedelta(minutes=1)
    last_minute = await db.scalar(
        select(func.count())
        .select_from(StudentGroupSelection)
        .where(
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.department_id == department_id,
            StudentGroupSelection.study_semester == study_semester,
            StudentGroupSelection.status == GroupSelectionStatus.CONFIRMED,
            StudentGroupSelection.confirmed_at.is_not(None),
            StudentGroupSelection.confirmed_at >= minute_ago,
        )
    )
    return confirmed, draft, int(last_minute or 0)


async def get_completion_stats(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
    window: DepartmentSelectionWindow | None = None,
) -> dict:
    """Per-window completion summary for monitor cards."""
    if window is None:
        window = await window_svc.get_window(
            db, academic_term_id, department_id, study_semester
        )

    confirmed, draft, confirms_last_minute = await _count_selections(
        db,
        academic_term_id=academic_term_id,
        department_id=department_id,
        study_semester=study_semester,
    )
    eligible = await student_svc.count_students(
        db,
        institution_id,
        department_id=department_id,
        semester=study_semester,
    )
    pending = max(0, eligible - confirmed - draft)

    return {
        "department_id": department_id,
        "academic_term_id": academic_term_id,
        "study_semester": study_semester,
        "effective_phase": (
            window_svc.compute_effective_phase(window) if window else "DRAFT"
        ),
        "confirmed_count": confirmed,
        "draft_count": draft,
        "eligible_count": eligible,
        "pending_count": pending,
        "completion_pct": _completion_pct(confirmed, eligible),
        "confirms_last_minute": confirms_last_minute,
        "published_scenario_id": (
            window.published_scenario_id if window else None
        ),
    }


async def get_completion_overview(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    dept_filter: uuid.UUID | None = None,
) -> list[dict]:
    """Cross-dept completion matrix for admin overview."""
    windows = await window_svc.list_windows(
        db, institution_id, academic_term_id, dept_filter
    )
    if not windows:
        return []

    dept_ids = {w.department_id for w in windows}
    dept_rows = await db.execute(
        select(Department.id, Department.name).where(Department.id.in_(dept_ids))
    )
    dept_names = {row.id: row.name for row in dept_rows.all()}

    items: list[dict] = []
    for window in sorted(windows, key=lambda w: (str(w.department_id), w.study_semester)):
        stats = await get_completion_stats(
            db,
            institution_id=institution_id,
            academic_term_id=academic_term_id,
            department_id=window.department_id,
            study_semester=window.study_semester,
            window=window,
        )
        stats["department_name"] = dept_names.get(window.department_id)
        items.append(stats)
    return items


def _effective_max(
    offering_max: int | None,
    config_max: int | None,
) -> int | None:
    return offering_max if offering_max is not None else config_max


def _resolve_booked_and_remaining(
    offering_id: str,
    db_booked: int,
    eff_max: int | None,
    live_seats: dict[str, int],
) -> tuple[int, int | None]:
    """Return (booked_seats, seats_remaining) using Redis when available."""
    remaining = live_seats.get(offering_id)
    if remaining is not None:
        if eff_max is not None:
            booked = max(0, eff_max - remaining)
        else:
            booked = db_booked
        return booked, remaining
    if eff_max is not None:
        return db_booked, max(0, eff_max - db_booked)
    return db_booked, None


async def get_offering_seat_dashboard(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
    academic_term_id: uuid.UUID | None = None,
    scenario_id: uuid.UUID | None = None,
) -> dict:
    """Enhanced per-offering availability for the registration monitor."""
    if scenario_id is None and academic_term_id is not None:
        window = await window_svc.get_window(
            db, academic_term_id, department_id, study_semester
        )
        if window and window.published_scenario_id:
            scenario_id = window.published_scenario_id

    effective_config_max: int | None = None
    if academic_term_id is not None:
        effective_config_max = await _resolve_effective_max_seats(
            db, institution_id, academic_term_id, department_id
        )

    q = (
        select(CourseOffering, Course, Faculty, OfferingBucket)
        .join(OfferingBucket, CourseOffering.bucket_id == OfferingBucket.id)
        .outerjoin(Course, CourseOffering.course_id == Course.id)
        .outerjoin(Faculty, CourseOffering.faculty_id == Faculty.id)
        .where(
            OfferingBucket.department_id == department_id,
            CourseOffering.study_semester == study_semester,
        )
    )
    if academic_term_id is not None:
        q = q.where(OfferingBucket.academic_term_id == academic_term_id)
    if scenario_id:
        q = q.where(OfferingBucket.scenario_id == scenario_id)

    result = await db.execute(q)
    rows = result.all()

    offering_ids = [str(offering.id) for offering, _, _, _ in rows]
    live_seats = await cache_svc.get_live_seat_counts(offering_ids)

    completion: dict | None = None
    if academic_term_id is not None:
        completion = await get_completion_stats(
            db,
            institution_id=institution_id,
            academic_term_id=academic_term_id,
            department_id=department_id,
            study_semester=study_semester,
        )

    items: list[dict] = []
    total_offering_bookings = 0
    for offering, course, faculty, bucket in rows:
        eff_max = _effective_max(offering.max_seats, effective_config_max)
        oid = str(offering.id)
        booked, remaining = _resolve_booked_and_remaining(
            oid, offering.booked_seats, eff_max, live_seats
        )
        total_offering_bookings += booked
        items.append(
            {
                "offering_id": offering.id,
                "bucket_id": bucket.id,
                "bucket_name": bucket.name,
                "selection_policy": bucket.selection_policy.value
                if hasattr(bucket.selection_policy, "value")
                else str(bucket.selection_policy),
                "course_id": offering.course_id,
                "course_code": course.code if course else None,
                "course_name": course.name if course else None,
                "faculty_name": faculty.name if faculty else None,
                "group_number": offering.group_number,
                "batch_number": offering.batch_number,
                "max_seats": offering.max_seats,
                "effective_max_seats": eff_max,
                "booked_seats": booked,
                "seats_remaining": remaining,
                "is_frozen": offering.is_frozen,
            }
        )

    items.sort(key=lambda x: (x["bucket_name"], x["course_code"] or "", x["faculty_name"] or ""))

    return {
        "confirms_last_minute": completion["confirms_last_minute"] if completion else 0,
        "confirmed_students": completion["confirmed_count"] if completion else 0,
        "total_offering_bookings": total_offering_bookings,
        "completion": completion,
        "offerings": items,
    }


async def sync_offering_seats_after_admin_update(
    db: AsyncSession,
    offering: CourseOffering,
) -> None:
    """Refresh Redis seat counter and notify SSE subscribers after admin edits."""
    bucket = await db.get(OfferingBucket, offering.bucket_id)
    if bucket is None or bucket.department_id is None:
        return

    study_semester = offering.study_semester
    if study_semester is None:
        return

    effective_config_max = await _resolve_effective_max_seats(
        db,
        bucket.institution_id,
        bucket.academic_term_id,
        bucket.department_id,
    )
    eff_max = _effective_max(offering.max_seats, effective_config_max)
    remaining = (
        max(0, eff_max - offering.booked_seats)
        if eff_max is not None
        else 10_000
    )
    await cache_svc.update_seat_counter(
        offering.id,
        remaining=remaining,
        max_seats=eff_max,
    )
    await cache_svc.invalidate_menu_cache(bucket.department_id, study_semester)
    await cache_svc.publish_cohort_seat_update(
        bucket.department_id,
        study_semester,
        scope="partial",
    )
