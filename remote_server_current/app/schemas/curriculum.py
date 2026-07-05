"""
app/schemas/curriculum.py
=========================
Pydantic V2 schemas for SchedulingTarget, OfferingBucket, CourseOffering,
and TargetRequirement.

These power the curriculum/demand layer used by the solver and FFCS
registration subsystem.

Design Notes
------------
- ``course_id``, ``faculty_id``, ``room_id`` on CourseOffering are loose UUIDs
  (no DB FK). They are typed as Optional[uuid.UUID] in schemas because API
  consumers always send proper UUIDs.
- ``slot_code`` and ``room_id`` on CourseOffering are solver OUTPUT fields —
  written back after a successful solve (first session's assignment for
  Traditional/Hybrid; the single bundle slot for FFCS).
- ``fixed_slot_id`` is an ADMIN INPUT field for CHOOSE_COURSE (elective) mode:
  an admin sets it before the solve to pre-lock an offering to a specific time
  grid position (1-based integer index into sorted slot codes). The solver
  respects it via ``SessionData.allowed_slot_codes`` in the assembler.
  It is NOT written by the solver — it is read by it.
- ``is_frozen`` blocks new registrations during batch operations / re-solve.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.curriculum import SelectionPolicy, TargetType
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# SchedulingTarget
# ---------------------------------------------------------------------------


class SchedulingTargetCreate(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    name: str = Field(..., max_length=100, description="e.g. 'CSE-A 2024'")
    target_type: TargetType = TargetType.BATCH
    size: Optional[int] = Field(None, description="Number of students — used for room capacity constraint")
    department_id: Optional[uuid.UUID] = Field(None, description="FK → departments.id (SET NULL on delete)")
    extra_data: Optional[dict[str, Any]] = Field(None, description="e.g. {program: 'B.Tech', year: 3, section: 'A'}")
    allowed_shifts: Optional[list[str]] = Field(
        None, description="Time-of-day shifts this target may use, e.g. ['morning', 'afternoon']"
    )
    is_active: bool = True
    scenario_id: Optional[uuid.UUID] = Field(
        None, description="Scope to a specific scenario. NULL = term-level (legacy)."
    )
    # COHORT-only fields
    class_count: Optional[int] = Field(None, description="COHORT only: explicit number of child batches")
    scheduling_mode: Optional[str] = Field(
        None,
        description="COHORT only: override institution scheduling_mode. "
                    "Takes priority over institution.scheduling_mode. "
                    "Pass scenario.solver_config.mode here.",
    )
    study_semester: Optional[int] = Field(
        None, ge=1, le=12,
        description="COHORT only: when set, distribution draws only TAs with this study_semester. "
                    "NULL = all semesters (TRADITIONAL default).",
    )


class SchedulingTargetUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    target_type: Optional[TargetType] = None
    size: Optional[int] = None
    department_id: Optional[uuid.UUID] = None
    extra_data: Optional[dict[str, Any]] = None
    allowed_shifts: Optional[list[str]] = None
    is_active: Optional[bool] = None
    class_count: Optional[int] = None
    study_semester: Optional[int] = Field(None, ge=1, le=12)


class SchedulingTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    name: str
    target_type: TargetType
    size: Optional[int]
    department_id: Optional[uuid.UUID]
    extra_data: Optional[dict[str, Any]]
    allowed_shifts: Optional[list[str]]
    is_active: bool
    parent_id: Optional[uuid.UUID] = None
    class_count: Optional[int] = None
    study_semester: Optional[int] = None
    scenario_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


SchedulingTargetListResponse = PaginatedResponse[SchedulingTargetResponse]


# ---------------------------------------------------------------------------
# OfferingBucket
# ---------------------------------------------------------------------------


class OfferingBucketCreate(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: Optional[uuid.UUID] = Field(None, description="FK → departments.id (SET NULL on delete)")
    name: str = Field(..., max_length=100, description="e.g. 'Sem 5 Core'")
    description: Optional[str] = None
    min_selection: int = Field(1, ge=1)
    max_selection: int = Field(1, ge=1)
    force_parallel_slots: bool = Field(False, description="If True, solver forces all offerings in this bucket to share the same slot")
    selection_policy: SelectionPolicy = SelectionPolicy.FIXED_BATCH
    is_active: bool = True
    scenario_id: Optional[uuid.UUID] = Field(
        None, description="Scope to a specific scenario. NULL = term-level (legacy)."
    )


class OfferingBucketUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    min_selection: Optional[int] = Field(None, ge=1)
    max_selection: Optional[int] = Field(None, ge=1)
    force_parallel_slots: Optional[bool] = None
    selection_policy: Optional[SelectionPolicy] = None
    is_active: Optional[bool] = None


class OfferingBucketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: Optional[uuid.UUID]
    name: str
    description: Optional[str]
    min_selection: int
    max_selection: int
    force_parallel_slots: bool
    selection_policy: SelectionPolicy
    is_active: bool
    scenario_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


OfferingBucketListResponse = PaginatedResponse[OfferingBucketResponse]


# ---------------------------------------------------------------------------
# CourseOffering
# ---------------------------------------------------------------------------


class CourseOfferingCreate(BaseModel):
    bucket_id: uuid.UUID = Field(..., description="FK → offering_buckets.id (CASCADE)")
    course_id: uuid.UUID = Field(..., description="Loose UUID — no FK; references courses table by convention")
    faculty_id: Optional[uuid.UUID] = Field(None, description="Loose UUID — null for TBA assignments")
    max_seats: Optional[int] = Field(None, description="FFCS capacity; None for non-FFCS offerings")
    min_capacity: Optional[int] = Field(None, description="Explicit student count for this offering. Overrides SchedulingTarget.size for room routing. Use for lab splits, combined lectures, or any offering whose headcount differs from the batch size. None = use batch size.")
    max_room_capacity: Optional[int] = Field(None, description="Upper bound on room size. Overrides the scenario-level size_factor policy for this specific offering. None = use policy default.")
    target_room_ids: Optional[list[str]] = Field(None, description="List of room UUIDs for L/T components.")
    target_room_ids_soft: bool = False
    target_lab_room_ids: Optional[list[str]] = Field(None, description="List of room UUIDs for P (lab) component (LTPC only).")
    target_lab_room_ids_soft: bool = False
    target_room_tags: Optional[list[str]] = Field(None, description="Tag-based fallback for L/T components (when target_room_ids is empty).")
    target_room_tags_soft: bool = False
    target_lab_room_tags: Optional[list[str]] = Field(None, description="Tag-based fallback for P component.")
    target_lab_room_tags_soft: bool = False
    is_frozen: bool = False


class CourseOfferingUpdate(BaseModel):
    faculty_id: Optional[uuid.UUID] = None
    bucket_id: Optional[uuid.UUID] = Field(None, description="Move offering to a different bucket")
    slot_code: Optional[str] = Field(None, max_length=20, description="Solver output: opaque slot code from time_grids.slots")
    fixed_slot_id: Optional[int] = Field(None, description="Admin input (CHOOSE_COURSE only): 1-based index into sorted slot codes — pre-locks offering to this slot before solve")
    room_id: Optional[uuid.UUID] = Field(None, description="Solver output: UUID of assigned room")
    target_room_ids: Optional[list[str]] = Field(None, description="List of room UUIDs for L/T components.")
    target_room_ids_soft: Optional[bool] = Field(None, description="Override per-offering soft flag.")
    target_lab_room_ids: Optional[list[str]] = Field(None, description="List of room UUIDs for P component (LTPC only).")
    target_lab_room_ids_soft: Optional[bool] = Field(None, description="Override per-offering lab soft flag.")
    target_room_tags: Optional[list[str]] = Field(None, description="Tag-based fallback for L/T components.")
    target_room_tags_soft: Optional[bool] = None
    target_lab_room_tags: Optional[list[str]] = Field(None, description="Tag-based fallback for P component.")
    target_lab_room_tags_soft: Optional[bool] = None
    max_seats: Optional[int] = None
    min_capacity: Optional[int] = None
    max_room_capacity: Optional[int] = None
    booked_seats: Optional[int] = Field(None, ge=0)
    is_frozen: Optional[bool] = None


class CourseOfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bucket_id: uuid.UUID
    course_id: uuid.UUID
    faculty_id: Optional[uuid.UUID]
    slot_code: Optional[str]
    fixed_slot_id: Optional[int]
    room_id: Optional[uuid.UUID]
    target_room_ids: Optional[list[str]] = None
    target_room_ids_soft: bool = False
    target_lab_room_ids: Optional[list[str]] = None
    target_lab_room_ids_soft: bool = False
    target_room_tags: Optional[list[str]] = None
    target_room_tags_soft: bool = False
    target_lab_room_tags: Optional[list[str]] = None
    target_lab_room_tags_soft: bool = False
    max_seats: Optional[int]
    min_capacity: Optional[int]
    max_room_capacity: Optional[int]
    booked_seats: int
    is_frozen: bool
    group_number: Optional[int] = None
    batch_number: Optional[int] = None
    study_year: Optional[int] = None
    study_semester: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Enriched display fields — joined by service layer
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    course_session_type: Optional[str] = None
    faculty_name: Optional[str] = None
    batch_name: Optional[str] = None
    bucket_name: Optional[str] = None


CourseOfferingListResponse = PaginatedResponse[CourseOfferingResponse]


# ---------------------------------------------------------------------------
# TargetRequirement  (M2M join — read-heavy, write-once)
# ---------------------------------------------------------------------------


class TargetRequirementCreate(BaseModel):
    target_id: uuid.UUID = Field(..., description="FK → scheduling_targets.id (CASCADE)")
    bucket_id: uuid.UUID = Field(..., description="FK → offering_buckets.id (CASCADE)")


class TargetRequirementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_id: uuid.UUID
    bucket_id: uuid.UUID
    created_at: datetime


TargetRequirementListResponse = PaginatedResponse[TargetRequirementResponse]


# ---------------------------------------------------------------------------
# TeachingAssignment
# ---------------------------------------------------------------------------


class TeachingAssignmentCreate(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: Optional[uuid.UUID] = None
    faculty_id: Optional[uuid.UUID] = None          # None = pending request (service dept not yet assigned)
    requested_dept_id: Optional[uuid.UUID] = None   # Which service dept to request a teacher from
    course_id: uuid.UUID
    section_count: int = Field(default=1, ge=1, description="Parallel sections this teacher handles")
    max_sections: Optional[int] = Field(None, ge=1, description="Solver-fill ceiling. NULL = no expansion allowed.")
    pinned_section_label: Optional[str] = Field(None, description="TRADITIONAL only: pin to class label 'A','B'...")
    notes: Optional[str] = None
    study_year: Optional[int] = Field(None, ge=1, le=8, description="Year of study this course is taught in")
    study_semester: Optional[int] = Field(None, ge=1, le=12, description="Semester number, dept-specific")

    # Room preference overrides (per-term — takes priority over Course defaults)
    override_room_ids: Optional[list[str]] = Field(
        None, description="Term-level override: room UUIDs for L/T. NULL = use Course.preferred_room_ids."
    )
    override_room_ids_soft: Optional[bool] = None
    override_lab_room_ids: Optional[list[str]] = Field(
        None, description="Term-level override: room UUIDs for P component. NULL = use Course.lab_preferred_room_ids."
    )
    override_lab_room_ids_soft: Optional[bool] = None

    is_merged_session: bool = False
    is_active: bool = True
    elective_pool_id: Optional[uuid.UUID] = Field(
        None, description="Assign this TA to an elective pool (PE/OE). NULL = core course."
    )

    @model_validator(mode="after")
    def require_faculty_or_request(self) -> "TeachingAssignmentCreate":
        # Both None is valid — unassigned pending slot (HOD assigns faculty later).
        # Cross-dept request: set requested_dept_id only (faculty_id stays None).
        return self


class TeachingAssignmentUpdate(BaseModel):
    faculty_id: Optional[uuid.UUID] = None
    requested_dept_id: Optional[uuid.UUID] = None
    section_count: Optional[int] = Field(None, ge=1)
    max_sections: Optional[int] = Field(None, ge=1)
    pinned_section_label: Optional[str] = None
    notes: Optional[str] = None
    study_year: Optional[int] = Field(None, ge=1, le=8)
    study_semester: Optional[int] = Field(None, ge=1, le=12)

    # Room preference overrides
    override_room_ids: Optional[list[str]] = None
    override_room_ids_soft: Optional[bool] = None
    override_lab_room_ids: Optional[list[str]] = None
    override_lab_room_ids_soft: Optional[bool] = None

    is_merged_session: Optional[bool] = None
    is_active: Optional[bool] = None
    elective_pool_id: Optional[uuid.UUID] = None


class TeachingAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: Optional[uuid.UUID]
    faculty_id: Optional[uuid.UUID]                     # None = pending request
    requested_dept_id: Optional[uuid.UUID] = None
    course_id: uuid.UUID
    section_count: int
    max_sections: Optional[int] = None
    pinned_section_label: Optional[str]
    notes: Optional[str]
    study_year: Optional[int] = None
    study_semester: Optional[int] = None

    # Room preference overrides
    override_room_ids: Optional[list[str]] = None
    override_room_ids_soft: Optional[bool] = None
    override_lab_room_ids: Optional[list[str]] = None
    override_lab_room_ids_soft: Optional[bool] = None

    is_merged_session: bool = False
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # Enriched display fields — joined from faculty + course tables by the service.
    # Always present on list responses; None only if the FK row no longer exists.
    faculty_name: Optional[str] = None
    faculty_department_id: Optional[uuid.UUID] = None    # Faculty's home department (from User.department_id)
    faculty_department_name: Optional[str] = None         # Enriched dept name

    course_code: Optional[str] = None
    course_name: Optional[str] = None
    course_session_type: Optional[str] = None
    course_elective_type: Optional[str] = None          # "PROFESSIONAL" | "OPEN" | None
    course_elective_semester: Optional[int] = None
    course_department_id: Optional[uuid.UUID] = None    # Owning dept of the course (not the planning dept)
    department_name: Optional[str] = None               # Enriched from departments table (academic dept)
    requested_dept_name: Optional[str] = None           # Enriched from departments table (service dept)
    elective_pool_id: Optional[uuid.UUID] = None
    elective_pool_label: Optional[str] = None           # "PE-1", "OE-1" etc.


TeachingAssignmentListResponse = PaginatedResponse[TeachingAssignmentResponse]


# ---------------------------------------------------------------------------
# CourseShareConfig
# ---------------------------------------------------------------------------


class CourseShareConfigCreate(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    course_id: uuid.UUID
    department_ids: Optional[list[uuid.UUID]] = Field(
        None, description="None = all depts share; specific list = selective"
    )
    notes: Optional[str] = None


class CourseShareConfigUpdate(BaseModel):
    department_ids: Optional[list[uuid.UUID]] = None
    notes: Optional[str] = None


class CourseShareConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    course_id: uuid.UUID
    department_ids: Optional[list[uuid.UUID]]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


CourseShareConfigListResponse = PaginatedResponse[CourseShareConfigResponse]


# ---------------------------------------------------------------------------
# Workload Preview
# ---------------------------------------------------------------------------


class WorkloadPreviewTeacher(BaseModel):
    faculty_id: uuid.UUID
    faculty_name: str
    section_count: int
    pinned_section_label: Optional[str]
    owning_dept_name: Optional[str] = None  # set for cross-dept TAs — the "other" department name
    cross_dept_label: Optional[str] = None  # human label: "Teaching for X" or "Faculty from X"


class WorkloadPreviewCourse(BaseModel):
    course_id: uuid.UUID
    course_name: str
    teachers: list[WorkloadPreviewTeacher]
    total_sections_covered: int   # sum of all teacher section_count for this course
    required_slots: int           # per-semester required sections (not the whole-dept class_count)
    is_sufficient: bool           # total_sections_covered >= required_slots
    study_year: Optional[int] = None          # from TeachingAssignment.study_year
    study_semester: Optional[int] = None      # from TeachingAssignment.study_semester
    students_per_section: Optional[int] = None  # round(sem_students / required_slots)


class WorkloadPreview(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: Optional[uuid.UUID]
    class_count: Optional[int]              # from COHORT if created, else derived from class_size
    courses: list[WorkloadPreviewCourse]
    warnings: list[str]                     # courses with insufficient teacher coverage
    # Student context — populated when dept + COHORT or class_size config exists
    students_total: Optional[int] = None         # COHORT.size
    effective_class_size: Optional[int] = None   # dept.class_size ?? institution.default_class_size
    recommended_sections: Optional[int] = None   # ceil(students_total / effective_class_size)
    students_per_section: Optional[int] = None   # round(students_total / class_count)


# ---------------------------------------------------------------------------
# Institution Planning Stats (admin dashboard)
# ---------------------------------------------------------------------------


class SemesterSessionCount(BaseModel):
    study_year: int
    study_semester: int
    label: str              # e.g. "Y3·S5"
    sessions_assigned: int


class DeptPlanningStats(BaseModel):
    department_id: uuid.UUID
    sessions_assigned: int          # SUM(section_count) where faculty_id IS NOT NULL
    courses_with_sessions: int      # COUNT(DISTINCT course_id) with ≥1 fulfilled TA
    total_courses: int              # active courses in this dept
    pending_count: int              # TAs where faculty_id IS NULL
    sem_breakdown: list[SemesterSessionCount]
    max_faculty_load: int
    avg_faculty_load: float
    is_load_imbalanced: bool        # max_faculty_load / avg > 2.5
    unassigned_faculty_count: int   # faculty with 0 sections (derived from faculty_load_map)
    merged_session_count: int       # COUNT where is_merged_session is True


class InstitutionPlanningStats(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    total_sessions_assigned: int
    total_pending: int
    dept_stats: list[DeptPlanningStats]


# ---------------------------------------------------------------------------
# CohortSetupResponse
# ---------------------------------------------------------------------------


class CohortSetupResponse(BaseModel):
    cohort: SchedulingTargetResponse
    children: list[SchedulingTargetResponse]   # TRADITIONAL child BATCHes
    demands_created: int
    buckets_created: int
    offerings_created: int
    tba_offerings_created: int    # CourseOfferings with faculty_id=NULL (placeholders)
    class_size_used: Optional[int]
    class_count: int
    required_slots: int
    scheduling_mode: str
    is_ready_for_solve: bool      # False when tba_offerings_created > 0
    warnings: list[str]
    group_distribution_pending: bool = False  # True for HYBRID/FFCS — admin must run group distribution before solve
