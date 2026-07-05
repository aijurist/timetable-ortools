"""
app/schemas/student.py
======================
Pydantic V2 schemas for StudentProfile, StudentRegistration, and
StudentWishlist.

Architecture Notes
------------------
- Student is NOT a solver resource. The solver uses SchedulingTarget
  (batch-level). These schemas serve the FFCS registration UI and Campus
  Brain AI study assistant.
- FFCS registration is two-phase:
    Phase 1: StudentWishlist  — draft, no seat lock
    Phase 2: StudentRegistration — confirmed, atomic booked_seats++
- Always verify ``booked_seats < max_seats`` and ``is_frozen = False``
  on the CourseOffering before Phase 2.
- ``offering_ids`` on StudentWishlist is a JSON array of UUIDs stored
  as a draft snapshot — not FK-constrained.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.student import RegistrationStatus
from app.models.user import GenderType
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# StudentProfile
# ---------------------------------------------------------------------------


class StudentProfileCreate(BaseModel):
    user_id: uuid.UUID = Field(..., description="FK → users.id (CASCADE) — 1-to-1")
    batch_id: Optional[uuid.UUID] = Field(
        None, description="FK → scheduling_targets.id (SET NULL on delete)"
    )
    enrollment_number: Optional[str] = Field(
        None, max_length=50, description="University-issued roll number — unique within institution"
    )
    degree_type: Optional[str] = Field(None, max_length=50, description="e.g. 'B.Tech', 'M.Tech', 'MBA'")
    program: Optional[str] = Field(None, max_length=200, description="e.g. 'B.Tech Computer Science Engineering'")
    semester: Optional[int] = Field(None, ge=1, description="Current academic semester (1-indexed)")
    year_of_study: Optional[int] = Field(None, ge=1, description="Year of study (1-4 UG, 1-2 PG)")


class StudentProfileUpdate(BaseModel):
    batch_id: Optional[uuid.UUID] = None
    enrollment_number: Optional[str] = Field(None, max_length=50)
    degree_type: Optional[str] = Field(None, max_length=50)
    program: Optional[str] = Field(None, max_length=200)
    semester: Optional[int] = Field(None, ge=1)
    year_of_study: Optional[int] = Field(None, ge=1)


class StudentProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    batch_id: Optional[uuid.UUID]
    enrollment_number: Optional[str]
    degree_type: Optional[str]
    program: Optional[str]
    semester: Optional[int]
    year_of_study: Optional[int]
    created_at: datetime
    updated_at: datetime


StudentProfileListResponse = PaginatedResponse[StudentProfileResponse]


class StudentAdminCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=20)
    gender: Optional[GenderType] = None
    institution_id: Optional[uuid.UUID] = Field(
        None, description="Required only for super_admin acting across institutions"
    )
    department_id: uuid.UUID = Field(..., description="FK → departments.id")
    batch_id: Optional[uuid.UUID] = Field(None, description="FK → scheduling_targets.id")
    enrollment_number: str = Field(..., min_length=1, max_length=50)
    degree_type: str = Field(..., min_length=1, max_length=50)
    program: str = Field(..., min_length=1, max_length=200)
    semester: Optional[int] = Field(None, ge=1)
    year_of_study: Optional[int] = Field(None, ge=1)


class StudentAdminUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=20)
    gender: Optional[GenderType] = None
    department_id: Optional[uuid.UUID] = Field(default=None, description="FK → departments.id")
    batch_id: Optional[uuid.UUID] = Field(default=None, description="FK → scheduling_targets.id")
    enrollment_number: Optional[str] = Field(default=None, min_length=1, max_length=50)
    degree_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    program: Optional[str] = Field(default=None, min_length=1, max_length=200)
    semester: Optional[int] = Field(default=None, ge=1)
    year_of_study: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None


class StudentAdminResponse(BaseModel):
    student_profile_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    phone: Optional[str] = None
    gender: Optional[GenderType] = None
    department_id: Optional[uuid.UUID]
    batch_id: Optional[uuid.UUID]
    enrollment_number: Optional[str]
    degree_type: Optional[str]
    program: Optional[str]
    semester: Optional[int]
    year_of_study: Optional[int]
    is_active: bool
    created_at: datetime
    updated_at: datetime


StudentAdminListResponse = PaginatedResponse[StudentAdminResponse]


class StudentDepartmentCount(BaseModel):
    department_id: Optional[uuid.UUID] = None
    department_name: str
    count: int


class StudentSummaryResponse(BaseModel):
    total: int
    by_department: list[StudentDepartmentCount]
    semester: Optional[int] = None
    year_of_study: Optional[int] = None
    degree_type: Optional[str] = None
    batch_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# StudentRegistration  (FFCS confirmed picks — Phase 2)
# ---------------------------------------------------------------------------


class StudentRegistrationCreate(BaseModel):
    student_id: uuid.UUID = Field(..., description="FK → student_profiles.id")
    offering_id: uuid.UUID = Field(..., description="FK → course_offerings.id")
    # status defaults to CONFIRMED on creation; WAITLISTED or DROPPED are
    # set by the service layer, not directly by the API consumer.


class StudentRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_id: uuid.UUID
    offering_id: uuid.UUID
    status: RegistrationStatus
    registered_at: datetime


StudentRegistrationListResponse = PaginatedResponse[StudentRegistrationResponse]


# ---------------------------------------------------------------------------
# StudentWishlist  (pre-registration shopping cart — Phase 1)
# ---------------------------------------------------------------------------


class StudentWishlistCreate(BaseModel):
    student_id: uuid.UUID = Field(..., description="FK → student_profiles.id")
    academic_term_id: uuid.UUID = Field(
        ..., description="Loose UUID — wishlists survive term deletion"
    )
    name: Optional[str] = Field(
        None, max_length=100, description="Human name for this plan, e.g. 'Plan A - Morning'"
    )
    offering_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Draft list of CourseOffering UUIDs; not FK-constrained"
    )


class StudentWishlistUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    offering_ids: Optional[list[uuid.UUID]] = None


class StudentWishlistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_id: uuid.UUID
    academic_term_id: uuid.UUID
    name: Optional[str]
    offering_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


StudentWishlistListResponse = PaginatedResponse[StudentWishlistResponse]


# ---------------------------------------------------------------------------
# Bulk batch assignment
# ---------------------------------------------------------------------------


class BulkBatchAssignRequest(BaseModel):
    student_profile_ids: List[uuid.UUID] = Field(
        ..., min_length=1, description="List of student_profiles.id to reassign"
    )
    batch_id: Optional[uuid.UUID] = Field(
        None, description="Target scheduling_targets.id; null clears the batch"
    )
    academic_term_id: Optional[uuid.UUID] = Field(
        None, description="Term scope for core eligibility seeding after batch assign"
    )


class BulkBatchAutoAllocateRequest(BaseModel):
    student_profile_ids: List[uuid.UUID] = Field(
        ..., min_length=1, description="List of student_profiles.id to auto-allocate"
    )
    academic_term_id: uuid.UUID = Field(
        ..., description="Academic term UUID to search scheduling targets in"
    )

