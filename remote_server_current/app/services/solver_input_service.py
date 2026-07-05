"""
app/services/solver_input_service.py
=====================================
Mode-awareness hub — the ONLY place that reads DB data and assembles SchedulerInput.

Reads:
  1. Scenario + Institution → scheduling mode, solver_config
  2. TimeGrid → slot dictionary
  3. SchedulingTarget + TargetRequirement → demand matrix
  4. OfferingBucket + CourseOffering → supply matrix (eager loaded)
  5. Course → weekly_hours, session_type
  6. Faculty → max_weekly_hours, availability_blacklist, preferences
  7. Room  → capacity, room_type, tags
  8. ScenarioRule (is_enabled=True) → active rules
  9. Department → working_days (per-dept day restrictions)

Returns a SchedulerInput ready for PipelineOrchestrator.run().
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from solver_engine.contracts import (
    DepartmentData,
    FacultyData,
    PinnedAssignment,
    RoomData,
    RuleData,
    SchedulerInput,
    SessionData,
    SlotData,
    SlotPatternDef,
    SolverConfig,
)
from solver_engine.config.defaults import MODE_SOLVER_CONFIG_OVERRIDES

from app.models.scenario import Scenario
from app.models.institution import Institution
from app.models.curriculum import OfferingBucket, SchedulingTarget, SelectionPolicy
from app.models.constraint import ScenarioRule
from app.services.assembly.base import AssemblyContext
from app.services.assembly.registry import get_assembly_registry
import solver_engine.constraints.policy_routing  # noqa: F401 — future extensibility

logger = logging.getLogger("app.solver_input_service")


# Physics constraints auto-injected for every solve
PHYSICS_CONSTRAINT_CODES = [
    "SESSION_COVERAGE",
    "ROOM_NO_DOUBLE_BOOK",
    "TEACHER_NO_DOUBLE_BOOK",
    "GROUP_NO_DOUBLE_BOOK",
    "ROOM_CAPACITY",
    "ROOM_TYPE",
    "SLOT_OVERRIDE",
]



async def assemble_input(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    warm_start: bool = True,
    honor_pins: bool = True,
    soft_pins: bool = False,
    extra_pins: list[PinnedAssignment] | None = None,
) -> SchedulerInput:
    """
    Assemble a complete SchedulerInput from DB data for one scenario.

    Entry point called by the Celery task adapter.
    """
    # ── Load scenario + institution ───────────────────────────────────────────
    scenario = await _load_scenario(db, scenario_id)
    institution = await _load_institution(db, scenario.institution_id)

    # ── Load common data ──────────────────────────────────────────────────────
    slots = await _load_slots(db, scenario)
    rooms_data = await _load_rooms(db, scenario, institution)
    faculty_data = await _load_faculty(db, scenario, institution)
    departments_data = await _load_departments(db, scenario)
    (
        rules,
        disabled_constraint_codes,
        disabled_pruning_layers,
        disabled_per_entity,
        per_entity_cp_sat_rules,
        slot_pattern_rules,
    ) = await _load_rules(db, scenario)
    warm_hints = _load_warm_start_hints(scenario) if warm_start else {}
    solver_cfg = _merge_solver_config(institution, scenario, warm_start_hints=warm_hints)

    # ── Load curriculum data ──────────────────────────────────────────────────
    buckets = await _load_buckets_with_offerings(db, scenario)
    courses = await _load_courses(db, scenario, institution)
    teaching_assignments = await _load_teaching_assignments(db, scenario)
    targets, reqs_by_bucket = await _load_targets_with_requirements(db, scenario)
    dept_working_days = await _load_department_working_days(db, scenario)

    # slot_pattern_rules already extracted from SLOT_PATTERN_LOCK distribution rules
    # in _load_rules() — passed as 6th tuple element above

    # Build a flat requirements list for AssemblyContext backward compat
    requirements = [req for reqs in reqs_by_bucket.values() for req in reqs]

    ctx = AssemblyContext(
        targets=targets,
        requirements=requirements,
        courses=courses,
        teaching_assignments=teaching_assignments,
        dept_working_days=dept_working_days,
        slots=slots,
        rooms=rooms_data,
        reqs_by_bucket=reqs_by_bucket,
        slot_pattern_rules=slot_pattern_rules,
    )

    # ── Modular dispatch — one bucket → one assembler ─────────────────────────
    from solver_engine.contracts import GroupData, ParallelGroupData, SessionData
    all_sessions: list[SessionData] = []
    all_groups: list[GroupData] = []
    all_parallel_groups: list[ParallelGroupData] = []

    registry = get_assembly_registry()

    for bucket in buckets:
        policy = bucket.selection_policy
        strategy = registry.get(policy)
        if strategy is None:
            logger.warning(
                "No assembler for selection_policy",
                extra={"policy": str(policy), "bucket_id": str(bucket.id)},
            )
            continue

        result = strategy.assemble(bucket, ctx)
        all_sessions.extend(result.sessions)
        all_groups.extend(result.groups)
        all_parallel_groups.extend(result.parallel_groups)

    # ── HYBRID: rebuild GroupData per (cohort, semester, group) ───────────────
    # Grouping is scoped per dept/semester: each (cohort, study_semester) is its
    # own non-overlap scope, and group_number restarts at 1 within it. So Sem 3's
    # groups and Sem 5's groups are independent — group_non_overlap only forces
    # disjoint timeslots among groups of the SAME (cohort, semester).
    # Only runs if at least one offering has a group_number set.
    from app.models.institution import SchedulingMode as _SM
    if getattr(scenario, "scheduling_mode", None) == _SM.HYBRID or (
        institution and getattr(institution, "scheduling_mode", None) == _SM.HYBRID
    ):
        # offering_id → group_number, semester key, owning cohort id
        offering_group: dict[str, int] = {}
        offering_scope: dict[str, str] = {}  # offering_id → "cohort__sem" scope key

        for bucket in buckets:
            bucket_id_str = str(bucket.id)
            cohort_reqs = reqs_by_bucket.get(bucket_id_str, [])
            cohort_id_str = str(cohort_reqs[0].target_id) if cohort_reqs else ""

            for offering in getattr(bucket, "offerings", []):
                oid = str(offering.id)
                if offering.group_number is None or not cohort_id_str:
                    continue
                offering_group[oid] = offering.group_number
                yr = getattr(offering, "study_year", None)
                sem = getattr(offering, "study_semester", None)
                offering_scope[oid] = f"cohort_{cohort_id_str}_y{yr}_s{sem}"

        if offering_group:
            # Group session_keys by (scope_key, group_number)
            by_scope_group: dict[tuple[str, int], list[str]] = {}
            for session in all_sessions:
                oid = session.offering_id
                gn = offering_group.get(oid)
                scope = offering_scope.get(oid, "")
                if gn is not None and scope:
                    by_scope_group.setdefault((scope, gn), []).append(session.session_key)

            if by_scope_group:
                all_groups = [
                    GroupData(
                        group_id=f"{scope}_g{gn}",
                        member_session_keys=keys,
                        scope_key=scope,
                    )
                    for (scope, gn), keys in sorted(by_scope_group.items())
                ]
                logger.info(
                    "HYBRID GroupData rebuilt per (cohort, semester, group)",
                    extra={
                        "scenario_id": str(scenario_id),
                        "hybrid_groups": len(all_groups),
                    },
                )

    # ── Defensive guard: nothing to schedule ─────────────────────────────────
    # The /solve route blocks this earlier with a 409; this catches any other
    # caller (e.g. a re-solve after cohorts were deleted) with a clear message
    # instead of handing the solver an empty model.
    if not all_sessions:
        raise ValueError(
            "No sessions to schedule for this scenario — set up and distribute "
            "cohorts before solving."
        )

    # ── Inject physics rules + mode-aware rules ───────────────────────────────
    rules = _inject_physics_rules(rules)
    rules = _inject_slot_pattern_assign(rules, all_sessions)
    rules = _inject_ffcs_slot_bundle(rules, all_sessions)
    rules = _inject_slot_type(rules, slots)

    # Build slot_patterns from time grid for SLOT_PATTERN_ASSIGN constraint
    slot_patterns = _build_slot_patterns(slots)

    logger.info(
        "SchedulerInput assembled",
        extra={
            "scenario_id": str(scenario_id),
            "sessions": len(all_sessions),
            "groups": len(all_groups),
            "rooms": len(rooms_data),
            "faculty": len(faculty_data),
            "slots": len(slots),
            "rules": len(rules),
        },
    )

    # ── Load pinned assignments ───────────────────────────────────────────────
    pinned: list[PinnedAssignment] = []
    if honor_pins:
        from app.services.schedule_service import get_pinned_sessions
        for row in await get_pinned_sessions(db, scenario_id):
            pinned.append(PinnedAssignment(
                session_key=row.session_id,
                room_id=row.room_id,
                slot_code=row.slot_code,
                soft=soft_pins,
            ))
    if extra_pins:
        pinned.extend(extra_pins)

    # Convert slots dict to SlotData objects
    slot_data_dict = _build_slot_data(slots)

    return SchedulerInput(
        scenario_id=str(scenario_id),
        solver_cfg=solver_cfg,
        sessions=all_sessions,
        rooms=rooms_data,
        faculty=faculty_data,
        departments=departments_data,
        slots=slot_data_dict,
        groups=all_groups,
        parallel_groups=all_parallel_groups,
        rules=rules,
        disabled_constraint_codes=disabled_constraint_codes,
        disabled_pruning_layers=disabled_pruning_layers,
        per_entity_disabled=disabled_per_entity,
        per_entity_rule_data=per_entity_cp_sat_rules,
        pinned_assignments=pinned,
        slot_patterns=slot_patterns,
    )


# ─── Loaders ──────────────────────────────────────────────────────────────────

async def _load_scenario(db: AsyncSession, scenario_id: uuid.UUID) -> Scenario:
    result = await db.execute(
        select(Scenario).where(Scenario.id == scenario_id)
    )
    scenario = result.scalar_one_or_none()
    if scenario is None:
        raise ValueError(f"Scenario {scenario_id} not found")
    return scenario


async def _load_institution(db: AsyncSession, institution_id: uuid.UUID) -> Institution:
    result = await db.execute(
        select(Institution).where(Institution.id == institution_id)
    )
    institution = result.scalar_one_or_none()
    if institution is None:
        raise ValueError(f"Institution {institution_id} not found")
    return institution


async def _load_slots(db: AsyncSession, scenario: Scenario) -> dict[str, dict]:
    """Load time grid slots using scenario-selected grid then active-term fallback."""
    from app.services.time_grid_service import resolve_slots_for_scenario
    return await resolve_slots_for_scenario(db, scenario)


async def _load_rooms(
    db: AsyncSession, scenario: Scenario, institution: Institution
) -> list[RoomData]:
    from app.models.room import Room
    result = await db.execute(
        select(Room).where(Room.institution_id == scenario.institution_id)
    )
    rooms = result.scalars().all()
    return [
        RoomData(
            room_id=str(r.id),
            capacity=r.capacity or 0,
            room_type=r.room_type.value if hasattr(r.room_type, "value") else str(r.room_type),
            tags=r.tags or [],
            campus=r.campus or "",
            building=r.building or "",
            target_utilisation_pct=getattr(r, "target_utilisation_pct", None),
        )
        for r in rooms
    ]


async def _load_faculty(
    db: AsyncSession, scenario: Scenario, institution: Institution
) -> list[FacultyData]:
    from app.models.faculty import Faculty
    result = await db.execute(
        select(Faculty).where(Faculty.institution_id == scenario.institution_id)
    )
    faculty_rows = result.scalars().all()
    return [
        FacultyData(
            faculty_id=str(f.id),
            name=getattr(f, "name", "") or "",
            max_weekly_hours=getattr(f, "max_weekly_hours", 20) or 20,
            availability_blacklist=getattr(f, "availability_blacklist", []) or [],
            employment_type=f.employment_type.value
            if hasattr(getattr(f, "employment_type", None), "value")
            else getattr(f, "employment_type", "FULL_TIME") or "FULL_TIME",
            preferences=getattr(f, "preferences", {}) or {},
        )
        for f in faculty_rows
    ]


async def _load_departments(
    db: AsyncSession, scenario: Scenario
) -> list[DepartmentData]:
    from app.models.institution import Department
    result = await db.execute(
        select(Department).where(Department.institution_id == scenario.institution_id)
    )
    dept_rows = result.scalars().all()
    return [
        DepartmentData(
            department_id=str(d.id),
            early_block_period=getattr(d, "early_block_period", None),
            early_block_soft=bool(getattr(d, "early_block_soft", False)),
            late_block_period=getattr(d, "late_block_period", None),
            late_block_soft=bool(getattr(d, "late_block_soft", False)),
            break_config=getattr(d, "break_config", None) or [],
            breaks_soft=bool(getattr(d, "breaks_soft", False)),
        )
        for d in dept_rows
    ]


async def _load_rules(
    db: AsyncSession,
    scenario: Scenario,
) -> tuple:
    """
    Returns a 6-tuple.  Every ScenarioRule row is classified into exactly one bucket:

        active_rules                — enabled CP-SAT/DSL rules (global only, target_id=None)
        disabled_constraint_codes   — frozenset: globally disabled CP-SAT constraint codes
        disabled_pruning_layers     — frozenset: var_builder pruning gates to skip globally
        disabled_per_entity         — dict[code, frozenset[entity_id]]: all per-entity disables
        per_entity_cp_sat_rules     — dict[code, dict[entity_id, RuleData]]: enabled per-entity
                                      CP-SAT rules (target_id set, NOT DSL).
                                      Constraints read these via context.per_entity_rule().
        slot_pattern_rules          — dict[course_id, pattern_code|None]: from SLOT_PATTERN_LOCK
                                      distribution rules.

    Routing table (is_enabled, target_id):
      OFF, entity      → disabled_per_entity[code].add(entity_id)
      OFF, global      → PRUNING_LAYER  → disabled_pruning_layers
                       → CP-SAT/DSL     → disabled_constraint_codes
      ON,  entity      → CP-SAT         → per_entity_cp_sat_rules
                       → PRUNING_LAYER  → (ignored)
      ON,  global      → CP-SAT/DSL     → active_rules
                       → PRUNING_LAYER  → (ignored)
      DISTRIBUTION     → slot_pattern_rules (SLOT_PATTERN_LOCK only), all others skipped
    """
    from app.models.constraint import ScenarioRule, RuleType
    result = await db.execute(
        select(ScenarioRule).where(ScenarioRule.scenario_id == scenario.id)
    )
    rows = result.scalars().all()

    active_rules: list[RuleData] = []
    disabled_constraint_codes: set[str] = set()
    disabled_pruning_layers: set[str] = set()
    disabled_per_entity: dict[str, set[str]] = {}
    per_entity_cp_sat_rules: dict[str, dict[str, RuleData]] = {}
    slot_pattern_rules_raw: dict[str, str | None] = {}

    for r in rows:
        code = r.definition_code or ""

        # ── Distribution rules — only extract SLOT_PATTERN_LOCK, skip rest ──
        r_type = getattr(r, "rule_type", None)
        is_dist = (r_type == RuleType.DISTRIBUTION) or (
            hasattr(r_type, "value") and r_type.value == "DISTRIBUTION"
        ) or (isinstance(r_type, str) and r_type == "DISTRIBUTION")
        if is_dist:
            if r.is_enabled and code == "SLOT_PATTERN_LOCK":
                for cid in (r.params or {}).get("course_ids", []):
                    slot_pattern_rules_raw[str(cid)] = (r.params or {}).get("pattern_code")
            continue  # distribution rules never become RuleData

        target_id = str(r.target_id) if r.target_id else None

        # ── Disabled rows ────────────────────────────────────────────────────
        if not r.is_enabled:
            if target_id:
                disabled_per_entity.setdefault(code, set()).add(target_id)
            elif code:
                disabled_constraint_codes.add(code)
            continue

        # ── Enabled rows ─────────────────────────────────────────────────────
        rule_data = RuleData(
            rule_id=str(r.id),
            definition_code=r.definition_code,
            params=r.params or {},
            script_trigger=r.script_trigger,
            script_logic=r.script_logic,
            is_hard=r.is_hard_constraint,
            penalty_weight=r.penalty_weight or 100,
            soft_tier=r.soft_tier,
            target_id=target_id,
            priority=5,
        )

        if target_id:
            # Per-entity CP-SAT rule override — stored separately from global active_rules.
            # model_builder reads these from inp.per_entity_rule_data via context.per_entity_rule().
            # These must never appear in active_rules (which drives constraint invocation passes).
            per_entity_cp_sat_rules.setdefault(code, {})[target_id] = rule_data
        else:
            active_rules.append(rule_data)

    return (
        active_rules,
        frozenset(disabled_constraint_codes),
        frozenset(disabled_pruning_layers),
        {k: frozenset(v) for k, v in disabled_per_entity.items()},
        {code: dict(entities) for code, entities in per_entity_cp_sat_rules.items()},
        slot_pattern_rules_raw,
    )


async def _load_buckets_with_offerings(
    db: AsyncSession, scenario: Scenario
) -> list[Any]:
    from app.models.curriculum import OfferingBucket
    result = await db.execute(
        select(OfferingBucket)
        .options(selectinload(OfferingBucket.offerings))
        .where(
            OfferingBucket.institution_id == scenario.institution_id,
            OfferingBucket.academic_term_id == scenario.academic_term_id,
            OfferingBucket.scenario_id == scenario.id,
        )
    )
    return result.scalars().all()


async def _load_courses(
    db: AsyncSession, scenario: Scenario, institution: Institution
) -> dict[str, Any]:
    from app.models.course import Course
    result = await db.execute(
        select(Course).where(Course.institution_id == scenario.institution_id)
    )
    return {str(c.id): c for c in result.scalars().all()}


async def _load_teaching_assignments(
    db: AsyncSession, scenario: Scenario
) -> dict[str, Any]:
    """Load TAs for the scenario's term keyed by course_id (last one wins per course)."""
    from app.models.curriculum import TeachingAssignment
    result = await db.execute(
        select(TeachingAssignment).where(
            TeachingAssignment.academic_term_id == scenario.academic_term_id,
            TeachingAssignment.institution_id == scenario.institution_id,
        )
    )
    # Multiple TAs per course are possible (multiple faculty). Keep all; assemblers
    # pick the first one with an override set rather than requiring a 1:1 mapping.
    tas: dict[str, Any] = {}
    for ta in result.scalars().all():
        key = str(ta.course_id)
        existing = tas.get(key)
        # Prefer a TA that has room overrides set over one that doesn't
        if existing is None or (
            (ta.override_room_ids or ta.override_lab_room_ids)
            and not (existing.override_room_ids or existing.override_lab_room_ids)
        ):
            tas[key] = ta
    return tas


