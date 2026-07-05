"""
app/services/cohort_service.py
================================
COHORT orchestrator: atomic setup of targets + demands + buckets + offerings.

Called by curriculum_service.create_target() when target_type=COHORT.
Thin orchestrator — flattens the cohort's teaching demand into a
DistributionDemand and hands it to the unified distribution engine, which owns
the mode-specific data-model shape (BATCH children / group buckets / offerings).

setup_cohort() steps:
  1. Validate: size + department_id required
  2. Load Department + Institution → resolve class_size + class_count + mode
  3. Create COHORT SchedulingTarget
  4. Load active TeachingAssignment rows for this dept+term
  5. Query CourseShareConfig per course → is_cross_dept flag
  6. Build DistributionDemand → distribution.engine.distribute()
  7. Return CohortSetupResponse
"""
from __future__ import annotations

import math
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.logger import logger
from app.models.curriculum import (
    CourseShareConfig,
    SchedulingTarget,
    TargetType,
)
from app.models.institution import SchedulingMode
from app.schemas.curriculum import (
    CohortSetupResponse,
    SchedulingTargetCreate,
    SchedulingTargetResponse,
)
from app.services.curriculum_service import _resolve_class_size
from app.services.distribution_rule_resolver import resolve_distribution_rule

_TA_OFFERING_FIELDS = (
    "target_room_ids",
    "target_room_ids_soft",
    "target_room_tags",
    "target_room_tags_soft",
    "target_lab_room_ids",
    "target_lab_room_ids_soft",
    "target_lab_room_tags",
    "target_lab_room_tags_soft",
)


def _ta_kwargs(
    overrides: dict[Any, Any] | None,
    course_id: uuid.UUID,
    faculty_id: uuid.UUID | None,
) -> dict[str, Any]:
    """CourseOffering kwargs from a TeachingAssignment's room/lab overrides."""
    if not overrides:
        return {}
    row = (overrides.get(course_id, {}) or {}).get(faculty_id)
    if not row:
        return {}
    return {f: row[f] for f in _TA_OFFERING_FIELDS if row.get(f) is not None}


