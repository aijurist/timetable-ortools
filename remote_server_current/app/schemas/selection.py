"""Pydantic schemas for HYBRID student selection."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.selection import GroupSelectionStatus, SelectionWindowStatus
from app.schemas.schedule import ScheduledSessionResponse


class SelectionWindowUpsert(BaseModel):
    study_semester: int
    status: SelectionWindowStatus = SelectionWindowStatus.DRAFT
    preview_opens_at: Optional[datetime] = None
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    allow_changes_until: Optional[datetime] = None
    timezone: str = "UTC"
    published_scenario_id: Optional[uuid.UUID] = None
    max_selections_per_student: int = 1


class SelectionWindowResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: uuid.UUID
    study_semester: int
    status: SelectionWindowStatus
    effective_phase: str
    preview_opens_at: Optional[datetime] = None
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    allow_changes_until: Optional[datetime] = None
    timezone: str
    published_scenario_id: Optional[uuid.UUID] = None
    max_selections_per_student: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OfferingMenuItem(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    faculty_id: Optional[uuid.UUID] = None
    faculty_name: Optional[str] = None
    group_number: Optional[int] = None
    # 1-based batch number for split-lab offerings; NULL for non-batched offerings.
    # Persisted in the DB so ordering is deterministic across all accounts.
    batch_number: Optional[int] = None
    max_seats: Optional[int] = None
    booked_seats: int = 0
    seats_remaining: Optional[int] = None
    is_frozen: bool = False


class BucketMenuItem(BaseModel):
    id: uuid.UUID
    name: str
    selection_policy: str
    min_selection: int
    max_selection: int
    course_id: Optional[uuid.UUID] = None
    """When set, this bucket represents one parallel section group (HYBRID grouped distribution)."""
    parallel_group_number: Optional[int] = None
    offerings: list[OfferingMenuItem]


class SelectionMenuResponse(BaseModel):
    academic_term_id: uuid.UUID
    department_id: uuid.UUID
    study_year: int
    study_semester: int
    cohort_id: Optional[uuid.UUID] = None
    window: Optional[SelectionWindowResponse] = None
    buckets: list[BucketMenuItem]
    required_bucket_ids: list[uuid.UUID]
    """per_group_bucket = pick one offering in each Group 1…N bucket; per_course = one bucket per course."""
    selection_mode: str = "per_course"
    elective_bucket_ids: list[uuid.UUID] = Field(default_factory=list)
    sessions_by_offering_id: dict[str, list[ScheduledSessionResponse]]
    slot_definitions: Optional[dict[str, Any]] = None
    current_selection: Optional["GroupSelectionResponse"] = None
    selection_reset_reason: Optional[str] = None


class SelectionPicksPayload(BaseModel):
    picks: dict[str, uuid.UUID] = Field(
        description="Map of bucket_id (str) → offering_id"
    )


class GroupSelectionResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: uuid.UUID
    study_year: int
    study_semester: int
    group_number: Optional[int] = None
    status: GroupSelectionStatus
    selection_payload: dict[str, Any]
    confirmed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ConfirmSelectionResponse(BaseModel):
    selection: GroupSelectionResponse
    registration_ids: list[uuid.UUID]


class MyTimetableResponse(BaseModel):
    sessions: list[ScheduledSessionResponse]
    slot_definitions: Optional[dict[str, Any]] = None


class CompletionStatsResponse(BaseModel):
    department_id: uuid.UUID
    academic_term_id: uuid.UUID
    study_semester: int
    effective_phase: str
    confirmed_count: int
    draft_count: int
    eligible_count: int
    pending_count: int
    completion_pct: float
    confirms_last_minute: int = 0
    published_scenario_id: Optional[uuid.UUID] = None


class CompletionOverviewItem(CompletionStatsResponse):
    department_name: Optional[str] = None


class CompletionOverviewResponse(BaseModel):
    items: list[CompletionOverviewItem]


class OfferingSeatDashboardItem(BaseModel):
    offering_id: uuid.UUID
    bucket_id: uuid.UUID
    bucket_name: str
    selection_policy: str
    course_id: uuid.UUID
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    faculty_name: Optional[str] = None
    group_number: Optional[int] = None
    batch_number: Optional[int] = None
    max_seats: Optional[int] = None
    effective_max_seats: Optional[int] = None
    booked_seats: int
    seats_remaining: Optional[int] = None
    is_frozen: bool


class RegistrationStatsResponse(BaseModel):
    confirms_last_minute: int = 0
    confirmed_students: int = 0
    total_offering_bookings: int = 0
    completion: Optional[CompletionStatsResponse] = None
    offerings: list[OfferingSeatDashboardItem]


class BulkCourseEligibilityRequest(BaseModel):
    student_profile_ids: list[uuid.UUID] = Field(..., min_length=1)
    course_id: uuid.UUID
    academic_term_id: uuid.UUID
    study_semester: int = Field(..., ge=1, le=8)
    action: str = Field(..., pattern="^(assign|remove)$")
    source: str = Field(default="MANUAL", pattern="^(PE|OE|MANUAL)$")


class CourseEligibilityResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    course_id: uuid.UUID
    academic_term_id: uuid.UUID
    department_id: uuid.UUID
    study_semester: int
    source: str

    model_config = {"from_attributes": True}


class PublishedContextCourse(BaseModel):
    course_id: uuid.UUID
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    elective_type: Optional[str] = None
    bucket_id: uuid.UUID
    bucket_name: str


class PublishedContextCohort(BaseModel):
    id: uuid.UUID
    name: str
    target_type: str


class PublishedContextResponse(BaseModel):
    published_scenario_id: Optional[uuid.UUID] = None
    cohorts: list[PublishedContextCohort] = Field(default_factory=list)
    elective_courses: list[PublishedContextCourse] = Field(default_factory=list)


class SelectionImpactResponse(BaseModel):
    active_selection_count: int


class AdminSelectionListItem(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    student_enrollment: Optional[str] = None
    student_email: str
    department_id: uuid.UUID
    study_semester: int
    status: GroupSelectionStatus
    selection_payload: dict[str, Any]
    confirmed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AdminBookSelectionRequest(BaseModel):
    student_id: uuid.UUID
    academic_term_id: uuid.UUID
    picks: dict[str, uuid.UUID]