async def _load_targets_with_requirements(
    db: AsyncSession, scenario: Scenario
) -> tuple[dict[str, Any], dict[str, list]]:
    """
    Single LEFT JOIN query: SchedulingTarget LEFT JOIN TargetRequirement.

    Replaces the separate _load_targets() + _load_requirements() pair with one
    DB round-trip. Returns:
      targets:        {str(target_id): SchedulingTarget ORM row}
      reqs_by_bucket: {str(bucket_id): [TargetRequirement, ...]}
    """
    from app.models.curriculum import TargetRequirement
    from collections import defaultdict

    rows = (
        await db.execute(
            select(SchedulingTarget, TargetRequirement)
            .outerjoin(TargetRequirement, TargetRequirement.target_id == SchedulingTarget.id)
            .where(
                SchedulingTarget.institution_id == scenario.institution_id,
                SchedulingTarget.academic_term_id == scenario.academic_term_id,
                SchedulingTarget.scenario_id == scenario.id,
                SchedulingTarget.is_active == True,  # noqa: E712
            )
        )
    ).all()

    targets: dict[str, Any] = {}
    reqs_by_bucket: dict[str, list] = defaultdict(list)

    for target, req in rows:
        targets[str(target.id)] = target
        if req is not None:
            reqs_by_bucket[str(req.bucket_id)].append(req)

    return targets, dict(reqs_by_bucket)


