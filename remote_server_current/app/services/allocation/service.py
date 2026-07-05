"""
allocation/service.py
=====================
DB-facing orchestrator for the pre-solve allocation phase.

Public functions:
  get_demand()           — list TargetCourseDemand rows
  add_demand()           — create one demand entry
  bulk_add_demand()      — create multiple entries for one target
  delete_demand()        — remove demand entry
  get_allocation_state() — inspect current offering state for a scenario
  run_allocation()       — main entry point: demand → buckets/offerings
  reset_allocation()     — clear auto-created offerings for a scenario
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import (
    CourseOffering,
    OfferingBucket,
    SchedulingTarget,
    TargetCourseDemand,
    TargetRequirement,
)
from app.models.institution import SchedulingMode
from app.schemas.allocation import (
    AllocationOfferingDetail,
    AllocationResult,
    AllocationRunRequest,
    AllocationState,
    AllocationStateOffering,
    TargetCourseDemandBulkCreate,
    TargetCourseDemandCreate,
    TargetCourseDemandResponse,
)

logger = logging.getLogger("allocation.service")



# ---------------------------------------------------------------------------
# Allocation context (read-only, assembled once per run)
# ---------------------------------------------------------------------------


@dataclass
class AllocationContext:
    """
    Read-only context shared across all allocation strategies.
    Populated by run_allocation() before dispatching to strategies.
    """

    db: AsyncSession
    scenario_id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    scheduling_mode: SchedulingMode | None

    # {str(id): ORM obj}
    targets: dict[str, Any] = field(default_factory=dict)
    courses: dict[str, Any] = field(default_factory=dict)
    faculty: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Demand CRUD
# ---------------------------------------------------------------------------


async def get_demand(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    target_id: uuid.UUID | None = None,
) -> list[TargetCourseDemandResponse]:
    stmt = select(TargetCourseDemand).where(
        TargetCourseDemand.institution_id == institution_id,
        TargetCourseDemand.academic_term_id == academic_term_id,
    )
    if target_id is not None:
        stmt = stmt.where(TargetCourseDemand.target_id == target_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [TargetCourseDemandResponse.model_validate(r) for r in rows]


async def add_demand(
    db: AsyncSession,
    payload: TargetCourseDemandCreate,
) -> TargetCourseDemandResponse:
    # Check for duplicate
    stmt = select(TargetCourseDemand).where(
        TargetCourseDemand.target_id == payload.target_id,
        TargetCourseDemand.course_id == payload.course_id,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        # Idempotent: update required_sections if different
        if existing.required_sections != payload.required_sections:
            existing.required_sections = payload.required_sections
            existing.notes = payload.notes
            await db.flush()
        return TargetCourseDemandResponse.model_validate(existing)

    demand = TargetCourseDemand(
        institution_id=payload.institution_id,
        academic_term_id=payload.academic_term_id,
        target_id=payload.target_id,
        course_id=payload.course_id,
        required_sections=payload.required_sections,
        notes=payload.notes,
    )
    db.add(demand)
    await db.flush()
    return TargetCourseDemandResponse.model_validate(demand)


async def bulk_add_demand(
    db: AsyncSession,
    payload: TargetCourseDemandBulkCreate,
) -> list[TargetCourseDemandResponse]:
    results = []
    for course_id in payload.course_ids:
        single = TargetCourseDemandCreate(
            institution_id=payload.institution_id,
            academic_term_id=payload.academic_term_id,
            target_id=payload.target_id,
            course_id=course_id,
            required_sections=payload.required_sections,
            notes=payload.notes,
        )
        results.append(await add_demand(db, single))
    return results


async def delete_demand(db: AsyncSession, demand_id: uuid.UUID) -> None:
    stmt = delete(TargetCourseDemand).where(TargetCourseDemand.id == demand_id)
    await db.execute(stmt)
    await db.flush()


# ---------------------------------------------------------------------------
# Allocation state inspection
# ---------------------------------------------------------------------------


async def get_allocation_state(db: AsyncSession, scenario: Any) -> AllocationState:
    """
    Inspect current offering state for the scenario's term.
    Cross-references target_course_demand with existing CourseOfferings
    to determine how many demands still lack a faculty assignment.
    """
    institution_id = scenario.institution_id
    academic_term_id = scenario.academic_term_id

    # Count demand rows
    demand_stmt = select(TargetCourseDemand).where(
        TargetCourseDemand.institution_id == institution_id,
        TargetCourseDemand.academic_term_id == academic_term_id,
    ).join(
        SchedulingTarget,
        TargetCourseDemand.target_id == SchedulingTarget.id,
    ).where(
        SchedulingTarget.scenario_id == scenario.id,
    )
    demand_result = await db.execute(demand_stmt)
    demands = demand_result.scalars().all()
    demands_total = len(demands)

    # Load all offerings in buckets for this term
    bucket_stmt = select(OfferingBucket).where(
        OfferingBucket.institution_id == institution_id,
        OfferingBucket.academic_term_id == academic_term_id,
        OfferingBucket.scenario_id == scenario.id,
        OfferingBucket.is_active == True,
    )
    bucket_result = await db.execute(bucket_stmt)
    buckets = bucket_result.scalars().all()
    bucket_ids = [b.id for b in buckets]
    bucket_map = {str(b.id): b for b in buckets}

    offerings: list[CourseOffering] = []
    if bucket_ids:
        off_stmt = select(CourseOffering).where(
            CourseOffering.bucket_id.in_(bucket_ids)
        )
        off_result = await db.execute(off_stmt)
        offerings = list(off_result.scalars().all())

    with_faculty = sum(1 for o in offerings if o.faculty_id is not None)
    without_faculty = len(offerings) - with_faculty

    # Build offering details (course/faculty names loaded lazily — we use IDs here)
    offering_details: list[AllocationStateOffering] = []
    for o in offerings:
        bucket = bucket_map.get(str(o.bucket_id))
        offering_details.append(AllocationStateOffering(
            offering_id=o.id,
            course_id=o.course_id,
            course_name=str(o.course_id),   # raw ID — caller resolves names if needed
            faculty_id=o.faculty_id,
            faculty_name=str(o.faculty_id) if o.faculty_id else None,
            bucket_id=o.bucket_id,
            selection_policy=bucket.selection_policy.value if bucket else "UNKNOWN",
        ))

    # Ready when there are offerings AND every offering has a faculty assigned.
    # The old formula (demands_total==0 or without_faculty==0) always returned
    # True for HYBRID/FFCS because no TargetCourseDemand rows are created there,
    # making is_ready_for_solve misleading on empty scenarios.
    is_ready = len(offerings) > 0 and without_faculty == 0

    return AllocationState(
        scenario_id=scenario.id,
        demands_total=demands_total,
        demands_with_faculty=with_faculty,
        demands_without_faculty=without_faculty,
        offerings=offering_details,
        is_ready_for_solve=is_ready,
    )


# ---------------------------------------------------------------------------
# Main allocation runner
# ---------------------------------------------------------------------------


async def run_allocation(
    db: AsyncSession,
    scenario: Any,
    payload: AllocationRunRequest,
) -> AllocationResult:
    """
    Main entry point for the pre-solve allocation phase.

    Steps:
    1. Load target_course_demand rows for institution + academic_term
    2. Load Course, Faculty, SchedulingTarget rows → context
    3. Determine default allocation_mode from institution.scheduling_mode
    4. For per_section mode → run CP-SAT mini-solver
    5. Dispatch to per-mode allocation strategy
    6. Return AllocationResult
    """
    from app.models.course import Course
    from app.models.faculty import Faculty as FacultyProfile
    from app.models.curriculum import SchedulingTarget
    from app.models.institution import Institution

    institution_id = scenario.institution_id
    academic_term_id = scenario.academic_term_id

    # Load institution → scheduling_mode
    inst_result = await db.execute(
        select(Institution).where(Institution.id == institution_id)
    )
    institution = inst_result.scalar_one_or_none()
    scheduling_mode = scenario.scheduling_mode or (institution.scheduling_mode if institution else None)

    # Load all demand rows for this term
    demand_result = await db.execute(
        select(TargetCourseDemand).join(
            SchedulingTarget,
            TargetCourseDemand.target_id == SchedulingTarget.id,
        ).where(
            TargetCourseDemand.institution_id == institution_id,
            TargetCourseDemand.academic_term_id == academic_term_id,
            SchedulingTarget.scenario_id == scenario.id,
        )
    )
    all_demands: list[TargetCourseDemand] = list(demand_result.scalars().all())

    if not all_demands:
        logger.info("No demand rows for institution", institution_id=institution_id, academic_term_id=academic_term_id)
        return AllocationResult(
            demands_processed=0,
            buckets_created=0,
            offerings_created=0,
            offerings_updated=0,
            warnings=["No target_course_demand rows found for this institution/term."],
            unassigned=[],
            details=[],
            is_dry_run=payload.dry_run,
        )

    # Build context: load targets, courses, faculty referenced in demands + assignments
    all_target_ids = list({d.target_id for d in all_demands})
    all_course_ids = list({d.course_id for d in all_demands})
    all_faculty_ids = list({
        fid
        for assignment in payload.assignments
        for fid in assignment.faculty_ids
    })

    targets_result = await db.execute(
        select(SchedulingTarget).where(SchedulingTarget.id.in_(all_target_ids))
    )
    courses_result = await db.execute(
        select(Course).where(Course.id.in_(all_course_ids))
    )
    faculty_result = await db.execute(
        select(FacultyProfile).where(FacultyProfile.id.in_(all_faculty_ids))
    )

    ctx = AllocationContext(
        db=db,
        scenario_id=scenario.id,
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        scheduling_mode=scheduling_mode,
        targets={str(t.id): t for t in targets_result.scalars().all()},
        courses={str(c.id): c for c in courses_result.scalars().all()},
        faculty={str(f.id): f for f in faculty_result.scalars().all()},
    )

    # Index demands by course_id
    demands_by_course: dict[str, list[TargetCourseDemand]] = {}
    for d in all_demands:
        demands_by_course.setdefault(str(d.course_id), []).append(d)

    # Aggregate result counters
    total_buckets_created = 0
    total_offerings_created = 0
    total_offerings_updated = 0
    all_warnings: list[str] = []
    all_unassigned: list[str] = []
    all_details: list[AllocationOfferingDetail] = []
    demands_processed = 0

    # Build assignment index for per_section mode solver output
    # {(target_id, course_id): faculty_id}
    solver_assignments: dict[tuple[str, str], str] = {}

    # Collect per_section demands for the mini-solver
    per_section_assignments = [a for a in payload.assignments
                                if _resolve_mode(a.allocation_mode, scheduling_mode) == "per_section"]
    if per_section_assignments:
        solver_assignments = _run_mini_solver(per_section_assignments, all_demands, ctx)

    # Process each course assignment
    for assignment in payload.assignments:
        course_id = assignment.course_id
        course_id_str = str(course_id)
        demands_for_course = demands_by_course.get(course_id_str, [])

        if not demands_for_course:
            course = ctx.courses.get(course_id_str)
            course_name = course.name if course else course_id_str
            all_warnings.append(
                f"Course {course_name} has no demand rows — skipping."
            )
            continue

        demands_processed += len(demands_for_course)
        mode = _resolve_mode(assignment.allocation_mode, scheduling_mode)

        if mode == "per_section":
            from app.services.allocation.strategies.per_section import allocate_per_section
            result = await allocate_per_section(
                db=db,
                course_id=course_id,
                faculty_assignments=solver_assignments,
                demands_for_course=demands_for_course,
                ctx=ctx,
                overwrite_existing=payload.overwrite_existing,
                dry_run=payload.dry_run,
            )

        elif mode in ("shared_dept", "shared_cross_dept"):
            from app.services.allocation.strategies.shared import allocate_shared
            result = await allocate_shared(
                db=db,
                course_id=course_id,
                faculty_ids=assignment.faculty_ids,
                demands_for_course=demands_for_course,
                ctx=ctx,
                cross_dept=(mode == "shared_cross_dept"),
                overwrite_existing=payload.overwrite_existing,
                dry_run=payload.dry_run,
            )

        elif mode == "open_pool":
            from app.services.allocation.strategies.open_pool import allocate_open_pool
            result = await allocate_open_pool(
                db=db,
                course_id=course_id,
                faculty_ids=assignment.faculty_ids,
                demands_for_course=demands_for_course,
                ctx=ctx,
                overwrite_existing=payload.overwrite_existing,
                dry_run=payload.dry_run,
            )
        else:
            all_warnings.append(f"Unknown allocation_mode={mode!r} for course {course_id_str}")
            continue

        total_buckets_created += result["buckets_created"]
        total_offerings_created += result["offerings_created"]
        total_offerings_updated += result["offerings_updated"]
        all_warnings.extend(result["warnings"])
        all_unassigned.extend(result["unassigned"])
        all_details.extend(result["details"])

    if not payload.dry_run:
        await db.flush()
        logger.info(
            "Allocation complete: buckets_created=%d offerings_created=%d "
            "offerings_updated=%d unassigned=%d",
            total_buckets_created, total_offerings_created,
            total_offerings_updated, len(all_unassigned),
        )

    return AllocationResult(
        demands_processed=demands_processed,
        buckets_created=total_buckets_created,
        offerings_created=total_offerings_created,
        offerings_updated=total_offerings_updated,
        warnings=all_warnings,
        unassigned=all_unassigned,
        details=all_details,
        is_dry_run=payload.dry_run,
    )


# ---------------------------------------------------------------------------
# Reset allocation
# ---------------------------------------------------------------------------


async def reset_allocation(db: AsyncSession, scenario: Any) -> int:
    """
    Clear all CourseOfferings (and orphaned Buckets) that were auto-created
    for this scenario's term.

    Only deletes offerings where faculty_id is set (auto-allocated) and the
    offering has not been manually edited (slot_code is still NULL — solver
    has not run yet).

    Returns count of deleted offerings.
    """
    institution_id = scenario.institution_id
    academic_term_id = scenario.academic_term_id

    # Find all buckets for this term
    bucket_stmt = select(OfferingBucket).where(
        OfferingBucket.institution_id == institution_id,
        OfferingBucket.academic_term_id == academic_term_id,
        OfferingBucket.scenario_id == scenario.id,
    )
    bucket_result = await db.execute(bucket_stmt)
    buckets = bucket_result.scalars().all()
    bucket_ids = [b.id for b in buckets]

    if not bucket_ids:
        return 0

    # Delete offerings where slot_code is NULL (not yet solved — safe to reset)
    off_stmt = select(CourseOffering).where(
        CourseOffering.bucket_id.in_(bucket_ids),
        CourseOffering.slot_code.is_(None),
        CourseOffering.faculty_id.isnot(None),
    )
    off_result = await db.execute(off_stmt)
    offerings = off_result.scalars().all()

    count = len(offerings)
    for offering in offerings:
        await db.delete(offering)
    await db.flush()

    logger.info(
        "Reset allocation: deleted %d offerings for institution=%s term=%s",
        count, institution_id, academic_term_id,
    )
    return count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def _resolve_mode(
    allocation_mode: str | None,
    scheduling_mode: SchedulingMode | None,
) -> str:
    """Derive allocation_mode from institution.scheduling_mode if not explicitly set."""
    if allocation_mode is not None:
        return allocation_mode
    if scheduling_mode is None or scheduling_mode == SchedulingMode.TRADITIONAL:
        return "per_section"
    if scheduling_mode == SchedulingMode.HYBRID:
        return "shared_dept"
    if scheduling_mode == SchedulingMode.FFCS:
        return "open_pool"
    # Unknown modes fall back to per_section
    return "per_section"


def _run_mini_solver(
    per_section_assignments: list,
    all_demands: list[TargetCourseDemand],
    ctx: AllocationContext,
) -> dict[tuple[str, str], str]:
    """
    Build AllocationInput and run the CP-SAT mini-solver for per_section demands.
    Returns {(target_id, course_id): faculty_id}.
    """
    from solver_engine.allocation_optimizer.optimizer import run_allocation_solver
    from solver_engine.allocation_optimizer.contracts import AllocationInput

    course_ids_in_scope = {str(a.course_id) for a in per_section_assignments}
    scoped_demands = [d for d in all_demands if str(d.course_id) in course_ids_in_scope]

    faculty_map: dict[str, list[str]] = {}
    faculty_hours: dict[str, int] = {}
    faculty_current_load: dict[str, int] = {}
    course_weekly_hours: dict[str, int] = {}

    for assignment in per_section_assignments:
        course_id_str = str(assignment.course_id)
        faculty_map[course_id_str] = [str(fid) for fid in assignment.faculty_ids]

        course = ctx.courses.get(course_id_str)
        if course:
            course_weekly_hours[course_id_str] = getattr(course, "weekly_hours", 1) or 1

    for fid_str, faculty in ctx.faculty.items():
        faculty_hours[fid_str] = getattr(faculty, "max_weekly_hours", 0) or 0

    demands_input = [
        (str(d.target_id), str(d.course_id), d.required_sections or 1)
        for d in scoped_demands
    ]

    inp = AllocationInput(
        demands=demands_input,
        faculty_map=faculty_map,
        faculty_hours=faculty_hours,
        faculty_current_load=faculty_current_load,
        course_weekly_hours=course_weekly_hours,
    )

    output = run_allocation_solver(inp)
    return output.assignments
