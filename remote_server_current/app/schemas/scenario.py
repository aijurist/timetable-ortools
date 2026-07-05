"""
scenario.py
===========
Pydantic V2 schemas for the Scenario domain.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.scenario import ScenarioStatus
from app.models.institution import SchedulingMode
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    selected_time_grid_id: Optional[uuid.UUID] = None
    solver_config: Optional[dict[str, Any]] = None
    scheduling_mode: Optional[SchedulingMode] = None


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    selected_time_grid_id: Optional[uuid.UUID] = None
    solver_config: Optional[dict[str, Any]] = None
    status: Optional[ScenarioStatus] = None
    scheduling_mode: Optional[SchedulingMode] = None
    auto_publish_latest: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ScenarioResponse(BaseModel):
    id: uuid.UUID
    name: str
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    selected_time_grid_id: Optional[uuid.UUID]
    scheduling_mode: Optional[SchedulingMode] = None
    status: ScenarioStatus
    solver_config: Optional[dict[str, Any]]
    celery_task_id: Optional[str]
    is_dirty: bool
    parent_scenario_id: Optional[uuid.UUID] = None
    current_job_id: Optional[uuid.UUID] = None
    published_job_id: Optional[uuid.UUID] = None
    auto_publish_latest: bool = False
    published_at: Optional[datetime] = None
    published_by_user_id: Optional[uuid.UUID] = None
    best_hint: Optional[dict[str, Any]] = Field(
        default=None, description="CP-SAT variable snapshot for warm-start resume"
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


ScenarioListResponse = PaginatedResponse[ScenarioResponse]