async def _load_department_working_days(
    db: AsyncSession,
    scenario: Scenario,
) -> dict[str, list[str] | None]:
    """
    Load per-department working days from departments table.

    Returns {dept_id: ["MON", "TUE", ...] | None}.
    None = all days in time grid (backward-compatible default).

    Requires: departments.working_days JSONB column (migration P5-2).
    """
    try:
        from app.models.institution import Department  # type: ignore
        result = await db.execute(
            select(Department.id, Department.working_days)
            .where(Department.institution_id == scenario.institution_id)
        )
        return {
            str(row.id): row.working_days
            for row in result.all()
        }
    except Exception:
        # working_days column may not exist yet (pre-migration)
        logger.debug("Department.working_days not available — defaulting all depts to None.")
        return {}


# ─── Config Merge ──────────────────────────────────────────────────────────────

def _load_warm_start_hints(scenario: Scenario) -> dict[str, int]:
    """Return best_hint dict if it exists and is a valid dict, else empty."""
    hints = scenario.best_hint
    return hints if isinstance(hints, dict) else {}


def _merge_solver_config(
    institution: Any,
    scenario: Scenario,
    warm_start_hints: dict | None = None,
) -> SolverConfig:
    """
    Merge solver config from four levels (lowest → highest priority):

      1. Code defaults       — reasonable baseline for any institution
      2. Mode overrides      — scheduling-mode-specific tuning (e.g. FFCS needs more workers)
      3. Institution DB      — institution.default_solver_config (hardware/policy caps)
      4. Scenario DB         — scenario.solver_config (per-solve tuning + warm-start hints)

    warm_start_hints: when not None, overrides the scenario.best_hint value.
    Pass {} to disable warm-start; pass None to use the caller-provided hints already set.

    YAML and env-var layers are intentionally absent: this is a multi-tenant system
    where per-institution tuning must live in the DB, not in deployment artifacts.
    """
    mode = scenario.scheduling_mode or getattr(institution, "scheduling_mode", None)
    mode_str = mode.value if hasattr(mode, "value") else str(mode) if mode else "TRADITIONAL"
    mode_overrides = MODE_SOLVER_CONFIG_OVERRIDES.get(mode_str, {})

    # Level 1: code defaults
    cfg = {
        "timeout_seconds": 300,
        "strategy": "PORTFOLIO_SEARCH",
        "num_workers": 8,
        "warm_start_hints": warm_start_hints if warm_start_hints is not None else {},
        "gap_limit": 0.05,
        "improvement_limit_seconds": 60,
        "max_solutions": 0,
        "enable_unsat_core": True,
        "log_search_progress": True,
    }

    # Level 2: mode overrides
    cfg.update(mode_overrides)

    # Level 3: institution DB config (e.g. cap num_workers to match server capacity)
    institution_cfg = getattr(institution, "default_solver_config", None) or {}
    cfg.update({k: v for k, v in institution_cfg.items() if k in cfg})

    # Level 4: scenario DB config (most specific — per-solve tuning)
    scenario_cfg = scenario.solver_config or {}
    cfg.update({k: v for k, v in scenario_cfg.items() if k in cfg})

    return SolverConfig(**cfg)