async def setup_cohort(
    db: AsyncSession,
    payload: SchedulingTargetCreate,
) -> CohortSetupResponse:
    """
    Atomic COHORT creation.

    Reads TeachingAssignment rows for dept+term, creates targets + demands +
    buckets + offerings in a single transaction (caller commits).
    """
    # ── 1. Validate required fields ─────────────────────────────────────────
    if payload.department_id is None:
        raise ValidationError("COHORT requires 'department_id'")

    # ── 1b. Reject duplicate cohort for the same (dept + semester + term + scenario) ─
    # Each (department, study_semester) pair may have at most one COHORT.
    # NULL study_semester = "all semesters" and collides only with other NULL-semester cohorts.
    dup_stmt = select(SchedulingTarget).where(
        SchedulingTarget.target_type == TargetType.COHORT,
        SchedulingTarget.institution_id == payload.institution_id,
        SchedulingTarget.academic_term_id == payload.academic_term_id,
        SchedulingTarget.department_id == payload.department_id,
        SchedulingTarget.scenario_id == payload.scenario_id,
        (
            SchedulingTarget.study_semester == payload.study_semester
            if payload.study_semester is not None
            else SchedulingTarget.study_semester.is_(None)
        ),
    )
    if (await db.execute(dup_stmt)).scalar_one_or_none() is not None:
        sem_label = f" Semester {payload.study_semester}" if payload.study_semester else ""
        raise ValidationError(
            f"A cohort already exists for this department{sem_label} in this scenario. "
            "Delete it, or re-distribute it from the Groups tab, instead of creating a second one."
        )

    # ── 2. Load Department + Institution ────────────────────────────────────
    from app.models.institution import Department, Institution

    dept_result = await db.execute(
        select(Department).where(Department.id == payload.department_id)
    )
    dept = dept_result.scalar_one_or_none()

    inst_result = await db.execute(
        select(Institution).where(Institution.id == payload.institution_id)
    )
    institution = inst_result.scalar_one_or_none()

    # Resolve scheduling_mode: payload (scenario-level) > institution-level
    if payload.scheduling_mode is not None:
        try:
            scheduling_mode: SchedulingMode | None = SchedulingMode(payload.scheduling_mode.upper())
        except ValueError:
            scheduling_mode = institution.scheduling_mode if institution else None
    else:
        scheduling_mode = institution.scheduling_mode if institution else None

    # ── 3. Resolve class_count + class_size (TRADITIONAL only) ──────────────
    class_size: Optional[int] = _resolve_class_size(dept, institution)

    class_count: Optional[int] = payload.class_count
    if class_count is None and class_size is not None and payload.size is not None:
        class_count = math.ceil(payload.size / class_size)

    dept_code = getattr(dept, "code", "DEPT") if dept else "DEPT"

    # ── 4. Create COHORT target ─────────────────────────────────────────────
    cohort_data = payload.model_dump(exclude={"scheduling_mode"})
    cohort_data["class_count"] = class_count
    cohort = SchedulingTarget(**cohort_data)
    db.add(cohort)
    await db.flush()
    logger.info(
        "COHORT target created",
        cohort_id=str(cohort.id),
        name=cohort.name,
        class_count=class_count,
    )
    import app.services.audit_log_service as audit_svc
    from app.models.audit_log import AuditAction
    await audit_svc.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="Cohort",
        entity_id=cohort.id,
        entity_label=cohort.name,
        institution_id=payload.institution_id,
        after={
            "class_count": class_count,
            "size": payload.size,
            "department_id": str(payload.department_id),
            "academic_term_id": str(payload.academic_term_id),
        },
    )

    # ── 5. Load TeachingAssignment rows for this dept+term ──────────────────
    from app.models.curriculum import TeachingAssignment

    ta_filters = [
        TeachingAssignment.institution_id == payload.institution_id,
        TeachingAssignment.academic_term_id == payload.academic_term_id,
        TeachingAssignment.department_id == payload.department_id,
        TeachingAssignment.is_active == True,  # noqa: E712
    ]
    # When a specific semester is requested, restrict to TAs for that semester.
    # TAs with study_semester=NULL are included only when no filter is specified.
    if payload.study_semester is not None:
        ta_filters.append(TeachingAssignment.study_semester == payload.study_semester)

    ta_result = await db.execute(select(TeachingAssignment).where(*ta_filters))
    ta_rows = list(ta_result.scalars().all())

    all_course_ids: list[uuid.UUID] = list({r.course_id for r in ta_rows})
    warnings: list[str] = []

    if not ta_rows:
        warnings.append(
            "No teaching assignments found for this dept+term — "
            "all offerings will be TBA placeholders"
        )

    # ── 6. Group TeachingAssignments by (course_id, elective_pool_id) ─────────
    # Pool TAs are kept separate from core TAs so the distribution engine can
    # create per-pool CHOOSE_COURSE buckets instead of running the group optimizer.
    # {course_id: [(faculty_id, section_count, pinned_label)]}
    by_course: dict[uuid.UUID, list[tuple[uuid.UUID | None, int, Optional[str]]]] = {}
    # {course_id: {faculty_id: overrides_dict}} — room/lab overrides from TA
    ta_overrides: dict[uuid.UUID, dict[uuid.UUID | None, dict[str, Any]]] = {}
    # {course_id: (study_year, study_semester)} — for per-semester grouping
    course_sem: dict[uuid.UUID, tuple[int | None, int | None]] = {}
    # {course_id: (pool_id_str, pool_label, is_oe)} — for PE/OE lines
    course_pool: dict[uuid.UUID, tuple[str | None, str | None, bool]] = {}

    # Pre-load pool labels for all referenced pool IDs
    pool_ids_seen = {r.elective_pool_id for r in ta_rows if getattr(r, "elective_pool_id", None)}
    pool_label_map: dict[str, tuple[str, bool]] = {}  # pool_id → (label, is_oe)
    if pool_ids_seen:
        from app.models.elective_pool import ElectivePool
        from app.models.course import ElectiveType as _ET
        pl_result = await db.execute(
            select(ElectivePool).where(ElectivePool.id.in_(pool_ids_seen))
        )
        for p in pl_result.scalars().all():
            pool_label_map[str(p.id)] = (
                p.label,
                p.elective_type == _ET.OPEN,
            )

    for r in ta_rows:
        by_course.setdefault(r.course_id, []).append(
            (r.faculty_id, r.section_count, r.pinned_section_label)
        )
        if r.course_id not in course_sem or course_sem[r.course_id] == (None, None):
            course_sem[r.course_id] = (
                getattr(r, "study_year", None),
                getattr(r, "study_semester", None),
            )
        overrides = {
            "target_room_ids": r.override_room_ids,
            "target_room_ids_soft": r.override_room_ids_soft,
            "target_room_tags": getattr(r, "override_room_tags", None),
            "target_room_tags_soft": getattr(r, "override_room_tags_soft", None),
            "target_lab_room_ids": r.override_lab_room_ids,
            "target_lab_room_ids_soft": r.override_lab_room_ids_soft,
            "target_lab_room_tags": getattr(r, "override_lab_room_tags", None),
            "target_lab_room_tags_soft": getattr(r, "override_lab_room_tags_soft", None),
        }
        ta_overrides.setdefault(r.course_id, {})[r.faculty_id] = overrides
        pool_id = getattr(r, "elective_pool_id", None)
        if pool_id and r.course_id not in course_pool:
            label, is_oe = pool_label_map.get(str(pool_id), ("PE", False))
            course_pool[r.course_id] = (str(pool_id), label, is_oe)

    # ── 7. Query CourseShareConfig per course ───────────────────────────────
    is_cross_dept: dict[uuid.UUID, bool] = {}
    if all_course_ids:
        cfg_result = await db.execute(
            select(CourseShareConfig).where(
                CourseShareConfig.academic_term_id == payload.academic_term_id,
                CourseShareConfig.course_id.in_(all_course_ids),
            )
        )
        for cfg in cfg_result.scalars().all():
            dept_in_list = (
                cfg.department_ids is None  # null = all depts
                or str(payload.department_id) in [str(d) for d in (cfg.department_ids or [])]
            )
            is_cross_dept[cfg.course_id] = dept_in_list

    # ── Load distribution rules for this scenario ────────────────────────────
    dist_rules: list[Any] = []
    equal_section_distribution: bool = False
    if payload.scenario_id is not None:
        from app.models.constraint import ScenarioRule, RuleType  # noqa: PLC0415
        dr_result = await db.execute(
            select(ScenarioRule).where(
                ScenarioRule.scenario_id == payload.scenario_id,
                ScenarioRule.is_enabled == True,  # noqa: E712
            )
        )
        all_rules = list(dr_result.scalars().all())
        dist_rules = [r for r in all_rules if getattr(r, "rule_type", None) == RuleType.DISTRIBUTION]
        equal_section_distribution = any(
            getattr(r, "definition_code", None) == "EQUAL_SECTION_DISTRIBUTION"
            for r in all_rules
        )

    # Resolve base distribution rule (needed for its optimizer params).
    base_rule = resolve_distribution_rule("__base__", dist_rules)

    # Load scenario.scheduling_mode as the authoritative mode signal.
    # The seeded DIST rule can drift out of sync with the scenario mode (e.g., a
    # creation-time bug seeded TRADITIONAL_DIST on a HYBRID scenario).
    scenario_mode: SchedulingMode | None = None
    if payload.scenario_id is not None:
        from app.models.scenario import Scenario as _Scenario  # noqa: PLC0415
        _scen_res = await db.execute(
            select(_Scenario).where(_Scenario.id == payload.scenario_id)
        )
        _scen = _scen_res.scalar_one_or_none()
        if _scen is not None:
            scenario_mode = _scen.scheduling_mode

    # Effective mode: scenario.scheduling_mode > payload > institution default.
    effective_mode = scenario_mode or scheduling_mode

    # Determine is_traditional from effective_mode, not from the seeded rule.
    is_traditional = effective_mode in (SchedulingMode.TRADITIONAL, None)

    # ── 8a. Apply EQUAL_SECTION_DISTRIBUTION balancing if enabled ───────────
    # Caps each faculty's section count so load is spread evenly across
    # teachers (mirrors the old _run_inline_allocation behaviour).
    if equal_section_distribution:
        for _cid, _tuples in by_course.items():
            _n = len(_tuples)
            if _n > 1:
                _denom = class_count or _n
                _max = math.ceil(_denom / _n)
                by_course[_cid] = [
                    (fid, min(_max, sc or 1), pl)
                    for fid, sc, pl in _tuples
                ]

    if payload.size is None:
        raise ValidationError(
            "COHORT requires 'size' (total number of students) — "
            "used for group sizing and class-count derivation."
        )
    if is_traditional and class_count is None:
        raise ValidationError(
            "Cannot derive class_count: provide 'class_count' explicitly, "
            "or set department.class_size / institution.default_class_size"
        )

    # ── 8. Resolve optimizer params (HYBRID/FFCS *_DIST rule) ───────────────
    dist_params: dict[str, Any] = {}
    _base_params = getattr(base_rule, "params", None) if base_rule is not None else None
    if _base_params:
        dist_params = {
            k: v for k, v in _base_params.items() if k != "dept_overrides"
        }

    # ── 9. Build DistributionDemand + run the unified engine ────────────────
    from app.services.distribution import CourseLine, DistributionDemand
    from app.services.distribution.engine import distribute

    mode_str = (
        "TRADITIONAL" if is_traditional
        else (effective_mode.value.upper() if effective_mode else "HYBRID")
    )
    course_lines = tuple(
        CourseLine(
            course_id=str(course_id),
            teacher_tuples=tuple(
                (str(fid) if fid else "", int(sc or 1), pl)
                for (fid, sc, pl) in tuples
            ),
            is_cross_dept=is_cross_dept.get(course_id, False),
            ta_overrides={
                str(fid): _ta_kwargs(ta_overrides, course_id, fid)
                for (fid, _sc, _pl) in tuples
                if fid
            },
            study_year=course_sem.get(course_id, (None, None))[0],
            study_semester=course_sem.get(course_id, (None, None))[1],
            elective_pool_id=course_pool.get(course_id, (None, None, False))[0],
            elective_pool_label=course_pool.get(course_id, (None, None, False))[1],
            is_open_elective=course_pool.get(course_id, (None, None, False))[2],
        )
        for course_id, tuples in by_course.items()
    )
    demand = DistributionDemand(
        cohort_id=str(cohort.id),
        institution_id=str(payload.institution_id),
        academic_term_id=str(payload.academic_term_id),
        department_id=str(payload.department_id) if payload.department_id else None,
        scenario_id=str(payload.scenario_id) if payload.scenario_id else None,
        mode=mode_str,
        courses=course_lines,
        size=payload.size,
        class_size=class_size,
        class_count=class_count,
        params=dist_params,
        cohort_name=cohort.name,
        dept_code=dept_code,
        cohort_extra_data=payload.extra_data or {},
    )

    dist = await distribute(db, demand)
    warnings.extend(dist.warnings)

    # Load any BATCH children the strategy created (TRADITIONAL only).
    children_result = await db.execute(
        select(SchedulingTarget).where(SchedulingTarget.parent_id == cohort.id)
    )
    children = list(children_result.scalars().all())

    tba_created = dist.tba_created
    is_ready = tba_created == 0

    logger.info(
        "COHORT setup complete",
        cohort_id=str(cohort.id),
        class_count=class_count,
        children=len(children),
        demands=dist.demands_created,
        buckets=dist.buckets_created,
        offerings=dist.offerings_created,
        tba=tba_created,
    )

    return CohortSetupResponse(
        cohort=SchedulingTargetResponse.model_validate(cohort),
        children=[SchedulingTargetResponse.model_validate(c) for c in children],
        demands_created=dist.demands_created,
        buckets_created=dist.buckets_created,
        offerings_created=dist.offerings_created,
        tba_offerings_created=tba_created,
        class_size_used=class_size,
        class_count=class_count or 0,
        required_slots=class_count or 0,
        scheduling_mode=scheduling_mode.value if scheduling_mode else "TRADITIONAL",
        is_ready_for_solve=is_ready,
        warnings=warnings,
        group_distribution_pending=False,
    )
