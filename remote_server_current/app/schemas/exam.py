"""
exam.py
=======
Pydantic V2 schemas for the Exam Scheduling domain.

Three tables:
  exam_scenarios    — per exam-period scenario
  exam_slots        — available date/time windows within a scenario
  exam_assignments  — solver output (course × slot × room × batch × invigilator)
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.exam import ExamScenarioStatus
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# ExamScenario
# ---------------------------------------------------------------------------

class ExamScenarioCreate(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    solver_config: Optional[dict[str, Any]] = None


class ExamScenarioUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    status: Optional[ExamScenarioStatus] = None
    solver_config: Optional[dict[str, Any]] = None


class ExamScenarioResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    name: str
    status: ExamScenarioStatus
    solver_config: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


ExamScenarioListResponse = PaginatedResponse[ExamScenarioResponse]


# ---------------------------------------------------------------------------
# ExamSlot
# ---------------------------------------------------------------------------

class ExamSlotCreate(BaseModel):
    """Date + time window within an exam scenario."""

    date: str = Field(
        min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="ISO date, e.g. '2026-11-10'",
    )
    start_time: str = Field(
        min_length=5, max_length=5, pattern=r"^\d{2}:\d{2}$",
        description="24-h time, e.g. '09:00'",
    )
    end_time: str = Field(
        min_length=5, max_length=5, pattern=r"^\d{2}:\d{2}$",
        description="24-h time, e.g. '12:00'",
    )
    label: Optional[str] = Field(default=None, max_length=100)


class ExamSlotUpdate(BaseModel):
    date: Optional[str] = Field(default=None, max_length=10)
    start_time: Optional[str] = Field(default=None, max_length=5)
    end_time: Optional[str] = Field(default=None, max_length=5)
    label: Optional[str] = Field(default=None, max_length=100)


class ExamSlotResponse(BaseModel):
    id: uuid.UUID
    exam_scenario_id: uuid.UUID
    date: str
    start_time: str
    end_time: str
    label: Optional[str]

    model_config = {"from_attributes": True}


ExamSlotListResponse = PaginatedResponse[ExamSlotResponse]


# ---------------------------------------------------------------------------
# ExamAssignment  (solver output — typically read-only via API)
# ---------------------------------------------------------------------------

class ExamAssignmentResponse(BaseModel):
    id: uuid.UUID
    exam_scenario_id: uuid.UUID
    course_id: uuid.UUID
    exam_slot_id: uuid.UUID
    room_id: uuid.UUID
    invigilator_id: Optional[uuid.UUID]
    target_id: Optional[uuid.UUID]
    created_at: datetime

    model_config = {"from_attributes": True}


ExamAssignmentListResponse = PaginatedResponse[ExamAssignmentResponse]