def _inject_physics_rules(existing_rules: list[RuleData]) -> list[RuleData]:
    """Ensure all physics constraints are in the rules list. Auto-add if missing."""
    existing_codes = {r.definition_code for r in existing_rules if r.definition_code}
    for code in PHYSICS_CONSTRAINT_CODES:
        if code not in existing_codes:
            existing_rules.append(RuleData(
                rule_id=f"physics__{code}",
                definition_code=code,
                params={},
                is_hard=True,
                penalty_weight=0,
                soft_tier=1,
                priority=1,
            ))
    return existing_rules


def _inject_slot_pattern_assign(
    existing_rules: list[RuleData],
    sessions: list[Any],
) -> list[RuleData]:
    """Auto-inject SLOT_PATTERN_ASSIGN rule when any session needs auto pattern selection."""
    if not any(getattr(s, "needs_pattern", False) for s in sessions):
        return existing_rules
    existing_codes = {r.definition_code for r in existing_rules if r.definition_code}
    if "SLOT_PATTERN_ASSIGN" not in existing_codes:
        existing_rules.append(RuleData(
            rule_id="auto__SLOT_PATTERN_ASSIGN",
            definition_code="SLOT_PATTERN_ASSIGN",
            params={},
            is_hard=True,
            penalty_weight=0,
            soft_tier=1,
            priority=2,
        ))
    return existing_rules


