"""
models/curriculum.py
====================
Curriculum & demand tier: the building blocks for FFCS, Hybrid, and
Traditional scheduling modes.

Tables:
  scheduling_targets  — batches / clusters / virtual groups who need a timetable.
  target_requirements — links a batch to the "buckets" of courses it must attend.
  offering_buckets    — a named container of course offerings (e.g. "Sem 5 Core").
  course_offerings    — one slot-assignment per faculty×course combo; solver writes here.

Architecture notes:
- `SchedulingTarget` is the "demand" side — it answers "which batches need scheduling?".
- `OfferingBucket` is the "supply" container — it groups offerings and carries constraint
  metadata (min/max_selection, force_parallel_slots).
- The Solver reads buckets + targets, produces slot assignments inside `course_offerings`.
- Student registration (FFCS) reads `course_offerings` to present the selection menu.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TargetType(str, enum.Enum):
    BATCH = "BATCH"          # A fixed class (e.g. "CSE-A 2024")
    CLUSTER = "CLUSTER"      # A cross-department grouping
    VIRTUAL = "VIRTUAL"      # Dynamic: computed at runtime from registration data
    COHORT = "COHORT"        # Dept intake — reads TeachingAssignments, auto-creates everything


class SelectionPolicy(str, enum.Enum):
    FIXED_BATCH = "FIXED_BATCH"       # Traditional — all in the bucket are assigned
    CHOOSE_FACULTY = "CHOOSE_FACULTY"  # Hybrid Core — pick 1 faculty for a course
    CHOOSE_COURSE = "CHOOSE_COURSE"    # Elective pool — pick 1 course from several
    OPEN_POOL = "OPEN_POOL"            # FFCS — student self-registers from open pool


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SchedulingTarget(Base):
    """
    The "demand" entity — a group of students who need a timetable.

    Examples:
    - Batch: "CSE-A 2024" (100 students, needs 6 core courses)
    - Cluster: "Joint ECE+EEE Lab Group" (cross-dept)
    - Virtual: assembled dynamically from FFCS registrations

    `size` feeds the Tier 1 RoomCapacity constraint: the solver
    will only assign rooms whose capacity >= target.size.
    """

    __tablename__ = "scheduling_targets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    target_type: Mapped[TargetType] = mapped_column(
        Enum(TargetType, name="target_type"),
        nullable=False,
        default=TargetType.BATCH,
    )

    # Number of students — used for room capacity constraint.
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Department this batch belongs to — needed for HOD scoping ("show only my batches").
    # Loose FK (SET NULL on dept delete) so orphan batches don't lose their history.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Extra data (e.g. {"program": "B.Tech", "year": 3, "section": "A"})
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Multi-shift support — restrict which time-of-day shifts this target is
    # allowed to be scheduled in.  NULL = all shifts.
    # e.g. ["morning", "afternoon"] — values match SlotDefinition.period.
    allowed_shifts: Mapped[list | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Scenario-scoped target. NULL = legacy term-level (shared across scenarios).
    # ondelete=CASCADE: deleting the scenario deletes its targets.
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = legacy term-level target. Non-NULL = belongs to this scenario only.",
    )

    # Parent COHORT → child BATCH relationship (TRADITIONAL only).
    # parent_id is set on BATCH children auto-created by a COHORT.
    # NULL for manually created targets, CLUSTER, VIRTUAL, and COHORT itself.
    # ondelete=CASCADE: deleting the COHORT deletes all its BATCH children.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduling_targets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # class_count: meaningful ONLY on COHORT type.
    # Stores the derived or explicit number of child batches.
    # NULL on all BATCH, CLUSTER, VIRTUAL targets.
    class_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Semester this cohort covers. NULL = all semesters (legacy / TRADITIONAL).
    # When set on a HYBRID/FFCS cohort, distribution only draws TAs with the
    # matching study_semester — enabling per-semester scheduling runs.
    study_semester: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="HYBRID/FFCS: restrict distribution to TAs with this study_semester. NULL = all semesters.",
    )

    # Relationships
    requirements: Mapped[list["TargetRequirement"]] = relationship(
        "TargetRequirement", back_populates="target", cascade="all, delete-orphan"
    )
    children: Mapped[list["SchedulingTarget"]] = relationship(
        "SchedulingTarget",
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys="[SchedulingTarget.parent_id]",
    )
    parent: Mapped["SchedulingTarget | None"] = relationship(
        "SchedulingTarget",
        back_populates="children",
        remote_side="[SchedulingTarget.id]",
        foreign_keys="[SchedulingTarget.parent_id]",
    )

    def __repr__(self) -> str:
        return f"<SchedulingTarget name={self.name!r} type={self.target_type}>"


class OfferingBucket(Base):
    """
    A named container that groups course offerings and carries constraint metadata.

    Constraint Data on this model:
    - min_selection / max_selection: how many offerings in this bucket must be picked
      (Traditional: 6/6 = take all; Hybrid Core: 1/1 = pick one faculty).
    - force_parallel_slots: if TRUE, Solver MUST schedule all offerings at the same time
      (used for labs split across sections).
    - selection_policy: drives which UI + solver behaviour is activated.
    """

    __tablename__ = "offering_buckets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)  # "Sem 5 Core"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # How many offerings inside this bucket must be selected / scheduled.
    # Traditional mode: min=max=total_offerings (take all).
    # FFCS elective: min=1, max=1 (student chooses one slot).
    min_selection: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    max_selection: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # If TRUE, Solver forces all offerings in this bucket to share the same slot.
    force_parallel_slots: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


    selection_policy: Mapped[SelectionPolicy] = mapped_column(
        Enum(SelectionPolicy, name="selection_policy"),
        nullable=False,
        default=SelectionPolicy.FIXED_BATCH,
    )

    # Scenario-scoped bucket. NULL = legacy term-level (shared across scenarios).
    # ondelete=CASCADE: deleting the scenario deletes its buckets.
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="NULL = legacy term-level bucket. Non-NULL = belongs to this scenario only.",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    department: Mapped["Department | None"] = relationship(  # type: ignore[name-defined]
        "Department"
    )
    offerings: Mapped[list["CourseOffering"]] = relationship(
        "CourseOffering", back_populates="bucket", cascade="all, delete-orphan"
    )
    target_requirements: Mapped[list["TargetRequirement"]] = relationship(
            "TargetRequirement",
            back_populates="bucket",
            cascade="all, delete-orphan",
            passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<OfferingBucket name={self.name!r} policy={self.selection_policy}>"


class CourseOffering(Base):
    """
    One faculty × course combination available for scheduling.

    This is both the solver's INPUT (here is a course that needs a slot)
    and the solver's OUTPUT (the assigned slot_code and room_id are written here).

    For FFCS: students register against a CourseOffering (not against a Course).
    A single course may have many offerings under different faculty for the same term.

    is_frozen: set TRUE during batch processing / maintenance to block new registrations
               even when booked_seats < max_seats.

    bucket_id: NULL for HYBRID/FFCS offerings pending group optimizer assignment.
               The group optimizer sets this to the student-group OfferingBucket.
    """

    __tablename__ = "course_offerings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bucket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offering_buckets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Loose UUID references — no FK; these survive independent service deletions.
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # --- Solver output fields (NULL before solve) ---
    # For FFCS / Traditional: opaque code from time_grids.slots
    slot_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # For FFCS: slot family grouping (e.g. "A1", "B2") — bundles theory + lab slots
    slot_family: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # For Traditional: integer slot index
    fixed_slot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # UUID of the assigned room (solver OUTPUT — written after solve)
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # --- Coordinator room input (arrays of room UUIDs, NULL = no preference) ---
    # Specific rooms this offering should use (lecture/tutorial components).
    target_room_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="List of room UUID strings for L/T components. Empty/null = no pin → fall back to target_room_tags.",
    )

    # If True, target_room_ids is a soft preference (penalty) rather than a hard requirement (prune).
    target_room_ids_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Specific rooms for the lab (P) component (LTPC only).
    target_lab_room_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="List of room UUID strings for P (lab) component. Empty/null = no pin → fall back to target_lab_room_tags.",
    )
    target_lab_room_ids_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Tag-based fallback for L/T components (when target_room_ids is empty).
    target_room_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    target_room_tags_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Tag-based fallback for P (lab) component (when target_lab_room_ids is empty).
    target_lab_room_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    target_lab_room_tags_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # --- Room capacity bounds (both optional per-offering overrides) ---
    # min_capacity: explicit student count for this offering.
    # Takes precedence over SchedulingTarget.size (batch-level fallback).
    # Use when one offering in a bucket has a different headcount than the batch:
    #   e.g. lab split (30 students), combined lecture (300 students), seminar (15).
    # None = fall back to SchedulingTarget.size via TargetRequirement.
    min_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # max_room_capacity: explicit per-offering override (optional) ---
    # Per-offering hard ceiling on room size.
    # Only needed when admin wants to pin this offering to a specific room size range
    # (e.g. force DSA combined lecture to exactly HALL_300, or cap a seminar to 40-seat rooms).
    # Primary upper-bound enforcement is via the MAX_ROOM_SIZE rule's size_factor param
    # which derives the ceiling from SchedulingTarget.size automatically for all offerings.
    # This field takes precedence over size_factor when set.
    # None = use size_factor policy from scenario rule (or no upper bound if rule absent).
    max_room_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- FFCS registration counters ---
    max_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    booked_seats: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Blocks new registrations during batch operations or re-solve windows.
    is_frozen: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # HYBRID/FFCS: which group-distribution group this offering belongs to (1..N).
    # Set by the group_distribution_service after running the CP-SAT sub-solver.
    # NULL = TRADITIONAL mode, or HYBRID/FFCS offering not yet distributed.
    # group_number restarts at 1 PER (study_year, study_semester) — grouping is
    # scoped per dept/semester, so (study_year, study_semester, group_number) is
    # what uniquely identifies a group within a cohort.
    group_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # For batched lab offerings (e.g. 70-student course split into 2×35 labs).
    # 1 = Batch 1, 2 = Batch 2, …  NULL = not a batched offering.
    # Persisted during import so batch identity is deterministic across accounts
    # and never derived from array-position / row ordering.
    batch_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Year-of-study + semester this offering belongs to (copied from the source
    # TeachingAssignment at distribution time). Drives per-semester grouping and
    # the solver's group_non_overlap scope. NULL = unknown / not partitioned.
    study_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    study_semester: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    bucket: Mapped["OfferingBucket"] = relationship(
        "OfferingBucket", back_populates="offerings"
    )

    def __repr__(self) -> str:
        return (
            f"<CourseOffering course={self.course_id} faculty={self.faculty_id}"
            f" slot={self.slot_code!r}>"
        )


class TargetRequirement(Base):
    """
    Many-to-many link: a SchedulingTarget must satisfy at least one OfferingBucket.

    E.g. "CSE-A 2024" (target) MUST attend "Sem 5 Core" (bucket).
    The Solver reads target_requirements to build its demand matrix.
    """

    __tablename__ = "target_requirements"
    __table_args__ = (
        UniqueConstraint("target_id", "bucket_id", name="uq_target_bucket"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduling_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bucket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offering_buckets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    target: Mapped["SchedulingTarget"] = relationship(
        "SchedulingTarget", back_populates="requirements"
    )
    bucket: Mapped["OfferingBucket"] = relationship(
        "OfferingBucket", back_populates="target_requirements"
    )

    def __repr__(self) -> str:
        return f"<TargetRequirement target={self.target_id} bucket={self.bucket_id}>"


class TargetCourseDemand(Base):
    """
    Pre-solve curriculum demand record.

    Stores "SchedulingTarget X needs Course Y this term (N sections)."

    This is term-level data shared across scenarios — coordinators define
    demand once per term and then run allocation against it to generate
    OfferingBuckets + CourseOfferings automatically.

    required_sections: TRADITIONAL only — how many parallel sections are needed
    (e.g. 3 sections of DSA for CSE targets split into CSE-A, CSE-B, CSE-C).
    For HYBRID / FFCS this is always 1 (all faculty go into one shared bucket).
    """

    __tablename__ = "target_course_demand"
    __table_args__ = (
        UniqueConstraint("target_id", "course_id", name="uq_target_course_demand"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # Loose UUID references — no FK; survive independent service deletions.
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # TRADITIONAL only: how many parallel sections needed
    required_sections: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<TargetCourseDemand target={self.target_id}"
            f" course={self.course_id} sections={self.required_sections}>"
        )


class TeachingAssignment(Base):
    """
    HOD pre-assignment: this teacher will take this course this term.

    Persisted immediately when HOD enters their teaching plan — survives
    page refresh. COHORT creation reads these rows to auto-create
    buckets + CourseOfferings atomically.

    section_count: how many parallel groups this teacher handles this term.
      1 = normal (one section), 2 = takes course for 2 groups.
      Expands to section_count CourseOffering rows at allocation time.

    pinned_section_label: TRADITIONAL only — pin this teacher to a specific
      auto-generated class ("A" → CSE-A, "B" → CSE-B). NULL = solver decides.
    """

    __tablename__ = "teaching_assignments"
    __table_args__ = (
        UniqueConstraint(
            "academic_term_id", "department_id", "faculty_id", "course_id",
            name="uq_teaching_assignment",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # SET NULL on dept delete: preserves historical assignment records.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Loose UUID references — no FK for cross-service decoupling.
    # NULL faculty_id = pending request (service dept has not yet assigned a teacher).
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Which service dept was asked to fulfill this assignment. NULL = direct assignment.
    # PostgreSQL NULL ≠ NULL in unique checks, so multiple pending requests for the same
    # course+dept+term are allowed.
    requested_dept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="For pending TAs: which service dept was asked to provide a teacher. NULL = direct assignment.",
    )

    section_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    max_sections: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Solver-fill ceiling: if set and > section_count, engine may assign up to max_sections sections to this faculty. NULL = no expansion allowed."
    )
    pinned_section_label: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Planning-time context: year of study and semester this course is taught in.
    # Dept-specific — CSE may teach Maths in Sem 3, ECE in Sem 1.
    study_year: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Year of study this course is taught in. Dept-specific, set at planning time.",
    )
    study_semester: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Semester number. Dept-specific, set at planning time.",
    )

    # Room preference overrides (per-term).
    # When set, these take priority over Course.preferred_room_ids / lab_preferred_room_ids
    # during scenario assembly. NULL = use Course defaults.
    override_room_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Term-level override: room UUIDs for L/T. NULL = use Course.preferred_room_ids.",
    )
    override_room_ids_soft: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None,
    )
    override_lab_room_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Term-level override: room UUIDs for P component. NULL = use Course.lab_preferred_room_ids.",
    )
    override_lab_room_ids_soft: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None,
    )
    is_merged_session: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="True = all section_count sections meet together in one room. "
                "Solver should emit 1 offering with min_capacity = section_count × students_per_section, "
                "and pick any room large enough (override_room_ids stay as soft preferences).",
    )

    # When set, this TA's course is one of the alternatives in an ElectivePool
    # (PE-1, OE-1 …). section_count on the TA drives the distribution split
    # (e.g. section_count=2 → 2 of the 5 groups get this course option).
    # NULL = core course (not part of any elective pool).
    elective_pool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("elective_pools.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK → elective_pools; NULL = core course.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<TeachingAssignment faculty={self.faculty_id}"
            f" course={self.course_id} sections={self.section_count}>"
        )


class CourseShareConfig(Base):
    """
    Admin-controlled: this course is shared across these departments this term.

    When COHORT is created for dept D, course C:
    - If CourseShareConfig exists for (term, C) and D is in department_ids → cross-dept bucket
    - Otherwise → dept-specific bucket

    department_ids: JSON list of department UUIDs that share this course.
      NULL = all depts (open sharing). Non-null list = selective sharing.
    """

    __tablename__ = "course_share_configs"
    __table_args__ = (
        UniqueConstraint(
            "academic_term_id", "course_id",
            name="uq_course_share_config",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # Loose UUID — no FK for cross-service decoupling.
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # NULL = all depts share; specific list = selective. Admin configures once per term.
    department_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<CourseShareConfig course={self.course_id} term={self.academic_term_id}>"
