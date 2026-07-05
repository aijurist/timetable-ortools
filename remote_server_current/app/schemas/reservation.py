"""
reservation.py
==============
Pydantic V2 schemas for the Ad-hoc Resource Reservation domain.

One table: reservations  — room booking requests outside the timetable.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.reservation import ReservationStatus
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ReservationCreate(BaseModel):
    institution_id: uuid.UUID
    room_id: uuid.UUID
    requested_by: uuid.UUID = Field(description="users.id of the requester (any role)")
    date: str = Field(
        min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="ISO date, e.g. '2026-11-10'",
    )
    start_time: str = Field(
        min_length=5, max_length=5, pattern=r"^\d{2}:\d{2}$",
        description="24-h time, e.g. '14:00'",
    )
    end_time: str = Field(
        min_length=5, max_length=5, pattern=r"^\d{2}:\d{2}$",
        description="24-h time, e.g. '16:00'",
    )
    purpose: Optional[str] = Field(default=None, max_length=255)


class ReservationApprove(BaseModel):
    """Body for PATCH /reservations/{id}/approve."""

    approved_by: uuid.UUID = Field(description="users.id of the approver (HOD/admin)")


class ReservationStatusUpdate(BaseModel):
    """Body for PATCH /reservations/{id}/status — admin / conflict-resolution use."""

    status: ReservationStatus


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

class ReservationResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    room_id: uuid.UUID
    requested_by: uuid.UUID
    approved_by: Optional[uuid.UUID]
    date: str
    start_time: str
    end_time: str
    purpose: Optional[str]
    status: ReservationStatus
    conflict_checked_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


ReservationListResponse = PaginatedResponse[ReservationResponse]
