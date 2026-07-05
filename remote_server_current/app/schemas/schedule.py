"""
schedule.py
===========
Pydantic V2 schemas for ScheduledSession (solver output).
"""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import PaginatedResponse


class ScheduledSessionResponse(BaseModel):
    """One row of solver output: a course session assigned to a slot + room + faculty."""

    id: uuid.UUID
    scenario_id: uuid.UUID
    session_id: str
    course_id: str
    faculty_id: str
    room_id: str
    slot_code: str
    offering_id: Optional[uuid.UUID] = None
    created_at: datetime
    is_pinned: bool = False

    # Original assignment values — set on first manual edit only.
    original_room_id: Optional[str] = None
    original_slot_code: Optional[str] = None
    original_faculty_id: Optional[str] = None

    # Enriched fields — populated by get_by_scenario JOINs
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    department_name: Optional[str] = None
    department_code: Optional[str] = None
    faculty_name: Optional[str] = None
    faculty_department_id: Optional[uuid.UUID] = None
    room_name: Optional[str] = None
    room_code: Optional[str] = None
    day_of_week: Optional[str] = None
    batch_name: Optional[str] = None
    bucket_name: Optional[str] = None
    group_number: Optional[int] = None
    section_label: Optional[str] = None
    study_semester: Optional[int] = None

    model_config = {"from_attributes": True}


class DepartmentTimetableMeta(BaseModel):
    academic_term_id: uuid.UUID
    academic_term_name: str
    department_id: uuid.UUID
    department_name: Optional[str] = None
    study_semester: Optional[int] = None
    published_at: Optional[datetime] = None
    session_count: int = 0


class DepartmentTimetableResponse(BaseModel):
    meta: DepartmentTimetableMeta
    sessions: List[ScheduledSessionResponse]
    slot_definitions: Optional[dict] = None


class TeacherTimetableMeta(BaseModel):
    academic_term_id: uuid.UUID
    academic_term_name: str
    faculty_id: uuid.UUID
    faculty_name: str
    session_count: int = 0


class TeacherTimetableResponse(BaseModel):
    meta: TeacherTimetableMeta
    sessions: List[ScheduledSessionResponse]
    slot_definitions: Optional[dict] = None


class ScheduledSessionPinUpdate(BaseModel):
    is_pinned: bool


class ScheduledSessionPatchRequest(BaseModel):
    room_id: Optional[str] = None
    faculty_id: Optional[str] = None
    slot_code: Optional[str] = None  # for DnD slot moves
    force: bool = False


class ScheduledSessionPatchResponse(BaseModel):
    session: ScheduledSessionResponse
    warnings: List[str] = []


ScheduleListResponse = PaginatedResponse[ScheduledSessionResponse]