def _inject_ffcs_slot_bundle(
    existing_rules: list[RuleData],
    sessions: list[Any],
) -> list[RuleData]:
    """Auto-inject FFCS_SLOT_BUNDLE when any session carries a slot_bundle."""
    if not any(getattr(s, "slot_bundle", None) for s in sessions):
        return existing_rules
    existing_codes = {r.definition_code for r in existing_rules if r.definition_code}
    if "FFCS_SLOT_BUNDLE" not in existing_codes:
        existing_rules.append(RuleData(
            rule_id="auto__FFCS_SLOT_BUNDLE",
            definition_code="FFCS_SLOT_BUNDLE",
            params={},
            is_hard=True,
            penalty_weight=0,
            soft_tier=1,
            priority=1,
        ))
    return existing_rules


def _grid_has_typed_slots(slots: dict[str, dict]) -> bool:
    return any(
        isinstance(data, dict) and data.get("type") in ("lab", "theory")
        for data in slots.values()
    )


def _inject_slot_type(
    existing_rules: list[RuleData],
    slots: dict[str, dict],
) -> list[RuleData]:
    """Auto-inject SLOT_TYPE when the time grid distinguishes lab vs theory slots."""
    if not _grid_has_typed_slots(slots):
        return existing_rules
    existing_codes = {r.definition_code for r in existing_rules if r.definition_code}
    if "SLOT_TYPE" not in existing_codes:
        existing_rules.append(RuleData(
            rule_id="auto__SLOT_TYPE",
            definition_code="SLOT_TYPE",
            params={},
            is_hard=True,
            penalty_weight=0,
            soft_tier=1,
            priority=1,
        ))
    return existing_rules


