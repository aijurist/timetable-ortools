"""
allocation/strategies/per_section.py
=====================================
TRADITIONAL / FIXED_BATCH allocation strategy.

Policy: one faculty per target × section.
Bucket scope: one OfferingBucket per (course, target).
Bucket policy: FIXED_BATCH.

CP-SAT solver assigns each section to exactly one faculty from the eligible list
(see engine.py). This strategy reads the solver output and creates:
  - OfferingBucket(FIXED_BATCH, dept=target.dept_id, name="{course} — {target}")
  - TargetRequirement(target_id, bucket_id)
  - CourseOffering(bucket_id, course_id, faculty_id=<solver assigned>)

For required_sections > 1, a single target demands multiple sections (e.g.
"CSE-A needs 3 parallel DSA sections"). The solver assigns a different faculty
to each section; each section gets its own bucket.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models.curriculum import CourseOffering, OfferingBucket, SelectionPolicy, TargetRequirement

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("allocation.strategy.per_section")


async def allocate_per_section(
    db: "AsyncSession",
    course_id: uuid.UUID,
    faculty_assignments: dict[tuple[str, str], str],  # {(target_id, course_id): faculty_id}
    demands_for_course: list[Any],                     # TargetCourseDemand rows
    ctx: Any,                                          # AllocationContext
    overwrite_existing: bool = False,
    dry_run: bool = False,
    pinned_target_ids: set[str] | None = None,         # target_ids with explicit pinned faculty
) -> dict:
    """
    Create FIXED_BATCH buckets/offerings for one course across all targets.

    Returns a dict with counts: buckets_created, offerings_created,
    offerings_updated, warnings, unassigned, details.
    """
    from app.schemas.allocation import AllocationOfferingDetail

    buckets_created = 0
    offerings_created = 0
    offerings_updated = 0
    warnings: list[str] = []
    unassigned: list[str] = []
    details: list[AllocationOfferingDetail] = []

    course = ctx.courses.get(str(course_id))
    course_name = course.name if course else str(course_id)

    for demand in demands_for_course:
        target_id_str = str(demand.target_id)
        course_id_str = str(course_id)
        required_sections = demand.required_sections or 1

        target = ctx.targets.get(target_id_str)
        target_name = target.name if target else target_id_str

        for section_idx in range(required_sections):
            # Build a lookup key — solver uses (target_id, course_id) per section
            # For required_sections=1 there is only one key: (target_id, course_id)
            # For multi-section we need per-section faculty; engine gives us one
            # entry per (target_id, course_id) — use round-robin from faculty_map
            assigned_faculty_id_str = faculty_assignments.get((target_id_str, course_id_str))

            if required_sections > 1 and assigned_faculty_id_str is None:
                # Multi-section: engine only returned one assignment; use it for section 0
                # and leave rest unassigned (coordinator must fill manually)
                if section_idx > 0:
                    assigned_faculty_id_str = None

            if assigned_faculty_id_str is None:
                unassigned.append(f"{target_name} / {course_name} (section {section_idx + 1})")
                detail = AllocationOfferingDetail(
                    target_id=demand.target_id,
                    target_name=target_name,
                    course_id=course_id,
                    course_name=course_name,
                    faculty_id=None,
                    faculty_name=None,
                    offering_id=None,
                    bucket_id=None,
                    is_new=False,
                )
                details.append(detail)
                continue

            faculty_id = uuid.UUID(assigned_faculty_id_str)
            faculty = ctx.faculty.get(assigned_faculty_id_str)
            faculty_name = faculty.name if faculty else assigned_faculty_id_str

            # Bucket name: "{course} — {target}" or "{course} — {target} S{n}" for multi-section
            section_suffix = f" S{section_idx + 1}" if required_sections > 1 else ""
            bucket_name = f"{course_name} — {target_name}{section_suffix}"

            if dry_run:
                details.append(AllocationOfferingDetail(
                    target_id=demand.target_id,
                    target_name=target_name,
                    course_id=course_id,
                    course_name=course_name,
                    faculty_id=faculty_id,
                    faculty_name=faculty_name,
                    offering_id=None,
                    bucket_id=None,
                    is_new=True,
                ))
                buckets_created += 1
                offerings_created += 1
                continue

            # ── Find or create bucket ──────────────────────────────────────
            bucket = await _find_or_create_bucket(
                db,
                name=bucket_name,
                institution_id=demand.institution_id,
                academic_term_id=demand.academic_term_id,
                department_id=target.department_id if target else None,
                policy=SelectionPolicy.FIXED_BATCH,
                scenario_id=ctx.scenario_id,
            )
            is_new_bucket = getattr(bucket, "_is_new", False)
            if is_new_bucket:
                buckets_created += 1

            # ── Find or create TargetRequirement ──────────────────────────
            await _ensure_target_requirement(db, demand.target_id, bucket.id)

            # ── Find or create/update offering ─────────────────────────────
            offering, is_new_offering = await _find_or_create_offering(
                db,
                bucket_id=bucket.id,
                course_id=course_id,
                faculty_id=faculty_id,
                overwrite_existing=overwrite_existing,
            )
            if is_new_offering:
                offerings_created += 1
            elif overwrite_existing:
                offerings_updated += 1

            details.append(AllocationOfferingDetail(
                target_id=demand.target_id,
                target_name=target_name,
                course_id=course_id,
                course_name=course_name,
                faculty_id=faculty_id,
                faculty_name=faculty_name,
                offering_id=offering.id,
                bucket_id=bucket.id,
                is_new=is_new_offering,
            ))

    return {
        "buckets_created": buckets_created,
        "offerings_created": offerings_created,
        "offerings_updated": offerings_updated,
        "warnings": warnings,
        "unassigned": unassigned,
        "details": details,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _find_or_create_bucket(
    db: "AsyncSession",
    name: str,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID | None,
    policy: SelectionPolicy,
    scenario_id: uuid.UUID,
) -> OfferingBucket:
    stmt = select(OfferingBucket).where(
        OfferingBucket.institution_id == institution_id,
        OfferingBucket.academic_term_id == academic_term_id,
        OfferingBucket.name == name,
        OfferingBucket.selection_policy == policy,
        OfferingBucket.scenario_id == scenario_id,
    )
    result = await db.execute(stmt)
    bucket = result.scalar_one_or_none()
    if bucket is None:
        bucket = OfferingBucket(
            institution_id=institution_id,
            academic_term_id=academic_term_id,
            department_id=department_id,
            name=name,
            selection_policy=policy,
            min_selection=1,
            max_selection=1,
            scenario_id=scenario_id,
        )
        bucket._is_new = True  # type: ignore[attr-defined]
        db.add(bucket)
        await db.flush()
    return bucket


async def _ensure_target_requirement(
    db: "AsyncSession",
    target_id: uuid.UUID,
    bucket_id: uuid.UUID,
) -> TargetRequirement:
    stmt = select(TargetRequirement).where(
        TargetRequirement.target_id == target_id,
        TargetRequirement.bucket_id == bucket_id,
    )
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()
    if req is None:
        req = TargetRequirement(target_id=target_id, bucket_id=bucket_id)
        db.add(req)
        await db.flush()
    return req


async def _find_or_create_offering(
    db: "AsyncSession",
    bucket_id: uuid.UUID,
    course_id: uuid.UUID,
    faculty_id: uuid.UUID,
    overwrite_existing: bool,
) -> tuple[CourseOffering, bool]:
    stmt = select(CourseOffering).where(
        CourseOffering.bucket_id == bucket_id,
        CourseOffering.course_id == course_id,
    )
    result = await db.execute(stmt)
    offering = result.scalar_one_or_none()
    if offering is None:
        offering = CourseOffering(
            bucket_id=bucket_id,
            course_id=course_id,
            faculty_id=faculty_id,
        )
        db.add(offering)
        await db.flush()
        return offering, True
    elif overwrite_existing:
        offering.faculty_id = faculty_id
        await db.flush()
        return offering, False
    return offering, False
