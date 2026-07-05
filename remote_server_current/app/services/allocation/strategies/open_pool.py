"""
allocation/strategies/open_pool.py
====================================
FFCS / OPEN_POOL allocation strategy.

Policy: all faculty become separate OPEN_POOL offerings in one institution-wide bucket.
Students self-register against individual offerings (max_seats enforced).

Creates:
  - ONE OfferingBucket(OPEN_POOL, dept=NULL, name="{course} (open pool)")
  - ONE CourseOffering per faculty_id with max_seats set
  - TargetRequirements for all targets that demand this course (optional in FFCS
    since students self-register, but kept for demand tracking)
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models.curriculum import CourseOffering, OfferingBucket, SelectionPolicy, TargetRequirement

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("allocation.strategy.open_pool")

# Default max_seats per FFCS offering when not specified
_DEFAULT_MAX_SEATS = 60


async def allocate_open_pool(
    db: "AsyncSession",
    course_id: uuid.UUID,
    faculty_ids: list[uuid.UUID],
    demands_for_course: list[Any],   # TargetCourseDemand rows
    ctx: Any,                        # AllocationContext
    overwrite_existing: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Create one OPEN_POOL bucket for a course with per-faculty offerings.

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
    bucket_name = f"{course_name} (open pool)"

    if not faculty_ids:
        for demand in demands_for_course:
            target = ctx.targets.get(str(demand.target_id))
            unassigned.append(
                f"{target.name if target else demand.target_id} / {course_name}"
            )
        return _empty_result(unassigned=unassigned)

    if dry_run:
        for fid in faculty_ids:
            faculty = ctx.faculty.get(str(fid))
            details.append(AllocationOfferingDetail(
                target_id=demands_for_course[0].target_id,
                target_name="(open pool)",
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

    # ── Find or create open pool bucket ──────────────────────────────────────
    institution_id = demands_for_course[0].institution_id
    academic_term_id = demands_for_course[0].academic_term_id

    stmt = select(OfferingBucket).where(
        OfferingBucket.institution_id == institution_id,
        OfferingBucket.academic_term_id == academic_term_id,
        OfferingBucket.name == bucket_name,
        OfferingBucket.selection_policy == SelectionPolicy.OPEN_POOL,
        OfferingBucket.scenario_id == ctx.scenario_id,
    )
    result = await db.execute(stmt)
    bucket = result.scalar_one_or_none()
    if bucket is None:
        bucket = OfferingBucket(
            institution_id=institution_id,
            academic_term_id=academic_term_id,
            department_id=None,   # institution-wide
            name=bucket_name,
            selection_policy=SelectionPolicy.OPEN_POOL,
            min_selection=1,
            max_selection=1,
            scenario_id=ctx.scenario_id,
        )
        db.add(bucket)
        await db.flush()
        buckets_created = 1

    # ── TargetRequirements ────────────────────────────────────────────────────
    for demand in demands_for_course:
        req_stmt = select(TargetRequirement).where(
            TargetRequirement.target_id == demand.target_id,
            TargetRequirement.bucket_id == bucket.id,
        )
        req_result = await db.execute(req_stmt)
        if req_result.scalar_one_or_none() is None:
            db.add(TargetRequirement(target_id=demand.target_id, bucket_id=bucket.id))
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
                max_seats=_DEFAULT_MAX_SEATS,
                booked_seats=0,
            )
            db.add(offering)
            await db.flush()
            offerings_created += 1
        elif overwrite_existing:
            offerings_updated += 1

        faculty = ctx.faculty.get(str(fid))
        details.append(AllocationOfferingDetail(
            target_id=demands_for_course[0].target_id,
            target_name="(open pool)",
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