def _build_slot_pattern_rules(rules: list[RuleData]) -> dict[str, str | None]:
    """
    Extract slot pattern rules from already-loaded active rules.

    SLOT_PATTERN_LOCK distribution rules were extracted in _load_rules() and
    are NOT in active_rules. This function exists for explicit documentation
    of how slot_pattern_rules flows through assemble_input().

    Returns the already-extracted dict (passed in directly from _load_rules return).
    """
    # slot_pattern_rules_raw was already built in _load_rules() and is passed
    # via the 6th return value. This identity function documents the data flow.
    return {}  # populated via _load_rules() — see assemble_input()


def _build_slot_patterns(slots: dict[str, dict]) -> tuple:
    """
    Group time grid slots by (family, day) → SlotPatternDef tuple.

    Each pattern contains exactly two consecutive same-day tokens. Pattern codes
    use ``{family}_{day}`` when multiple days share a family label (REC grids).

    Returns an empty tuple if no slots have a 'family' key (non-FFCS grids).
    """
    from collections import defaultdict

    by_family_day: dict[tuple[str, str], list[str]] = defaultdict(list)
    for code, data in slots.items():
        if isinstance(data, dict):
            fam = data.get("family")
            if fam:
                day = str(data.get("day", "MON"))
                by_family_day[(fam, day)].append(code)

    period_map: dict[str, int] = {}
    day_slots: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for code, data in slots.items():
        if not isinstance(data, dict):
            continue
        day = str(data.get("day", "MON"))
        start = data.get("start", "08:00")
        day_slots[day].append((code, start))
    for day_slot_list in day_slots.values():
        day_slot_list.sort(key=lambda x: x[1])
        for idx, (code, _) in enumerate(day_slot_list, start=1):
            period_map[code] = idx

    patterns: list = []
    fam_day_counts: dict[str, int] = defaultdict(int)
    for (fam, _day), _codes in by_family_day.items():
        fam_day_counts[fam] += 1

    for (fam, day), codes in sorted(by_family_day.items()):
        if len(codes) != 2:
            continue
        ordered = sorted(codes, key=lambda c: period_map.get(c, 0))
        t0, t1 = ordered[0], ordered[1]
        p0, p1 = period_map.get(t0, 0), period_map.get(t1, 0)
        if p1 != p0 + 1:
            continue
        pattern_code = fam if fam_day_counts[fam] == 1 else f"{fam}_{day}"
        from solver_engine.contracts import SlotPatternDef
        patterns.append(SlotPatternDef(code=pattern_code, tokens=(t0, t1)))

    return tuple(patterns)


