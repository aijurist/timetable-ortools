"""
analytics.py
============
Pydantic V2 schemas for the Analytics & Reporting domain.

One ORM table: analytics_snapshots  — immutable point-in-time exports.

Two materialized views (workload_metrics, room_utilization) are NOT ORM models;
they are queried via raw SQL and their response shapes are defined here as
plain Pydantic models.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# AnalyticsSnapshot  (ORM-backed)
# ---------------------------------------------------------------------------

class AnalyticsSnapshotResponse(BaseModel):
    """Returned when fetching a cached analytics export."""

    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    snapshot_data: dict[str, Any]
    generated_at: datetime

    model_config = {"from_attributes": True}


AnalyticsSnapshotListResponse = PaginatedResponse[AnalyticsSnapshotResponse]


# ---------------------------------------------------------------------------
# Workload Metrics  (live query — scenario-scoped)
# ---------------------------------------------------------------------------

class FacultyWorkloadRow(BaseModel):
    """One row from the live workload query (scheduled_sessions JOIN faculty)."""

    faculty_id: str          # String(255) in scheduled_sessions
    faculty_name: Optional[str] = None
    total_sessions: int
    total_hours: Optional[float] = None
    academic_term_id: uuid.UUID
    institution_id: uuid.UUID


class WorkloadMetricsResponse(BaseModel):
    scenario_id: str         # scoped to a specific scenario, not just a term
    rows: list[FacultyWorkloadRow]
    total: int


# ---------------------------------------------------------------------------
# Room Utilisation  (live query — scenario-scoped)
# ---------------------------------------------------------------------------

class RoomUtilizationRow(BaseModel):
    """One row from the live room utilization query (scheduled_sessions JOIN rooms)."""

    room_id: str             # String(255) in scheduled_sessions
    room_code: Optional[str] = None
    room_name: Optional[str] = None
    booked_slots: int
    total_slots: Optional[int] = None
    utilization_pct: Optional[float] = None
    total_sessions: int
    academic_term_id: uuid.UUID
    institution_id: uuid.UUID


class RoomUtilizationResponse(BaseModel):
    scenario_id: str
    rows: list[RoomUtilizationRow]
    total: int


# ---------------------------------------------------------------------------
# Report generation trigger
# ---------------------------------------------------------------------------

class GenerateSnapshotRequest(BaseModel):
    """Body for POST /analytics/snapshots — triggers Celery task."""

    institution_id: uuid.UUID
    academic_term_id: uuid.UUID


class GenerateSnapshotResponse(BaseModel):
    task_id: str
    message: str = "Snapshot generation task queued."
