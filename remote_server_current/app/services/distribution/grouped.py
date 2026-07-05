"""
app/services/distribution/grouped.py
====================================
Shared grouped-distribution routine for HYBRID and FFCS.

Both modes run the group_optimizer sub-solver once and create per-group buckets.
The fix vs the legacy inline path: the "Group N" bucket AND
CourseOffering.group_number are written in the SAME transaction, so group identity
is never NULL-then-backfilled.

HYBRID  → CHOOSE_FACULTY buckets, scheduling_mode="HYBRID"
FFCS    → OPEN_POOL buckets,      scheduling_mode="FFCS"
"""
from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.curriculum import SelectionPolicy
from app.services.distribution import persistence
from app.services.distribution.contracts import DistributionDemand, DistributionResult
from solver_engine.group_optimizer.contracts import GroupOptimizerInput, OfferingEntry
from solver_engine.group_optimizer.optimizer import run_group_optimizer

_DEFAULT_PARAMS: dict[str, Any] = {
    "lab_priority": True,
    "consolidation_objective": False,
    "max_groups_per_course": 2,
    "min_groups_per_course": 2,
    "timeout_seconds": 10,
}


def _apply_relaxation(params: dict[str, Any], demand: DistributionDemand) -> dict[str, Any]:
    """Fold a RelaxationHint into optimizer params (no-op when absent)."""
    out = dict(params)
    hint = demand.relaxation
    if hint is None:
        return out
    if hint.bump_max_groups_per_course:
        out["max_groups_per_course"] = int(
            out.get("max_groups_per_course", 2)
        ) + hint.bump_max_groups_per_course
    if hint.relax_group_size_equality:
        # Allow groups to differ in size when the equality constraint is the blocker.
        out["relax_group_size_equality"] = True
    return out