# ─── Slot Conversion ──────────────────────────────────────────────────────────

def _build_slot_data(slots: dict[str, dict]) -> dict[str, SlotData]:
    """Convert raw JSONB slot dicts to SlotData frozen dataclasses.

    The time-grid JSONB stores ``period`` as a label string ("morning",
    "afternoon", "evening") which is useless for numeric comparisons.  We
    derive an integer 1-based period index by sorting each day's slots by
    their ``start`` time — the first slot of the day is period 1, the second
    is period 2, etc.  This is the value BlockEarlySlotsConstraint and
    BlockLateSlotsConstraint rely on.
    """
    # Group valid slot codes by day and sort by start time
    day_slots: dict[str, list[tuple[str, str]]] = {}
    for code, data in slots.items():
        if not isinstance(data, dict):
            continue
        day = data.get("day", "MON")
        start = data.get("start", "08:00")
        day_slots.setdefault(day, []).append((code, start))

    # Assign 1-based integer period numbers ordered by start time within each day
    period_map: dict[str, int] = {}
    for day_slot_list in day_slots.values():
        day_slot_list.sort(key=lambda x: x[1])  # lexicographic sort on "HH:MM" is correct
        for idx, (code, _) in enumerate(day_slot_list, start=1):
            period_map[code] = idx

    result = {}
    for code, data in slots.items():
        if not isinstance(data, dict):
            continue
        result[code] = SlotData(
            slot_code=code,
            day=data.get("day", "MON"),
            period=period_map.get(code, 1),
            start=data.get("start", "08:00"),
            end=data.get("end", "09:00"),
            slot_type=data.get("type", "theory"),
        )
    return result
