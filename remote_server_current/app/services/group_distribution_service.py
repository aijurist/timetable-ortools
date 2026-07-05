"""
app/services/group_distribution_service.py
==========================================
DB orchestrator for HYBRID/FFCS group distribution.

Workflow
--------
1. Load cohort + its TargetRequirement rows → bucket_ids
2. Load all CourseOffering rows for those buckets (with Course eager-loaded)
3. If already done and force_rerun=False → return ALREADY_DONE
4. Read HYBRID_DIST (or FFCS_DIST) ScenarioRule.params → resolve dept-level overrides
5. Build OfferingEntry list (with weights, has_lab, co_scheduled_id)
6. Call run_group_optimizer(inp) → GroupOptimizerOutput
7. Write offering.group_number → db.flush() (caller commits)

Manual override
---------------
update_group_assignments() patches specific offering group_numbers directly.

Param resolution (dept-wise overrides)
---------------------------------------
Global params live in ScenarioRule.params at the top level.
Per-dept overrides live under ScenarioRule.params["dept_overrides"][dept_id].
Only fields explicitly listed in the dept override take effect; everything else
inherits from global defaults.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logger import logger
from app.models.curriculum import (
    CourseOffering,
    OfferingBucket,
    SchedulingTarget,
    TargetRequirement,
    TargetType,
)
from app.models.institution import SchedulingMode
from app.services.distribution.contracts import RelaxationHint


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GroupDistributionResult:
    num_groups: int
    target_group_size: int
    status: str  # "OPTIMAL" | "FEASIBLE" | "FALLBACK" | "SKIPPED" | "ALREADY_DONE" | "INFEASIBLE"
    warnings: list[str]
    group_assignments: dict[str, int]  # {offering_id: group_number}
    offerings_updated: int


# ---------------------------------------------------------------------------
# Default optimizer params
# ---------------------------------------------------------------------------

_DEFAULT_PARAMS: dict[str, Any] = {
    "lab_priority": True,
    "consolidation_objective": False,
    "max_groups_per_course": 2,
    "min_groups_per_course": 2,
    "timeout_seconds": 10,
    "fixed_group_assignments": {},
}


_OFFERING_ROOM_FIELDS = (
    "target_room_ids",
    "target_room_ids_soft",
    "target_room_tags",
    "target_room_tags_soft",
    "target_lab_room_ids",
    "target_lab_room_ids_soft",
    "target_lab_room_tags",
    "target_lab_room_tags_soft",
)


def _offering_room_overrides(offering: CourseOffering) -> dict[str, Any]:
    """Non-None room/lab override fields carried back into a rebuilt offering."""
    out: dict[str, Any] = {}
    for f in _OFFERING_ROOM_FIELDS:
        val = getattr(offering, f, None)
        if val is not None:
            out[f] = val
    return out


def _resolve_params(rule_params: dict[str, Any] | None, dept_id: str) -> dict[str, Any]:
    """Merge global defaults → ScenarioRule.params → dept_overrides."""
    base = {**_DEFAULT_PARAMS}
    if rule_params:
        # Apply global rule params (everything except dept_overrides)
        for k, v in rule_params.items():
            if k != "dept_overrides":
                base[k] = v
        # Apply per-dept overrides on top
        dept_overrides: dict[str, Any] = (rule_params.get("dept_overrides") or {}).get(dept_id, {})
        for k, v in dept_overrides.items():
            if k != "dept_overrides":
                base[k] = v
    return base


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


async def run_group_distribution(
    db: AsyncSession,
    cohort_id: uuid.UUID,
    scenario_id: uuid.UUID,
    force_rerun: bool = False,
    params_override: dict[str, Any] | None = None,
    relaxation: "RelaxationHint | None" = None,
) -> GroupDistributionResult:
    """
    Re-run group distribution for one HYBRID/FFCS cohort via the unified engine.

    Reconstructs a DistributionDemand from the cohort's existing offerings and
    rebuilds its group buckets + group_number atomically (reset-then-recreate).

    params_override: applied on top of rule params for this single run only.
    relaxation: optional RelaxationHint (bounded feedback seam) loosening the run.
    Caller must commit the session after a successful return.
    """
    # ── 1. Load cohort ────────────────────────────────────────────────────────
    cohort_result = await db.execute(
        select(SchedulingTarget).where(SchedulingTarget.id == cohort_id)
    )
    cohort = cohort_result.scalar_one_or_none()
    if cohort is None:
        raise NotFoundError(f"SchedulingTarget {cohort_id} not found")
    if cohort.target_type != TargetType.COHORT:
        raise ValidationError(
            f"Target {cohort_id} is type {cohort.target_type!r}; group distribution "
            "only applies to COHORT targets."
        )

    dept_id = str(cohort.department_id) if cohort.department_id else ""

    # ── 2. Load buckets via TargetRequirement ────────────────────────────────
    req_result = await db.execute(
        select(TargetRequirement).where(TargetRequirement.target_id == cohort_id)
    )
    reqs = list(req_result.scalars().all())
    bucket_ids = [r.bucket_id for r in reqs]

    if not bucket_ids:
        return GroupDistributionResult(
            num_groups=0,
            target_group_size=0,
            status="SKIPPED",
            warnings=["No TargetRequirement rows found for this cohort — nothing to distribute."],
            group_assignments={},
            offerings_updated=0,
        )

    # ── 3. Load all CourseOffering rows for those buckets ────────────────────
    offering_result = await db.execute(
        select(CourseOffering).where(CourseOffering.bucket_id.in_(bucket_ids))
    )
    offerings = list(offering_result.scalars().all())

    if not offerings:
        return GroupDistributionResult(
            num_groups=0,
            target_group_size=0,
            status="SKIPPED",
            warnings=["No CourseOffering rows found in this cohort's buckets."],
            group_assignments={},
            offerings_updated=0,
        )

    # ── 4. Short-circuit if already distributed ──────────────────────────────
    if not force_rerun and all(o.group_number is not None for o in offerings):
        done_groups = {str(o.id): o.group_number for o in offerings if o.group_number is not None}
        return GroupDistributionResult(
            num_groups=max(done_groups.values(), default=1),
            target_group_size=0,
            status="ALREADY_DONE",
            warnings=[],
            group_assignments=done_groups,
            offerings_updated=0,
        )

    # ── 5. Resolve scheduling_mode ────────────────────────────────────────────
    from app.models.scenario import Scenario
    from app.models.institution import Institution

    scenario_result = await db.execute(
        select(Scenario).where(Scenario.id == scenario_id)
    )
    scenario = scenario_result.scalar_one_or_none()

    scheduling_mode: SchedulingMode | None = None
    if scenario and scenario.scheduling_mode is not None:
        scheduling_mode = scenario.scheduling_mode
    elif scenario:
        inst_result = await db.execute(
            select(Institution).where(Institution.id == scenario.institution_id)
        )
        inst = inst_result.scalar_one_or_none()
        if inst:
            scheduling_mode = inst.scheduling_mode

    mode_str = scheduling_mode.value if scheduling_mode else "TRADITIONAL"

    if mode_str not in ("HYBRID", "FFCS"):
        return GroupDistributionResult(
            num_groups=1,
            target_group_size=len(offerings),
            status="SKIPPED",
            warnings=[f"Group distribution does not apply to {mode_str} mode."],
            group_assignments={str(o.id): 1 for o in offerings},
            offerings_updated=0,
        )

    # ── 6. Load distribution rule params (dept-aware) ───────────────────────
    from app.models.constraint import ScenarioRule

    dist_codes = {"HYBRID": "HYBRID_DIST", "FFCS": "FFCS_DIST"}
    target_code = dist_codes[mode_str]

    rule_result = await db.execute(
        select(ScenarioRule).where(
            ScenarioRule.scenario_id == scenario_id,
            ScenarioRule.definition_code == target_code,
            ScenarioRule.is_enabled == True,  # noqa: E712
        )
    )
    dist_rule = rule_result.scalar_one_or_none()
    rule_params: dict[str, Any] = (dist_rule.params or {}) if dist_rule else {}

    resolved = _resolve_params(rule_params, dept_id)
    if params_override:
        resolved.update(params_override)
    resolved.pop("dept_overrides", None)

    # ── 7. Reconstruct a DistributionDemand from the existing offerings ─────
    from app.services.distribution import CourseLine, DistributionDemand
    from app.services.distribution.engine import distribute

    inst_id = scenario.institution_id if scenario else cohort.institution_id
    term_id = scenario.academic_term_id if scenario else cohort.academic_term_id
    class_size = next(
        (o.min_capacity for o in offerings if o.min_capacity is not None),
        getattr(cohort, "size", None),
    )

    by_course: dict[uuid.UUID, list[CourseOffering]] = {}
    for o in offerings:
        by_course.setdefault(o.course_id, []).append(o)

    course_lines: list[CourseLine] = []
    for course_uuid, offs in by_course.items():
        teacher_tuples = tuple(
            (
                str(o.faculty_id) if o.faculty_id else "",
                1,
                "frozen" if o.is_frozen else None,
            )
            for o in offs
        )
        ta_overrides = {
            str(o.faculty_id): _offering_room_overrides(o)
            for o in offs
            if o.faculty_id and _offering_room_overrides(o)
        }
        # Carry the semester back so re-distribution re-partitions identically.
        sem_year = next((o.study_year for o in offs if o.study_year is not None), None)
        sem_no = next((o.study_semester for o in offs if o.study_semester is not None), None)
        course_lines.append(CourseLine(
            course_id=str(course_uuid),
            teacher_tuples=teacher_tuples,
            is_cross_dept=False,
            ta_overrides=ta_overrides,
            study_year=sem_year,
            study_semester=sem_no,
        ))

    demand = DistributionDemand(
        cohort_id=str(cohort_id),
        institution_id=str(inst_id),
        academic_term_id=str(term_id),
        department_id=str(cohort.department_id) if cohort.department_id else None,
        scenario_id=str(scenario_id),
        mode=mode_str,
        courses=tuple(course_lines),
        size=getattr(cohort, "size", None),
        class_size=class_size,
        params=resolved,
        cohort_name=cohort.name,
        relaxation=relaxation,
    )

    logger.info(
        "Re-running group distribution via engine",
        cohort_id=str(cohort_id),
        mode=mode_str,
        offerings=len(offerings),
    )

    # full_reset clears all prior buckets/offerings (including solved) so regroup
    # retries and force-rerun cannot accumulate duplicate group buckets.
    dist = await distribute(db, demand, reset_first=True, full_reset=True)

    logger.info(
        "Group distribution complete",
        cohort_id=str(cohort_id),
        status=dist.status,
        num_groups=dist.num_groups,
        warnings=len(dist.warnings),
    )

    return GroupDistributionResult(
        num_groups=dist.num_groups,
        target_group_size=0,
        status=dist.status,
        warnings=dist.warnings,
        group_assignments=dist.group_assignments,
        offerings_updated=dist.offerings_created,
    )


# ---------------------------------------------------------------------------
# Manual override
# ---------------------------------------------------------------------------


async def update_group_assignments(
    db: AsyncSession,
    cohort_id: uuid.UUID,
    overrides: dict[str, int],  # {offering_id: new_group_number}
) -> int:
    """
    Directly patch group_number for specific offerings.
    Validates that new_group_number is in [1..current_max].
    Returns number of rows updated.
    """
    if not overrides:
        return 0

    # Load cohort's bucket_ids
    req_result = await db.execute(
        select(TargetRequirement).where(TargetRequirement.target_id == cohort_id)
    )
    bucket_ids = [r.bucket_id for r in req_result.scalars().all()]

    if not bucket_ids:
        return 0

    offering_result = await db.execute(
        select(CourseOffering).where(CourseOffering.bucket_id.in_(bucket_ids))
    )
    all_offerings = list(offering_result.scalars().all())
    offering_map = {str(o.id): o for o in all_offerings}

    # Determine valid range
    existing_groups = [o.group_number for o in all_offerings if o.group_number is not None]
    max_group = max(existing_groups) if existing_groups else 1

    updated = 0
    for offering_id_str, new_group in overrides.items():
        if new_group < 1 or new_group > max_group:
            raise ValidationError(
                f"group_number {new_group} out of range [1..{max_group}] "
                f"for offering {offering_id_str}"
            )
        offering = offering_map.get(offering_id_str)
        if offering is not None:
            offering.group_number = new_group
            updated += 1

    await db.flush()
    return updated


# ---------------------------------------------------------------------------
# Status query helper
# ---------------------------------------------------------------------------


async def get_group_distribution_status(
    db: AsyncSession,
    cohort_id: uuid.UUID,
) -> dict[str, Any]:
    """
    Lightweight status check without loading full group data.
    Returns: {status, num_groups, offerings_total, offerings_distributed, warnings}
    """
    req_result = await db.execute(
        select(TargetRequirement).where(TargetRequirement.target_id == cohort_id)
    )
    bucket_ids = [r.bucket_id for r in req_result.scalars().all()]

    if not bucket_ids:
        return {"status": "NO_BUCKETS", "num_groups": 0, "offerings_total": 0,
                "offerings_distributed": 0, "warnings": []}

    offering_result = await db.execute(
        select(CourseOffering).where(CourseOffering.bucket_id.in_(bucket_ids))
    )
    offerings = list(offering_result.scalars().all())

    total = len(offerings)
    distributed = sum(1 for o in offerings if o.group_number is not None)
    # group_number restarts per semester, so each distinct BUCKET is one group.
    num_groups = len({o.bucket_id for o in offerings if o.bucket_id is not None})

    if total == 0:
        status = "NO_OFFERINGS"
    elif distributed == 0:
        status = "PENDING"
    elif distributed < total:
        status = "PARTIAL"
    else:
        status = "DONE"

    return {
        "status": status,
        "num_groups": num_groups,
        "offerings_total": total,
        "offerings_distributed": distributed,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Full group view helper
# ---------------------------------------------------------------------------


async def get_group_distribution(
    db: AsyncSession,
    cohort_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """
    Returns per-group offering details for the GroupAssignmentsPanel.

    Output: [
      {
        "group_number": 1,
        "offerings": [
          { "offering_id", "course_code", "course_name", "faculty_id", "has_lab" }
        ]
      }, ...
    ]
    """
    req_result = await db.execute(
        select(TargetRequirement).where(TargetRequirement.target_id == cohort_id)
    )
    bucket_ids = [r.bucket_id for r in req_result.scalars().all()]

    if not bucket_ids:
        return []

    offering_result = await db.execute(
        select(CourseOffering).where(CourseOffering.bucket_id.in_(bucket_ids))
    )
    offerings = list(offering_result.scalars().all())

    # Load buckets — used to expose selection_policy / force_parallel_slots so the
    # UI can flag PE/OE pool groups (CHOOSE_COURSE) distinctly from core groups.
    from app.models.curriculum import OfferingBucket
    bucket_result = await db.execute(
        select(OfferingBucket).where(OfferingBucket.id.in_(bucket_ids))
    )
    buckets_by_id = {str(b.id): b for b in bucket_result.scalars().all()}

    # Load courses
    from app.models.course import Course
    course_ids = list({o.course_id for o in offerings})
    course_result = await db.execute(select(Course).where(Course.id.in_(course_ids)))
    courses_by_id = {str(c.id): c for c in course_result.scalars().all()}

    # Load faculty names
    from app.models.faculty import Faculty
    faculty_ids = list({o.faculty_id for o in offerings if o.faculty_id is not None})
    faculty_by_id: dict[str, Any] = {}
    if faculty_ids:
        fac_result = await db.execute(
            select(Faculty).where(Faculty.id.in_(faculty_ids))
        )
        faculty_by_id = {str(f.id): f for f in fac_result.scalars().all()}

    # Group by (study_semester, group_number) — group_number restarts per
    # semester, so the semester is part of the key. This matches how the solver
    # scopes groups and how the manual override (group_number) reassigns them.
    by_group: dict[tuple[int | None, int], dict[str, Any]] = {}
    unassigned: list[dict[str, Any]] = []

    for o in offerings:
        course = courses_by_id.get(str(o.course_id))
        faculty = faculty_by_id.get(str(o.faculty_id)) if o.faculty_id else None
        structure: dict[str, Any] = (course.structure or {}) if course and hasattr(course, "structure") else {}
        has_lab = bool(structure.get("P", 0))

        entry = {
            "offering_id": str(o.id),
            "course_code": getattr(course, "code", "?") if course else "?",
            "course_name": getattr(course, "name", "?") if course else "?",
            "faculty_id": str(o.faculty_id) if o.faculty_id else None,
            "faculty_name": (
                f"{getattr(faculty, 'first_name', '')} {getattr(faculty, 'last_name', '')}".strip()
                if faculty else "TBA"
            ),
            "has_lab": has_lab,
        }

        bucket = buckets_by_id.get(str(o.bucket_id)) if o.bucket_id else None
        policy = bucket.selection_policy.value if bucket else None
        is_pool = policy == "CHOOSE_COURSE"

        if o.group_number is not None:
            key = (o.study_semester, o.group_number)
            # PE/OE pool groups carry the bucket name (e.g. "… · PE-1"); core
            # groups use the generic "Sem N · Group M" label.
            if is_pool and bucket is not None:
                label = bucket.name
            elif o.study_semester is not None:
                label = f"Sem {o.study_semester} · Group {o.group_number}"
            else:
                label = f"Group {o.group_number}"
            slot = by_group.setdefault(key, {
                "group_number": o.group_number,
                "group_label": label,
                "study_semester": o.study_semester,
                "selection_policy": policy,
                "force_parallel_slots": bool(bucket.force_parallel_slots) if bucket else False,
                "offerings": [],
            })
            slot["offerings"].append(entry)
        else:
            unassigned.append(entry)

    result = [
        {
            "group_number": g["group_number"],
            "group_label": g["group_label"],
            "study_semester": g["study_semester"],
            "selection_policy": g["selection_policy"],
            "force_parallel_slots": g["force_parallel_slots"],
            "offerings": sorted(g["offerings"], key=lambda x: x["course_code"]),
        }
        for g in sorted(
            by_group.values(),
            key=lambda g: (g["study_semester"] or 0, g["group_number"]),
        )
    ]
    if unassigned:
        result.append({
            "group_number": None, "group_label": "Unassigned",
            "study_semester": None, "selection_policy": None,
            "force_parallel_slots": False, "offerings": unassigned,
        })

    return result