async def build_grouped(
    db: AsyncSession,
    demand: DistributionDemand,
    *,
    scheduling_mode: str,
    selection_policy: SelectionPolicy,
) -> DistributionResult:
    result = DistributionResult()

    if not demand.courses:
        result.warnings.append(
            "No teaching assignments found — no offerings created. "
            "Add faculty assignments in Planning first."
        )
        return result

    # ── Load course metadata for the entries ────────────────────────────────
    course_ids = list({uuid.UUID(c.course_id) for c in demand.courses})
    course_rows = (
        await db.execute(select(Course).where(Course.id.in_(course_ids)))
    ).scalars().all()
    courses_by_id = {str(c.id): c for c in course_rows}

    student_count = int(demand.size or 70)

    cohort_uuid = uuid.UUID(demand.cohort_id)
    inst_uuid = uuid.UUID(demand.institution_id)
    term_uuid = uuid.UUID(demand.academic_term_id)

    params = _apply_relaxation({**_DEFAULT_PARAMS, **(demand.params or {})}, demand)
    dept_uuid = uuid.UUID(demand.department_id) if demand.department_id else None
    scenario_uuid = uuid.UUID(demand.scenario_id) if demand.scenario_id else None
    bucket_prefix = demand.cohort_name or f"Cohort {demand.cohort_id[:8]}"

    # ── Partition courses by (study_year, study_semester) ───────────────────
    # Grouping is per dept/semester: each semester forms its own groups,
    # numbered from 1, with its own non-overlap scope. A cohort with no
    # semester info on its TAs falls into a single (None, None) partition.
    partitions: dict[tuple[int | None, int | None], list[Any]] = defaultdict(list)
    for line in demand.courses:
        partitions[(line.study_year, line.study_semester)].append(line)

    from app.services.student_service import count_students

    statuses: list[str] = []
    for (year, sem), lines in sorted(
        partitions.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0)
    ):
        # Per-semester student headcount from the real student records (auto),
        # so the optimizer weights groups by each semester's actual size rather
        # than a single typed cohort number. Fall back to the cohort size / 70.
        sem_student_count = student_count
        if dept_uuid is not None and sem is not None:
            counted = await count_students(
                db, inst_uuid, department_id=dept_uuid, semester=sem,
            )
            if counted > 0:
                sem_student_count = counted

        # ── Split: core lines vs PE/OE pool lines ───────────────────────────
        # Pool lines bypass the group optimizer and become CHOOSE_COURSE buckets.
        # Pool lines are grouped by pool_id so each pool forms one bucket.
        core_lines: list[Any] = []
        pool_groups: dict[str, list[Any]] = {}  # pool_id → [lines]
        for line in lines:
            if line.elective_pool_id:
                pool_groups.setdefault(line.elective_pool_id, []).append(line)
            else:
                core_lines.append(line)

        # ── Build entries + creation metadata for CORE lines only ───────────
        entries: list[OfferingEntry] = []
        meta: dict[str, dict[str, Any]] = {}
        for line in core_lines:
            course = courses_by_id.get(line.course_id)
            course_code = getattr(course, "code", None) or line.course_id
            structure: dict[str, Any] = getattr(course, "structure", {}) or {}
            has_lab = bool(structure.get("P", 0)) or (
                str(getattr(course, "session_type", "")) == "LAB"
            )
            lecture_hours = int(structure.get("L", getattr(course, "weekly_hours", 1) or 1))
            practical_hours = int(structure.get("P", 0))

            for faculty_id, section_count, pinned_label in line.teacher_tuples:
                for _ in range(max(int(section_count or 1), 1)):
                    temp_id = str(uuid.uuid4())
                    entries.append(OfferingEntry(
                        offering_id=temp_id,
                        course_id=line.course_id,
                        course_code=course_code,
                        faculty_id=str(faculty_id) if faculty_id else "",
                        has_lab=has_lab,
                        lecture_hours=lecture_hours,
                        practical_hours=practical_hours,
                        student_count=sem_student_count,
                    ))
                    meta[temp_id] = {
                        "course_id": uuid.UUID(line.course_id),
                        "faculty_id": uuid.UUID(faculty_id) if faculty_id else None,
                        "is_pinned": bool(pinned_label),
                        "ta_kwargs": line.ta_overrides.get(str(faculty_id), {}) if faculty_id else {},
                    }

        # Skip entire partition only when both core and pool sides are empty.
        if not entries and not pool_groups:
            continue

        # Tracks how many core groups were created this semester so pool group
        # numbers continue from where core left off (keeps the per-semester
        # non-overlap scope consistent).
        core_groups_this_sem = 0

        if entries:
            # NOTE: we deliberately do NOT trim sections here. Every teaching
            # assignment the user created becomes an offering. "max_groups_per_course"
            # is purely the optimizer's span bound (optimizer.py C3: how many distinct
            # groups one course may occupy) — not a cap on how many sections a course
            # may have. If that bound is too tight to place every section cleanly,
            # the optimizer's greedy fallback still round-robins all sections across
            # groups without dropping any.
            opt_inp = GroupOptimizerInput(
                offerings=entries,
                dept_id=str(demand.department_id or ""),
                scheduling_mode=scheduling_mode,
                lab_priority=bool(params.get("lab_priority", True)),
                consolidation_objective=bool(params.get("consolidation_objective", False)),
                max_groups_per_course=int(params.get("max_groups_per_course", 2)),
                min_groups_per_course=int(params.get("min_groups_per_course", 2)),
                timeout_seconds=int(params.get("timeout_seconds", 10)),
                fixed_group_assignments={
                    str(k): {int(gi): int(cnt) for gi, cnt in v.items()}
                    for k, v in (params.get("fixed_group_assignments") or {}).items()
                },
            )
            # Run CP-SAT off the event loop (OR-Tools releases the GIL) so the API
            # stays responsive while the solver runs.
            opt_out = await asyncio.to_thread(run_group_optimizer, opt_inp)
            statuses.append(opt_out.status)
            result.warnings.extend(opt_out.warnings)

            if opt_out.num_groups > 0:
                core_groups_this_sem = opt_out.num_groups
                result.num_groups += opt_out.num_groups

                # One bucket per group within this semester; group_number restarts at 1.
                sem_part = f" · Sem {sem}" if sem is not None else ""
                group_buckets: dict[int, uuid.UUID] = {}
                for g in range(1, opt_out.num_groups + 1):
                    # Always create a fresh bucket — group buckets are owned by exactly
                    # one cohort and must never be shared by name across cohorts.
                    bucket = await persistence.create_bucket(
                        db,
                        institution_id=inst_uuid,
                        academic_term_id=term_uuid,
                        department_id=dept_uuid,
                        name=f"{bucket_prefix}{sem_part} · Group {g}",
                        selection_policy=selection_policy,
                        scenario_id=scenario_uuid,
                        min_selection=1,
                        max_selection=1,
                    )
                    group_buckets[g] = bucket.id
                    result.buckets_created += 1
                    await persistence.ensure_target_requirement(
                        db, target_id=cohort_uuid, bucket_id=bucket.id
                    )

                for entry in entries:
                    group_num = opt_out.group_assignments.get(entry.offering_id, 1)
                    bucket_id = group_buckets.get(group_num)
                    m = meta[entry.offering_id]
                    offering = await persistence.create_offering(
                        db,
                        bucket_id=bucket_id,
                        course_id=m["course_id"],
                        faculty_id=m["faculty_id"],
                        min_capacity=demand.class_size,
                        is_frozen=m["is_pinned"],
                        group_number=group_num,
                        study_year=year,
                        study_semester=sem,
                        ta_kwargs=m["ta_kwargs"],
                    )
                    result.offerings_created += 1
                    result.group_assignments[str(offering.id)] = group_num
                    if m["faculty_id"] is None:
                        result.tba_created += 1

        # ── PE / OE pools — each pool → one CHOOSE_COURSE bucket ────────────
        # Runs regardless of whether core entries existed or the optimizer succeeded.
        # force_parallel_slots=True: all PE/OE options in one pool share the same
        # timeslot so students can pick exactly one.
        for pool_ordinal, (pool_id, pool_lines) in enumerate(
            sorted(pool_groups.items()), start=core_groups_this_sem + 1
        ):
            pool_label = pool_lines[0].elective_pool_label or f"Pool {pool_ordinal}"
            sem_part = f" · Sem {sem}" if sem is not None else ""

            pe_bucket = await persistence.create_bucket(
                db,
                institution_id=inst_uuid,
                academic_term_id=term_uuid,
                department_id=dept_uuid,
                name=f"{bucket_prefix}{sem_part} · {pool_label}",
                selection_policy=SelectionPolicy.CHOOSE_COURSE,
                scenario_id=scenario_uuid,
                min_selection=1,
                max_selection=1,
                force_parallel_slots=True,
            )
            result.buckets_created += 1
            result.num_groups += 1
            pool_group_number = pool_ordinal
            await persistence.ensure_target_requirement(
                db, target_id=cohort_uuid, bucket_id=pe_bucket.id
            )

            for line in pool_lines:
                course = courses_by_id.get(line.course_id)
                for faculty_id, section_count, pinned_label in line.teacher_tuples:
                    n_sections = max(int(section_count or 1), 1)
                    # If section_count > 1 in a PE pool, the sections are merged
                    # (one teacher, same timeslot). Create one offering with
                    # combined capacity so the solver assigns one big room.
                    if n_sections > 1:
                        # Merged: 1 offering covering all sections
                        combined_capacity = (demand.class_size or 70) * n_sections
                        offering = await persistence.create_offering(
                            db,
                            bucket_id=pe_bucket.id,
                            course_id=uuid.UUID(line.course_id),
                            faculty_id=uuid.UUID(faculty_id) if faculty_id else None,
                            min_capacity=combined_capacity,
                            is_frozen=bool(pinned_label),
                            group_number=pool_group_number,
                            study_year=year,
                            study_semester=sem,
                            ta_kwargs=line.ta_overrides.get(str(faculty_id), {}) if faculty_id else {},
                        )
                        result.offerings_created += 1
                        result.group_assignments[str(offering.id)] = pool_group_number
                        if not faculty_id:
                            result.tba_created += 1
                    else:
                        # Normal single section — one offering per section
                        offering = await persistence.create_offering(
                            db,
                            bucket_id=pe_bucket.id,
                            course_id=uuid.UUID(line.course_id),
                            faculty_id=uuid.UUID(faculty_id) if faculty_id else None,
                            min_capacity=demand.class_size,
                            is_frozen=bool(pinned_label),
                            group_number=pool_group_number,
                            study_year=year,
                            study_semester=sem,
                            ta_kwargs=line.ta_overrides.get(str(faculty_id), {}) if faculty_id else {},
                        )
                        result.offerings_created += 1
                        result.group_assignments[str(offering.id)] = pool_group_number
                        if not faculty_id:
                            result.tba_created += 1

    # Worst status wins for the overall result.
    if "INFEASIBLE" in statuses:
        result.status = "INFEASIBLE"
    elif "FALLBACK" in statuses:
        result.status = "FALLBACK"
    elif statuses:
        result.status = "FEASIBLE" if "FEASIBLE" in statuses else statuses[0]

    return result
