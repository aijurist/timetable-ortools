"""
analytics.py
============
Analytics & reporting — snapshots and materialized view queries.

Architecture Notes
------------------
- AnalyticsSnapshot rows are IMMUTABLE — never updated, only inserted.
  The Celery beat task calls ``analytics_svc.persist_snapshot`` to write them.
- workload_metrics and room_utilization are PostgreSQL materialized views.
  This router reads them via analytics_svc raw SQL helpers.
- POST /analytics/snapshots enqueues a Celery task (fire-and-forget).
  The client polls the task_id via GET /schedules/{task_id}/status.

GET    /analytics/snapshots                    List snapshots for an institution
POST   /analytics/snapshots                    Trigger snapshot generation (enqueues Celery)
GET    /analytics/snapshots/{id}               Get a specific snapshot
GET    /analytics/workload                     Read workload_metrics materialized view
GET    /analytics/room-utilization             Read room_utilization materialized view
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    actor_institution_id,
    assert_same_institution,
    get_db,
    get_pagination,
    require_admin,
    require_hod,
)
from app.schemas.analytics import (
    AnalyticsSnapshotListResponse,
    AnalyticsSnapshotResponse,
    GenerateSnapshotRequest,
    GenerateSnapshotResponse,
    RoomUtilizationResponse,
    RoomUtilizationRow,
    WorkloadMetricsResponse,
    FacultyWorkloadRow,
)
import app.services.analytics_service as analytics_svc

router = APIRouter()


# ===========================================================================
# AnalyticsSnapshots
# ===========================================================================


@router.get(
    "/snapshots",
    response_model=AnalyticsSnapshotListResponse,
    summary="List analytics snapshots for an institution",
)
async def list_snapshots(
    institution_id: uuid.UUID = Query(..., description="Institution UUID"),
    academic_term_id: Optional[uuid.UUID] = Query(default=None, description="Filter by term"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_admin),
) -> AnalyticsSnapshotListResponse:
    assert_same_institution(current_user, institution_id)
    items = await analytics_svc.list_snapshots(
        db,
        institution_id,
        academic_term_id=academic_term_id,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return AnalyticsSnapshotListResponse(
        items=[AnalyticsSnapshotResponse.model_validate(s) for s in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.post(
    "/snapshots",
    response_model=GenerateSnapshotResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger analytics snapshot generation (enqueues Celery task)",
)
async def generate_snapshot(
    body: GenerateSnapshotRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> GenerateSnapshotResponse:
    """
    Fire-and-forget: enqueues the Celery analytics task and returns task_id.
    The snapshot row is written by the task via analytics_svc.persist_snapshot.
    Poll task status via GET /schedules/{task_id}/status.
    """
    inst_id = actor_institution_id(current_user, body.institution_id)
    task_id = analytics_svc.trigger_snapshot_task(inst_id, body.academic_term_id)
    return GenerateSnapshotResponse(task_id=task_id)


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=AnalyticsSnapshotResponse,
    summary="Get a specific analytics snapshot",
)
async def get_snapshot(
    snapshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> AnalyticsSnapshotResponse:
    snapshot = await analytics_svc.get_snapshot_or_404(db, snapshot_id)
    assert_same_institution(current_user, snapshot.institution_id)
    return AnalyticsSnapshotResponse.model_validate(snapshot)


# ===========================================================================
# Materialized View Queries (read-only)
# ===========================================================================


@router.get(
    "/workload",
    response_model=WorkloadMetricsResponse,
    summary="Faculty workload metrics (live query scoped to a scenario)",
)
async def get_workload_metrics(
    scenario_id: uuid.UUID = Query(..., description="Scenario UUID"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> WorkloadMetricsResponse:
    """
    Live query against scheduled_sessions JOIN faculty, filtered by scenario_id.
    Returns one row per faculty member with session counts for this scenario's schedule.
    """
    rows_raw = await analytics_svc.get_workload_by_scenario(db, scenario_id)
    rows = [FacultyWorkloadRow(**r) for r in rows_raw]
    return WorkloadMetricsResponse(
        scenario_id=str(scenario_id),
        rows=rows,
        total=len(rows),
    )


@router.get(
    "/room-utilization",
    response_model=RoomUtilizationResponse,
    summary="Room utilization metrics (live query scoped to a scenario)",
)
async def get_room_utilization(
    scenario_id: uuid.UUID = Query(..., description="Scenario UUID"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> RoomUtilizationResponse:
    """
    Live query against scheduled_sessions JOIN rooms, filtered by scenario_id.
    Returns one row per room with booked slot counts for this scenario's schedule.
    """
    rows_raw = await analytics_svc.get_room_utilization_by_scenario(db, scenario_id)
    rows = [RoomUtilizationRow(**r) for r in rows_raw]
    return RoomUtilizationResponse(
        scenario_id=str(scenario_id),
        rows=rows,
        total=len(rows),
    )
