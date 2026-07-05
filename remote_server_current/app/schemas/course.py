"""
course.py
=========
Pydantic V2 schemas for the Course domain.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.course import ElectiveType, SessionType
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CourseCreate(BaseModel):
    institution_id: uuid.UUID
    department_id: Optional[uuid.UUID] = Field(default=None, description="FK → departments.id")
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    weekly_hours: int = Field(default=3, ge=1, le=40)
    session_type: SessionType = SessionType.THEORY
    credits: int = Field(default=3, ge=0, le=20)
    structure: Optional[dict[str, Any]] = Field(
        default=None, description="FFCS credit structure, e.g. {'L': 3, 'T': 1, 'P': 2}"
    )
    room_tags: Optional[list[str]] = Field(
        None, description="Room tags this course needs, e.g. ['ECE_DEPT']."
    )
    room_tags_soft: bool = Field(
        False, description="If True, room_tags are a soft preference (penalty) not a hard requirement. Overridable by ScenarioRule(ROOM_TAGS)."
    )
    elective_type: Optional[ElectiveType] = None
    elective_semester: Optional[int] = Field(default=None, ge=1, le=8)

    # Direct room pins (takes priority over room_tags)
    preferred_room_ids: Optional[list[str]] = Field(
        None, description="List of room UUIDs for L/T components. Empty/null = fall back to room_tags."
    )
    preferred_room_ids_soft: bool = True
    lab_preferred_room_ids: Optional[list[str]] = Field(
        None, description="List of room UUIDs for P (lab) component."
    )
    lab_preferred_room_ids_soft: bool = True
    lab_room_tags: Optional[list[str]] = Field(
        None, description="Required room tags for the lab/practical component only."
    )
    lab_room_tags_soft: bool = True

    @model_validator(mode="after")
    def derive_weekly_hours_from_structure(self) -> "CourseCreate":
        """If structure is provided, weekly_hours must equal sum(L+T+P). Auto-derive if not set explicitly."""
        if self.structure and isinstance(self.structure, dict):
            total = sum(int(self.structure.get(k, 0)) for k in ("L", "T", "P"))
            if total > 0:
                self.weekly_hours = total
        return self


class CourseUpdate(BaseModel):
    department_id: Optional[uuid.UUID] = Field(default=None, description="FK → departments.id")
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    weekly_hours: Optional[int] = Field(default=None, ge=1, le=40)
    session_type: Optional[SessionType] = None
    credits: Optional[int] = Field(default=None, ge=0, le=20)
    structure: Optional[dict[str, Any]] = None
    room_tags: Optional[list[str]] = None
    room_tags_soft: Optional[bool] = None
    elective_type: Optional[ElectiveType] = None
    elective_semester: Optional[int] = Field(default=None, ge=1, le=8)

    # Direct room pins
    preferred_room_ids: Optional[list[str]] = None
    preferred_room_ids_soft: Optional[bool] = None
    lab_preferred_room_ids: Optional[list[str]] = None
    lab_preferred_room_ids_soft: Optional[bool] = None
    lab_room_tags: Optional[list[str]] = None
    lab_room_tags_soft: Optional[bool] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def derive_weekly_hours_from_structure(self) -> "CourseUpdate":
        """If structure is being updated, sync weekly_hours to sum(L+T+P)."""
        if self.structure and isinstance(self.structure, dict):
            total = sum(int(self.structure.get(k, 0)) for k in ("L", "T", "P"))
            if total > 0:
                self.weekly_hours = total
        return self


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class CourseResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    department_id: Optional[uuid.UUID]
    department_name: Optional[str] = None
    code: str
    name: str
    weekly_hours: int
    session_type: SessionType
    credits: int
    structure: Optional[dict[str, Any]]
    room_tags: Optional[list[str]]
    room_tags_soft: bool
    elective_type: Optional[ElectiveType] = None
    elective_semester: Optional[int] = None
    preferred_room_ids: Optional[list[str]] = None
    preferred_room_ids_soft: bool = True
    lab_preferred_room_ids: Optional[list[str]] = None
    lab_preferred_room_ids_soft: bool = True
    lab_room_tags: Optional[list[str]] = None
    lab_room_tags_soft: bool = True
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CourseListResponse(PaginatedResponse[CourseResponse]):
    session_counts: dict[str, int] = {}
