"""Pydantic schemas for Selection Window Access Configuration."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class DeptSeatOverride(BaseModel):
    """Per-department group seat count override."""

    department_id: uuid.UUID
    max_seats: int = Field(..., ge=1)


class SelectionAccessConfigUpsert(BaseModel):
    """Payload for creating/updating an access configuration."""

    allowed_login_years: list[int] = Field(default_factory=list)
    allowed_login_departments: list[uuid.UUID] = Field(default_factory=list)
    
    allowed_booking_years: list[int] = Field(default_factory=list)
    allowed_booking_departments: list[uuid.UUID] = Field(default_factory=list)
    
    early_access_emails: list[str] = Field(default_factory=list)
    group_seat_overrides: list[DeptSeatOverride] = Field(default_factory=list)
    default_max_group_size: Optional[int] = Field(None, ge=1)
    notes: Optional[str] = Field(None, max_length=1024)


class SelectionAccessConfigResponse(BaseModel):
    """Full access configuration response."""

    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID

    allowed_login_years: list[int]
    allowed_login_departments: list[uuid.UUID]
    allowed_booking_years: list[int]
    allowed_booking_departments: list[uuid.UUID]

    early_access_emails: list[str]
    group_seat_overrides: list[DeptSeatOverride]
    default_max_group_size: Optional[int]
    notes: Optional[str]

    model_config = {"from_attributes": True}
