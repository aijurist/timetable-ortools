"""
app/services/distribution/contracts.py
======================================
Frozen data contracts for the unified cohort distribution engine.

These carry everything a DistributionStrategy needs to turn a cohort's teaching
demand into the persisted data model (SchedulingTargets + OfferingBuckets +
CourseOfferings + TargetRequirements). No ORM objects cross this boundary — the
caller (cohort_service / the distribute endpoint) flattens the DB rows into these
plain values, the strategy does the work, and a DistributionResult comes back.

See documents plan: "Unified Cohort Distribution Engine".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CourseLine:
    """One course's teaching assignments for a single cohort.

    teacher_tuples mirrors the (faculty_id, section_count, pinned_label) shape that
    cohort_service already builds from TeachingAssignment rows.
    """

    course_id: str
    # (faculty_id, section_count, pinned_label)
    teacher_tuples: tuple[tuple[str, int, str | None], ...]
    is_cross_dept: bool = False
    # {faculty_id: {offering_field: value}} — room/lab pins from TeachingAssignment overrides
    ta_overrides: dict[str, Any] = field(default_factory=dict)
    # Year-of-study + semester (from the TeachingAssignment) — grouping partitions on this.
    study_year: int | None = None
    study_semester: int | None = None
    # Elective pool: when set, this line is one of the PE/OE alternatives for that pool.
    # Distribution engine bypasses the group optimizer for pool lines and creates a
    # CHOOSE_COURSE + force_parallel_slots bucket instead.
    elective_pool_id: str | None = None
    elective_pool_label: str | None = None   # "PE-1", "OE-1" etc.
    is_open_elective: bool = False           # True = OE (cross-dept)


@dataclass(frozen=True)
class RelaxationHint:
    """Produced from a main-solve UNSAT core; loosens the next distribution run.

    All fields default to "no relaxation" so a None/empty hint is a no-op.
    """

    over_packed_groups: tuple[int, ...] = ()
    over_packed_dept_ids: tuple[str, ...] = ()
    bump_max_groups_per_course: int = 0
    relax_group_size_equality: bool = False


@dataclass(frozen=True)
class DistributionDemand:
    """Everything a strategy needs to build a cohort's data model — no ORM objects."""

    cohort_id: str
    institution_id: str
    academic_term_id: str
    department_id: str | None
    mode: str  # "TRADITIONAL" | "HYBRID" | "FFCS"
    courses: tuple[CourseLine, ...]
    scenario_id: str | None = None
    size: int | None = None
    class_size: int | None = None
    class_count: int | None = None
    # Resolved optimizer params (from the *_DIST ScenarioRule), already merged with defaults.
    params: dict[str, Any] = field(default_factory=dict)
    # Cohort name + extra_data, used by TRADITIONAL to name/tag BATCH children.
    cohort_name: str = ""
    dept_code: str = "DEPT"
    cohort_extra_data: dict[str, Any] = field(default_factory=dict)
    # Set on re-distribution (bounded feedback seam); None on first run.
    relaxation: RelaxationHint | None = None


@dataclass
class DistributionResult:
    """Outcome of one engine.distribute() call (mutable — strategies accumulate counts)."""

    buckets_created: int = 0
    offerings_created: int = 0
    tba_created: int = 0
    demands_created: int = 0
    num_groups: int = 0
    # {offering_id (str): group_number} — empty for TRADITIONAL/FFCS-without-groups
    group_assignments: dict[str, int] = field(default_factory=dict)
    # OPTIMAL | FEASIBLE | FALLBACK | SKIPPED | INFEASIBLE
    status: str = "SKIPPED"
    warnings: list[str] = field(default_factory=list)
