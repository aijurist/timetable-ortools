"""
app/schemas/institution.py
==========================
Pydantic V2 schemas for Institution, Department, and AcademicTerm.

These power the infrastructure layer — an Institution owns Departments,
which scope HOD access. AcademicTerms define the semester windows that
Scenarios, TimeGrids, and ExamScenarios operate within.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.institution import AcademicTermStatus, SchedulingMode, TermType
from app.schemas.common import PaginatedResponse

# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------


class InstitutionCreate(BaseModel):
    name: str = Field(..., max_length=200)
    domain: Optional[str] = Field(None, max_length=100, description="Subdomain, e.g. 'vit.exovance.io'")
    scheduling_mode: Optional[SchedulingMode] = SchedulingMode.TRADITIONAL
    timezone: str = Field("UTC", max_length=50)
    default_solver_config: Optional[dict[str, Any]] = Field(
        None, description="Institution-wide solver defaults, e.g. {timeout_seconds: 120}"
    )
    regulatory_body: Optional[str] = Field(None, max_length=100, description="e.g. 'UGC', 'AICTE', 'VTU'")
    default_class_size: Optional[int] = Field(
        None, ge=1, description="Institution-wide default students per class for COHORT auto-setup"
    )
    is_active: bool = True


class InstitutionUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    domain: Optional[str] = Field(None, max_length=100)
    scheduling_mode: Optional[SchedulingMode] = None
    timezone: Optional[str] = Field(None, max_length=50)
    default_solver_config: Optional[dict[str, Any]] = None
    regulatory_body: Optional[str] = Field(None, max_length=100)
    default_class_size: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None


class InstitutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    domain: Optional[str]
    scheduling_mode: Optional[SchedulingMode]
    timezone: str
    default_solver_config: Optional[dict[str, Any]]
    regulatory_body: Optional[str]
    default_class_size: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


InstitutionListResponse = PaginatedResponse[InstitutionResponse]


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------


# Valid working-day abbreviations (matches SlotData.day values from time grid)
_VALID_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}


class BreakDefinition(BaseModel):
    """One institutional break window."""
    name: str = Field(..., description="Display name, e.g. 'Lunch', 'Prayer'")
    slot_codes: list[str] = Field(
        ..., description="Slot codes blocked during this break, e.g. ['P5', 'Q5']"
    )
    duration_minutes: int = Field(
        default=0, ge=0, description="Informational duration in minutes."
    )

    model_config = {"extra": "forbid"}


class DepartmentBreakConfig(BaseModel):
    """
    Department-level break configuration for the solver.

    Feeds into MANDATORY_BREAK constraint resolution:
      Per-dept ScenarioRule > DepartmentBreakConfig (model baseline) > global ScenarioRule
    """
    breaks: list[BreakDefinition] = Field(
        default_factory=list,
        description="Break windows specific to this department.",
    )
    breaks_soft: bool = Field(
        default=False,
        description=(
            "If True, break slots are soft penalties instead of hard blocks for this dept. "
            "Overrides the global MANDATORY_BREAK hard/soft mode."
        ),
    )

    model_config = {"extra": "forbid"}


class DepartmentWriteBase(BaseModel):
    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=20, description="Short code used in JWT 'dept' claim, e.g. 'CSE'")
    description: Optional[str] = None
    dept_type: Literal["ACADEMIC", "SERVICE"] = "ACADEMIC"
    is_active: bool = True
    class_size: Optional[int] = Field(
        None, ge=1, description="Dept-specific class size for COHORT auto-setup. Overrides institution.default_class_size."
    )
    working_days: Optional[list[str]] = Field(
        None,
        description=(
            "Days this department operates, e.g. ['MON','TUE','WED','THU','FRI']. "
            "NULL = inherit all days from the institution time grid (default). "
            "Valid values: MON TUE WED THU FRI SAT SUN."
        ),
    )
    early_block_period: Optional[int] = Field(
        default=None, ge=1,
        description="Sessions at or before this period are blocked/penalised for this dept. "
                    "Set to 1 to block the first period. NULL = use global BLOCK_EARLY_SLOTS before_period param.",
    )
    early_block_soft: bool = Field(
        default=False,
        description="If True, early-slot block is a soft penalty for this dept.",
    )
    late_block_period: Optional[int] = Field(
        default=None, ge=1,
        description="Sessions after this period are blocked/penalised for this dept. "
                    "NULL = use global BLOCK_LATE_SLOTS after_period param.",
    )
    late_block_soft: bool = Field(
        default=False,
        description="If True, late-slot block is a soft penalty for this dept.",
    )
    break_config: Optional[list[BreakDefinition]] = Field(
        None,
        description="Department-specific break windows. NULL = use global MANDATORY_BREAK rule.",
    )
    breaks_soft: bool = Field(
        default=False,
        description="If True, dept breaks are soft penalties instead of hard blocks.",
    )


class DepartmentCreateRequest(DepartmentWriteBase):
    pass


class DepartmentCreate(DepartmentWriteBase):
    institution_id: uuid.UUID


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    code: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = None
    dept_type: Optional[Literal["ACADEMIC", "SERVICE"]] = None
    is_active: Optional[bool] = None
    class_size: Optional[int] = Field(None, ge=1)
    working_days: Optional[list[str]] = Field(
        None,
        description=(
            "Update working days. Pass an explicit list to restrict, "
            "or null to revert to 'all days in grid'."
        ),
    )
    early_block_period: Optional[int] = Field(default=None, ge=1)
    early_block_soft: Optional[bool] = None
    late_block_period: Optional[int] = Field(default=None, ge=1)
    late_block_soft: Optional[bool] = None
    break_config: Optional[list[BreakDefinition]] = Field(
        None,
        description="Department-specific break windows. NULL = use global MANDATORY_BREAK rule.",
    )
    breaks_soft: Optional[bool] = None
    hod_faculty_id: Optional[uuid.UUID] = Field(
        None,
        description="Faculty UUID to assign as HOD. Must belong to this department. Pass null to clear.",
    )


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: uuid.UUID
    name: str
    code: str
    description: Optional[str]
    dept_type: str = "ACADEMIC"
    is_active: bool
    class_size: Optional[int] = None
    working_days: Optional[list[str]]
    early_block_period: Optional[int]
    early_block_soft: bool
    late_block_period: Optional[int]
    late_block_soft: bool
    break_config: Optional[list[BreakDefinition]]
    breaks_soft: bool
    created_at: datetime
    updated_at: datetime
    hod_faculty_id: Optional[uuid.UUID] = None
    hod_faculty_name: Optional[str] = None


DepartmentListResponse = PaginatedResponse[DepartmentResponse]


# ---------------------------------------------------------------------------
# AcademicTerm
# ---------------------------------------------------------------------------


class AcademicTermCreate(BaseModel):
    institution_id: uuid.UUID
    name: str = Field(..., max_length=100, description="e.g. 'Fall 2026'")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    term_type: Optional[TermType] = Field(None, description="Calendar structure: SEMESTER, TRIMESTER, QUARTER, ANNUAL")
    holidays: Optional[list[dict[str, Any]]] = Field(
        None, description="Non-teaching dates, e.g. [{'date': '2026-10-02', 'label': 'Gandhi Jayanti'}]"
    )
    status: AcademicTermStatus = AcademicTermStatus.PLANNING
    is_active: bool = True


class AcademicTermUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    term_type: Optional[TermType] = None
    holidays: Optional[list[dict[str, Any]]] = None
    status: Optional[AcademicTermStatus] = None
    is_active: Optional[bool] = None


class AcademicTermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution_id: uuid.UUID
    name: str
    start_date: Optional[date]
    end_date: Optional[date]
    term_type: Optional[TermType]
    holidays: Optional[list[dict[str, Any]]]
    status: AcademicTermStatus
    is_active: bool
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


AcademicTermListResponse = PaginatedResponse[AcademicTermResponse]


class DependentCountsResponse(BaseModel):
    """Count of dependent records referencing an academic term across all tables."""

    teaching_assignments: int = 0
    scheduling_targets: int = 0
    offering_buckets: int = 0
    target_course_demands: int = 0
    course_share_configs: int = 0
    student_wishlists: int = 0
    time_grids: int = 0
    scenarios: int = 0
    exam_scenarios: int = 0
    analytics_snapshots: int = 0

    @property
    def total(self) -> int:
        return (
            self.teaching_assignments
            + self.scheduling_targets
            + self.offering_buckets
            + self.target_course_demands
            + self.course_share_configs
            + self.student_wishlists
            + self.time_grids
            + self.scenarios
            + self.exam_scenarios
            + self.analytics_snapshots
        )


class InstitutionStatsResponse(BaseModel):
    """Aggregate resource counts for an institution (no HOD filter)."""

    faculty_total: int
    course_total: int
    room_total: int
    department_total: int
