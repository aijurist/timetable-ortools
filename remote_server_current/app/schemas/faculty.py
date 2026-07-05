"""
faculty.py
==========
Pydantic V2 schemas for the Faculty domain.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.upload import FACULTY_DEFAULT_PASSWORD
from app.models.faculty import DesignationType, EmploymentType
from app.models.user import GenderType
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# Faculty preferences sub-schema
# ---------------------------------------------------------------------------

_DAY_CODES = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}


class FacultyPreferences(BaseModel):
    """
    Typed solver preferences for a faculty member.

    These feed directly into the solver's per-faculty resolution chain:
      preferred_days          → DAY_WINDOW  (step 3 model baseline)
      preferred_slots         → PREFERRED_SLOT (step 2 model baseline)
      max_daily_hours         → MAX_DAILY_HOURS (step 2 model baseline)
      max_consecutive_slots   → MAX_CONSECUTIVE_SLOTS (step 2 model baseline)
      preferred_rooms         → informational only; used for future ROOM_PREFERENCE constraint
    """

    preferred_slots: list[str] = Field(
        default_factory=list,
        description="Slot codes this faculty prefers, e.g. ['A1', 'A2']. "
                    "Solver penalises assignments outside this set (PREFERRED_SLOT).",
    )
    preferred_days: list[str] = Field(
        default_factory=list,
        description="Working days this faculty prefers, e.g. ['MON', 'TUE', 'WED']. "
                    "Overrides global DAY_WINDOW allowed_days for this faculty.",
    )
    preferred_rooms: list[str] = Field(
        default_factory=list,
        description="Room UUIDs this faculty prefers to teach in.",
    )
    max_daily_hours: Optional[int] = Field(
        default=None,
        ge=1,
        le=24,
        description="Max teaching hours per day for this faculty. "
                    "Overrides global MAX_DAILY_HOURS param.",
    )
    max_consecutive_slots: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="Max consecutive slots without a break for this faculty. "
                    "Overrides global MAX_CONSECUTIVE_SLOTS param.",
    )
    min_gap_between_sessions: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Minimum idle periods required between two sessions of the same "
                    "course by this faculty on the same day. "
                    "Overrides global MIN_GAP_BETWEEN param.",
    )

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class FacultyCreate(BaseModel):
    institution_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    staff_code: Optional[str] = Field(default=None, max_length=20)
    employee_id: Optional[str] = Field(default=None, max_length=20)
    age: Optional[int] = Field(default=None, ge=18, le=100)
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    designation: Optional[DesignationType] = None
    max_weekly_hours: int = Field(default=20, ge=1, le=80)
    availability_blacklist: Optional[list[str]] = None
    preferences: Optional[FacultyPreferences] = None


class FacultyUpdate(BaseModel):
    department_id: Optional[uuid.UUID] = Field(default=None, description="Applied to linked User.department_id")
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    staff_code: Optional[str] = Field(default=None, max_length=20)
    employee_id: Optional[str] = Field(default=None, max_length=20)
    age: Optional[int] = Field(default=None, ge=18, le=100)
    employment_type: Optional[EmploymentType] = None
    designation: Optional[DesignationType] = None
    max_weekly_hours: Optional[int] = Field(default=None, ge=1, le=80)
    preferences: Optional[FacultyPreferences] = None
    is_active: Optional[bool] = None


class FacultyAvailabilityUpdate(BaseModel):
    """Body for PATCH /faculty/{id}/availability."""

    availability_blacklist: list[str] = Field(
        description="Slot codes where this faculty is NOT available. e.g. ['A3', 'B5']"
    )


class FacultyWithUserCreate(BaseModel):
    """Atomically creates a Faculty record and a linked User account.

    The User is assigned UserRole.TEACHER by default. Email is stored only
    on the User table (single source of truth — see Student pattern).
    The Faculty is created first (flush → obtain id), then the User is
    created, and finally Faculty.user_id is set to the User's id.
    """

    # Shared
    institution_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    # User account
    password: str = Field(default=FACULTY_DEFAULT_PASSWORD, min_length=8, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=20)
    gender: Optional[GenderType] = None
    department: Optional[str] = Field(default=None, max_length=100)
    # Department — applied to User.department_id (single source of truth)
    department_id: Optional[uuid.UUID] = Field(default=None, description="Department for the linked User")
    # Faculty-specific
    staff_code: Optional[str] = Field(default=None, max_length=20)
    employee_id: Optional[str] = Field(default=None, max_length=20)
    age: Optional[int] = Field(default=None, ge=18, le=100)
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    max_weekly_hours: int = Field(default=20, ge=1, le=80)
    availability_blacklist: Optional[list[str]] = None
    preferences: Optional[FacultyPreferences] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class FacultyResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    department_id: Optional[uuid.UUID]
    department_name: Optional[str] = None
    name: str
    email: str
    phone: Optional[str] = None
    gender: Optional[GenderType] = None
    staff_code: Optional[str] = None
    employee_id: Optional[str] = None
    age: Optional[int]
    employment_type: EmploymentType
    designation: Optional[DesignationType] = None
    max_weekly_hours: int
    current_load_hours: int = 0
    availability_blacklist: Optional[list[str]]
    preferences: Optional[FacultyPreferences]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    hod_of_department_code: Optional[str] = None
    hod_of_department_name: Optional[str] = None

    model_config = {"from_attributes": True}


class FacultyListResponse(PaginatedResponse[FacultyResponse]):
    employment_counts: dict[str, int] = {}
    total_max_weekly_hours: int = 0
    avg_load_percent: int = 0


class FacultyWithUserResponse(BaseModel):
    """Response for POST /faculty/with-user — contains both created records."""

    faculty: FacultyResponse
    user: "UserResponse"

    model_config = {"from_attributes": True}


# Deferred import to avoid circular dependency
from app.schemas.user import UserResponse  # noqa: E402
FacultyWithUserResponse.model_rebuild()
