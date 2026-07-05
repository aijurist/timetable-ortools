"""
room.py
=======
Pydantic V2 schemas for the Room domain.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.room import RoomType
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class RoomCreate(BaseModel):
    institution_id: uuid.UUID
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    capacity: int = Field(ge=1, le=5000)
    room_type: RoomType = RoomType.LECTURE
    tags: Optional[list[str]] = Field(None, description="Freeform tags, e.g. ['AIR_CONDITIONED', 'PROJECTOR']")
    campus: Optional[str] = Field(None, max_length=100, description="Campus name for multi-campus institutions")
    building: Optional[str] = Field(None, max_length=100, description="Building within campus")
    target_utilisation_pct: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Target fraction of total sessions this room should carry (0.0–1.0). "
                    "NULL = use computed average across all active rooms.",
    )


class RoomUpdate(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    capacity: Optional[int] = Field(default=None, ge=1, le=5000)
    room_type: Optional[RoomType] = None
    tags: Optional[list[str]] = None
    campus: Optional[str] = Field(None, max_length=100)
    building: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None
    target_utilisation_pct: Optional[float] = Field(default=None, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class RoomResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    code: str
    name: str
    capacity: int
    room_type: RoomType
    tags: Optional[list[str]]
    campus: Optional[str]
    building: Optional[str]
    target_utilisation_pct: Optional[float]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoomListResponse(PaginatedResponse[RoomResponse]):
    type_counts: dict[str, int] = {}
