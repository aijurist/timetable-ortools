"""
allocation/strategies/shared.py
================================
HYBRID / CHOOSE_FACULTY allocation strategy.

Covers two sub-modes:
  shared_dept         — one shared bucket per course, dept-owned
  shared_cross_dept   — one shared bucket per course, dept_id=NULL (cross-dept)

Policy: ALL faculty in faculty_ids become separate CourseOfferings in ONE shared bucket.
The CP-SAT mini-solver is NOT used here — no 1:1 faculty→section assignment.

Creates:
  - ONE OfferingBucket(CHOOSE_FACULTY, dept=primary_dept | NULL, name="{course} (dept sections)")
  - ONE TargetRequirement per target that demands this course → shared bucket
  - ONE CourseOffering per faculty_id in the assignment
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models.curriculum import CourseOffering, OfferingBucket, SelectionPolicy, TargetRequirement

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("allocation.strategy.shared")


async def allocate_shared(
    db: "AsyncSession",
    course_id: uuid.UUID,
    faculty_ids: list[uuid.UUID],
    demands_for_course: list[Any],        # TargetCourseDemand rows
    ctx: Any,                             # AllocationContext
    cross_dept: bool = False,             # True → shared_cross_dept (dept_id=NULL)
    overwrite_existing: bool = False,
    dry_run: bool = False,
    cohort_class_size: int | None = None, # → CourseOffering.min_capacity for room routing
    pinned_faculty_ids: set[uuid.UUID] | None = None,  # these offerings get is_frozen=True
) -> dict:
    """
    Create one shared CHOOSE_FACULTY bucket for a course with all eligible faculty.

    Returns counts dict: buckets_created, offerings_created, offerings_updated,
    warnings, unassigned, details.
    """
    from app.schemas.allocation import AllocationOfferingDetail

    buckets_created = 0
    offerings_created = 0
    offerings_updated = 0
    warnings: list[str] = []
    unassigned: list[str] = []
    details: list[AllocationOfferingDetail] = []

    if not demands_for_course:
        return _empty_result()

    course = ctx.courses.get(str(course_id))
    course_name = course.name if course else str(course_id)

    # Determine dept ownership
    primary_dept_id: uuid.UUID | None = None
    if not cross_dept and demands_for_course:
        first_demand = demands_for_course[0]
        target = ctx.targets.get(str(first_demand.target_id))
        if target:
            primary_dept_id = target.department_id

    bucket_name = f"{course_name} (dept sections)"

    if not faculty_ids:
        for demand in demands_for_course:
            target = ctx.targets.get(str(demand.target_id))
            unassigned.append(
                f"{target.name if target else demand.target_id} / {course_name}"
            )
        return _empty_result(unassigned=unassigned)

    if dry_run:
        for demand in demands_for_course:
            target = ctx.targets.get(str(demand.target_id))
            target_name = target.name if target else str(demand.target_id)
            for fid in faculty_ids:
                faculty = ctx.faculty.get(str(fid))
                details.append(AllocationOfferingDetail(
                    target_id=demand.target_id,
                    target_name=target_name,
                    course_id=course_id,
                    course_name=course_name,
                    faculty_id=fid,
                    faculty_name=faculty.name if faculty else str(fid),
                    offering_id=None,
                    bucket_id=None,
                    is_new=True,
                ))
        return {
            "buckets_created": 1,
            "offerings_created": len(faculty_ids),
            "offerings_updated": 0,
            "warnings": warnings,
            "unassigned": unassigned,
            "details": details,
        }

    # ── Find or create shared bucket ──────────────────────────────────────────
    stmt = select(OfferingBucket).where(
        OfferingBucket.institution_id == demands_for_course[0].institution_id,
        OfferingBucket.academic_term_id == demands_for_course[0].academic_term_id,
        OfferingBucket.name == bucket_name,
        OfferingBucket.selection_policy == SelectionPolicy.CHOOSE_FACULTY,
        OfferingBucket.scenario_id == ctx.scenario_id,
    )
    result = await db.execute(stmt)
    bucket = result.scalar_one_or_none()
    if bucket is None:
        bucket = OfferingBucket(
            institution_id=demands_for_course[0].institution_id,
            academic_term_id=demands_for_course[0].academic_term_id,
            department_id=primary_dept_id if not cross_dept else None,
            name=bucket_name,
            selection_policy=SelectionPolicy.CHOOSE_FACULTY,
            min_selection=1,
            max_selection=1,
            scenario_id=ctx.scenario_id,
        )
        db.add(bucket)
        await db.flush()
        buckets_created = 1

    # ── TargetRequirements for all targets demanding this course ──────────────
    for demand in demands_for_course:
        req_stmt = select(TargetRequirement).where(
            TargetRequirement.target_id == demand.target_id,
            TargetRequirement.bucket_id == bucket.id,
        )
        req_result = await db.execute(req_stmt)
        req = req_result.scalar_one_or_none()
        if req is None:
            req = TargetRequirement(target_id=demand.target_id, bucket_id=bucket.id)
            db.add(req)
    await db.flush()

    # ── CourseOffering per faculty ─────────────────────────────────────────────
    for fid in faculty_ids:
        off_stmt = select(CourseOffering).where(
            CourseOffering.bucket_id == bucket.id,
            CourseOffering.course_id == course_id,
            CourseOffering.faculty_id == fid,
        )
        off_result = await db.execute(off_stmt)
        offering = off_result.scalar_one_or_none()
        is_new = offering is None
        if offering is None:
            offering = CourseOffering(
                bucket_id=bucket.id,
                course_id=course_id,
                faculty_id=fid,
                min_capacity=cohort_class_size,
                is_frozen=(fid in (pinned_faculty_ids or set())),
            )
            db.add(offering)
            await db.flush()
            offerings_created += 1
        elif overwrite_existing:
            offerings_updated += 1

        faculty = ctx.faculty.get(str(fid))
        # Attach details once per faculty (multiple targets → same offering)
        for demand in demands_for_course:
            target = ctx.targets.get(str(demand.target_id))
            details.append(AllocationOfferingDetail(
                target_id=demand.target_id,
                target_name=target.name if target else str(demand.target_id),
                course_id=course_id,
                course_name=course_name,
                faculty_id=fid,
                faculty_name=faculty.name if faculty else str(fid),
                offering_id=offering.id,
                bucket_id=bucket.id,
                is_new=is_new,
            ))

    return {
        "buckets_created": buckets_created,
        "offerings_created": offerings_created,
        "offerings_updated": offerings_updated,
        "warnings": warnings,
        "unassigned": unassigned,
        "details": details,
    }


def _empty_result(unassigned: list[str] | None = None) -> dict:
    return {
        "buckets_created": 0,
        "offerings_created": 0,
        "offerings_updated": 0,
        "warnings": [],
        "unassigned": unassigned or [],
        "details": [],
    }
