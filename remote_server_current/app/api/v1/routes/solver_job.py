"""
solver_job.py
=============
Read-only endpoints for SolverJob runs and JobConflicts.

These are written exclusively by the Celery solver task and the solver
analysis pass — the API only exposes them for inspection by the Agent's
conflict-analysis tool and the frontend's run-history UI.

GET    /solver-jobs                                List solver jobs for a scenario
GET    /solver-jobs/{job_id}                       Get a single solver job
GET    /solver-jobs/scenarios/{scenario_id}/latest Get the latest job for a scenario
GET    /solver-jobs/{job_id}/conflicts             List job conflicts (Agent analysis input)
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    assert_same_institution,
    get_current_user,
    get_db,
    get_pagination,
    require_admin,
)
import app.services.scenario_service as scenario_svc
from app.models.solver_job import ConflictSeverity
from app.schemas.schedule import ScheduledSessionResponse
from app.schemas.solver_job import (
    JobConflictListResponse,
    JobConflictResponse,
    SolverJobListResponse,
    SolverJobResponse,
)
import app.services.solver_job_service as solver_job_svc

router = APIRouter()


@router.get(
    "",
    response_model=SolverJobListResponse,
    summary="List solver jobs for a scenario",
)
async def list_solver_jobs(
    scenario_id: uuid.UUID = Query(..., description="Filter by scenario UUID"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> SolverJobListResponse:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    items = await solver_job_svc.list_jobs(db, scenario_id, skip=pagination.skip, limit=pagination.limit)
    total = await solver_job_svc.count_jobs(db, scenario_id)
    response_items = await solver_job_svc.serialize_job_responses(db, items)
    return SolverJobListResponse(
        items=response_items,
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/scenarios/{scenario_id}/latest",
    response_model=SolverJobResponse,
    summary="Get the latest solver job for a scenario",
    description=(
        "Returns the most recent SolverJob row for the scenario (ordered by started_at DESC). "
        "Used by the Agent's analyze_conflict tool after an INFEASIBLE result."
    ),
)
async def get_latest_solver_job(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> SolverJobResponse:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    job = await solver_job_svc.get_latest_job(db, scenario_id)
    if job is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"No solver jobs found for scenario {scenario_id}")
    return await solver_job_svc.serialize_job_response(db, job, latest_job_id=job.id)


@router.get(
    "/{job_id}/stream",
    summary="Stream solver progress events via Server-Sent Events",
    description=(
        "Returns a persistent text/event-stream of solver progress events for a job. "
        "Replays all buffered events first (safe for late connectors), then streams live. "
        "Sends 'event: done' when the solver completes or times out. "
        "Connect with EventSource — events are JSON strings from the solver pipeline."
    ),
)
async def stream_solver_events(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> StreamingResponse:
    job = await solver_job_svc.get_job_or_404(db, job_id)
    scenario = await scenario_svc.get_or_404(db, job.scenario_id)
    assert_same_institution(current_user, scenario.institution_id)

    import json as _json
    import time
    from app.core.redis_client import get_async_redis, solver_stream_key

    stream_key = solver_stream_key(str(job_id))

    # Check whether the Redis stream still exists.  If the job is already
    # completed and the stream has expired, fall back to DB log_entries so
    # the log viewer always works regardless of age.
    async def event_generator():
        import asyncio as _asyncio

        r = get_async_redis()
        _terminal = {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "FAILED"}

        try:
            stream_exists = await r.exists(stream_key)
        except Exception:
            stream_exists = False

        if not stream_exists:
            # Check job status to decide: wait for stream (active) or replay from DB (terminal)
            job = await solver_job_svc.get_job_or_404(db, job_id)
            is_terminal = job.status.value in _terminal

            if is_terminal:
                # Job finished and stream expired → replay permanently-stored log from DB
                await r.aclose()
                for entry in (job.log_entries or []):
                    yield f"data: {_json.dumps(entry)}\n\n"
                yield "event: done\ndata: {}\n\n"
                return

            # Job still active but stream not yet created (task is PENDING/assembling input).
            # Poll until the stream key appears or the job terminates.
            wait_deadline = time.monotonic() + 90  # 90s — well beyond assemble_input time
            while time.monotonic() < wait_deadline:
                await _asyncio.sleep(1)
                try:
                    stream_exists = await r.exists(stream_key)
                except Exception:
                    break
                if stream_exists:
                    break
                # Re-check job status in case it went terminal without publishing
                try:
                    job = await solver_job_svc.get_job_or_404(db, job_id)
                    if job.status.value in _terminal:
                        await r.aclose()
                        for entry in (job.log_entries or []):
                            yield f"data: {_json.dumps(entry)}\n\n"
                        yield "event: done\ndata: {}\n\n"
                        return
                except Exception:
                    pass
                yield ": keepalive\n\n"  # keep browser connection alive while waiting

            if not stream_exists:
                await r.aclose()
                yield 'event: done\ndata: {"reason": "stream_never_appeared"}\n\n'
                return

        # Stream exists — read from the very beginning (safe replay + live blocking)
        last_id = "0-0"
        deadline = time.monotonic() + 720  # 12-minute ceiling

        try:
            while time.monotonic() < deadline:
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                block_ms = min(30_000, remaining_ms)

                results = await r.xread({stream_key: last_id}, block=block_ms, count=100)

                if not results:
                    if time.monotonic() >= deadline:
                        yield 'event: done\ndata: {"reason": "timeout"}\n\n'
                        break
                    yield ": keepalive\n\n"
                    continue

                for _, messages in results:
                    for msg_id, fields in messages:
                        last_id = msg_id
                        if "done" in fields:
                            yield "event: done\ndata: {}\n\n"
                            return
                        if "data" in fields:
                            yield f"data: {fields['data']}\n\n"
        finally:
            await r.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{job_id}",
    response_model=SolverJobResponse,
    summary="Get a solver job by ID",
)
async def get_solver_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> SolverJobResponse:
    job = await solver_job_svc.get_job_or_404(db, job_id)
    scenario = await scenario_svc.get_or_404(db, job.scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    return await solver_job_svc.serialize_job_response(db, job)


@router.get(
    "/{job_id}/results",
    response_model=List[ScheduledSessionResponse],
    summary="Get the hydrated schedule rows for a solver job",
)
async def get_solver_job_results(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> List[ScheduledSessionResponse]:
    job = await solver_job_svc.get_job_or_404(db, job_id)
    scenario = await scenario_svc.get_or_404(db, job.scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    rows = await solver_job_svc.get_result_rows(db, job_id)
    return [ScheduledSessionResponse.model_validate(row) for row in rows]


@router.get(
    "/{job_id}/conflicts",
    response_model=JobConflictListResponse,
    summary="List infeasibility conflicts for a solver job",
    description=(
        "Returns JobConflict rows written by the solver analysis pass on INFEASIBLE runs. "
        "The Agent's analyze_conflict tool reads these to decide which Tier 2 params to relax."
    ),
)
async def list_job_conflicts(
    job_id: uuid.UUID,
    severity: Optional[ConflictSeverity] = Query(
        default=None, description="Filter by severity: BLOCKER | HIGH | MEDIUM | LOW"
    ),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> JobConflictListResponse:
    job = await solver_job_svc.get_job_or_404(db, job_id)
    scenario = await scenario_svc.get_or_404(db, job.scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    items = await solver_job_svc.list_conflicts(
        db, job_id, severity=severity, skip=pagination.skip, limit=pagination.limit
    )
    return JobConflictListResponse(
        items=[JobConflictResponse.model_validate(c) for c in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )
