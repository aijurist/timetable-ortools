"""
time_grid.py
============
Pydantic V2 schemas for the TimeGrid domain.

Time is stored as a JSON "Slot Dictionary" — slot codes are opaque keys
that map to day + time-window definitions. The solver treats slot codes
as integer indices built from this dict at pipeline start.
"""

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# Slot definition (nested inside TimeGrid.slots)
# ---------------------------------------------------------------------------

class SlotDefinition(BaseModel):
    """
    Single slot entry inside the slot dictionary.

    Example::
        {
            "day": "MON",
            "start": "09:00",
            "end": "10:00",
            "period": "morning"
        }
    """

    day: str = Field(max_length=3, description="3-letter day code: MON, TUE, WED, THU, FRI, SAT")
    start: str = Field(max_length=5, description="24-h time, e.g. '09:00'")
    end: str = Field(max_length=5, description="24-h time, e.g. '10:00'")
    period: Optional[str] = Field(default=None, description="morning / afternoon / evening")
    type: Optional[Literal["theory", "lab"]] = Field(
        default=None,
        description="Slot kind for solver pruning. Omit on shared theory/lab grids.",
    )
    family: Optional[str] = Field(
        default=None,
        max_length=32,
        description="Lab pair group label (e.g. L1). Two consecutive slots share a family.",
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class TimeGridCreate(BaseModel):
    academic_term_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True
    slots: dict[str, SlotDefinition] = Field(
        default_factory=dict,
        description=(
            "Slot dictionary. Keys are opaque slot codes (e.g. 'A1', 'B3'). "
            "Values define the day and time window for that slot."
        ),
    )


class TimeGridUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    slots: Optional[dict[str, SlotDefinition]] = Field(
        default=None,
        description="Full replacement of the slot dictionary.",
    )


class TimeGridSlotPatch(BaseModel):
    """Body for PATCH /time-grids/{id}/slots — surgical upsert and remove."""

    slots: dict[str, SlotDefinition] = Field(
        default_factory=dict,
        description="Slot codes to add or overwrite. Existing codes not listed are preserved.",
    )
    remove: list[str] = Field(
        default_factory=list,
        description="List of slot codes to delete from the grid.",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class TimeGridResponse(BaseModel):
    id: uuid.UUID
    academic_term_id: uuid.UUID
    name: str
    is_active: bool
    slots: dict[str, Any]   # raw JSON from DB — SlotDefinition shape at runtime
    slot_count: int = Field(default=0)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_count(cls, obj: Any) -> "TimeGridResponse":
        data = {
            "id": obj.id,
            "academic_term_id": obj.academic_term_id,
            "name": obj.name,
            "is_active": obj.is_active,
            "slots": obj.slots or {},
            "slot_count": len(obj.slots) if obj.slots else 0,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
        return cls(**data)


TimeGridListResponse = PaginatedResponse[TimeGridResponse]
