"""
app/schemas/solver_job.py
=========================
Pydantic V2 schemas for SolverJob and JobConflict.

Both are READ-ONLY from the API perspective:
- SolverJob rows are created by the Celery task and never updated after
  the run completes.
- JobConflict rows are written by the solver analysis pass and read by
  the Agent's self-correction loop.

No Create/Update schemas are exposed — the API only surfaces these
for inspection, rollback, and the agent's conflict-analysis tool.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.models.solver_job import ConflictSeverity, SolverJobStatus
from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# SolverJob
# ---------------------------------------------------------------------------


class SolverJobResponse(BaseModel):
    """
    Read-only view of a single CP-SAT solver run.

    Key fields for the Agent:
    - ``status``: INFEASIBLE triggers the self-correction loop.
    - ``result_schedule``: list of ScheduledSession dicts (mirrors DB rows).
    - ``score_summary``: {objective, gap_pct, wall_seconds, sessions}.
    - ``constraints_snapshot`` + ``config_snapshot``: exact solver inputs for
      diffing across jobs.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scenario_id: uuid.UUID
    celery_task_id: Optional[str] = None
    constraints_snapshot: dict[str, Any]
    config_snapshot: dict[str, Any]
    # Stored as a JSON list of ScheduledSession dicts, not a single dict.
    result_schedule: Optional[list[dict[str, Any]]] = None
    status: SolverJobStatus
    score_summary: Optional[dict[str, Any]] = None
    telemetry_snapshot: Optional[dict[str, Any]] = None
    # Ordered event log captured during the run (permanent, DB-backed).
    log_entries: Optional[list[dict[str, Any]]] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    is_latest: bool = False
    is_current: bool = False
    is_published: bool = False
    has_result_schedule: bool = False


SolverJobListResponse = PaginatedResponse[SolverJobResponse]


# ---------------------------------------------------------------------------
# JobConflict
# ---------------------------------------------------------------------------


class JobConflictResponse(BaseModel):
    """
    One infeasibility record from the constraint analysis pass.

    Read by the Agent's ``analyze_conflict`` tool to decide which
    Tier 2 params to relax.

    ``entities`` is a free-form JSON array of offending resource references:
    e.g. [{"type": "faculty", "id": "uuid"}, {"type": "room", "id": "uuid"}]
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: uuid.UUID
    constraint_code: Optional[str]
    severity: ConflictSeverity
    description: Optional[str]
    entities: Optional[list[dict[str, Any]]]
    created_at: datetime
    # Diagnosis fields — populated by the solver analysis pass
    conflict_code: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[float] = None
    evidence: Optional[list] = None
    recommended_actions: Optional[list] = None


JobConflictListResponse = PaginatedResponse[JobConflictResponse]
