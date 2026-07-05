"""
Scenarios router — manage scheduling scenarios.

POST   /scenarios                   Create a new scenario.
GET    /scenarios                   List scenarios (paginated).
GET    /scenarios/{id}              Get a single scenario.
PATCH  /scenarios/{id}/config       Update solver_config overrides.
POST   /scenarios/{id}/clone        Clone a scenario with all its rules.
DELETE /scenarios/{id}              Delete a scenario.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser, PaginationParams, get_current_user, get_db, get_pagination,
    assert_same_institution, actor_institution_id, require_admin,
)
from app.schemas.scenario import ScenarioCreate, ScenarioListResponse, ScenarioResponse, ScenarioUpdate
import app.services.scenario_service as scenario_svc
import app.services.allocation.service as allocation_svc
import app.services.notification_service as notification_svc
import app.services.time_grid_service as time_grid_svc

router = APIRouter()


class _CloneRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=255)


class _JobSelectionRequest(BaseModel):
    job_id: uuid.UUID


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new scheduling scenario",
)
async def create_scenario(
    payload: ScenarioCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> ScenarioResponse:
    inst_id = actor_institution_id(current_user, payload.institution_id)
    scenario = await scenario_svc.create(
        db, inst_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(scenario)
    return ScenarioResponse.model_validate(scenario)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ScenarioListResponse,
    summary="List scenarios for an institution",
)
async def list_scenarios(
    institution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> ScenarioListResponse:
    assert_same_institution(current_user, institution_id)
    total = await scenario_svc.count_by_institution(db, institution_id)
    items = await scenario_svc.list_by_institution(
        db,
        institution_id,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return ScenarioListResponse(
        items=[ScenarioResponse.model_validate(s) for s in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


# ---------------------------------------------------------------------------
# GET /{scenario_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{scenario_id}",
    response_model=ScenarioResponse,
    summary="Get a single scenario",
)
async def get_scenario(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> ScenarioResponse:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    return ScenarioResponse.model_validate(scenario)


# ---------------------------------------------------------------------------
# PATCH /{scenario_id}/config
# ---------------------------------------------------------------------------

@router.patch(
    "/{scenario_id}/config",
    response_model=ScenarioResponse,
    summary="Update solver config overrides",
)
async def update_scenario_config(
    scenario_id: uuid.UUID,
    payload: ScenarioUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> ScenarioResponse:
    existing = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, existing.institution_id)
    scenario = await scenario_svc.update(
        db, scenario_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(scenario)
    return ScenarioResponse.model_validate(scenario)


@router.post(
    "/{scenario_id}/publish",
    response_model=ScenarioResponse,
    summary="Publish a successful solver job for a scenario",
)
async def publish_scenario_job(
    scenario_id: uuid.UUID,
    body: _JobSelectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> ScenarioResponse:
    existing = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, existing.institution_id)
    scenario = await scenario_svc.publish_job(
        db,
        scenario_id,
        body.job_id,
        current_user.user_uuid,
    )
    await db.commit()
    await notification_svc.dispatch_pending(db)
    await db.refresh(scenario)
    return ScenarioResponse.model_validate(scenario)


@router.post(
    "/{scenario_id}/unpublish",
    response_model=ScenarioResponse,
    summary="Unpublish a scenario and invalidate linked student selections",
)
async def unpublish_scenario(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> ScenarioResponse:
    existing = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, existing.institution_id)
    scenario = await scenario_svc.unpublish(
        db,
        scenario_id,
        current_user.user_uuid,
    )
    await db.commit()
    await db.refresh(scenario)
    return ScenarioResponse.model_validate(scenario)


@router.post(
    "/{scenario_id}/restore-current",
    response_model=ScenarioResponse,
    summary="Restore a successful solver job as the current live schedule",
)
async def restore_scenario_current(
    scenario_id: uuid.UUID,
    body: _JobSelectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> ScenarioResponse:
    existing = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, existing.institution_id)
    scenario = await scenario_svc.restore_job_as_current(db, scenario_id, body.job_id)
    await db.commit()
    await db.refresh(scenario)
    return ScenarioResponse.model_validate(scenario)


# ---------------------------------------------------------------------------
# POST /{scenario_id}/clone
# ---------------------------------------------------------------------------

@router.post(
    "/{scenario_id}/clone",
    response_model=ScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone a scenario and all its rules",
)
async def clone_scenario(
    scenario_id: uuid.UUID,
    body: _CloneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> ScenarioResponse:
    existing = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, existing.institution_id)
    cloned = await scenario_svc.clone(
        db, scenario_id, body.new_name,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(cloned)
    return ScenarioResponse.model_validate(cloned)


# ---------------------------------------------------------------------------
# DELETE /{scenario_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/{scenario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a scenario",
)
async def delete_scenario(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> None:
    existing = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, existing.institution_id)
    await scenario_svc.delete_preserve_history(
        db, scenario_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# POST /{scenario_id}/solve
# ---------------------------------------------------------------------------


class _SolveRequest(BaseModel):
    timeout_seconds: int = Field(default=300, ge=30, le=3600)
    num_workers: int = Field(default=8, ge=1, le=16)
    strategy: str = Field(default="PORTFOLIO_WITH_QUICK_RESTART_SEARCH")
    warm_start: bool = Field(default=True, description="Use best_hint as CP-SAT warm-start")
    honor_pins: bool = Field(default=True, description="Hard-lock pinned sessions")
    soft_pins: bool = Field(default=False, description="Flexible: pins as 1M penalty vs hard lock")
    clear_pins: bool = Field(default=False, description="Reset all pins before solving")
    freeze_existing: bool = Field(default=False, description="Transiently freeze entire current schedule")


class _SolveResponse(BaseModel):
    job_id: uuid.UUID
    scenario_id: uuid.UUID
    status: str  # "QUEUED"


@router.post(
    "/{scenario_id}/solve",
    response_model=_SolveResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger asynchronous solve for a scenario",
    description=(
        "Enqueues a Celery solver task for the scenario. "
        "Returns a job_id immediately. Poll GET /solver-jobs/{job_id} for status."
    ),
)
async def solve_scenario(
    scenario_id: uuid.UUID,
    payload: _SolveRequest = _SolveRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> _SolveResponse:
    # 1. Verify scenario exists and belongs to caller's institution
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)

    # 1a. Readiness: nothing to schedule if no cohorts were distributed.
    alloc_state = await allocation_svc.get_allocation_state(db, scenario)
    if len(alloc_state.offerings) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No cohorts distributed for this scenario — set up cohorts first "
                "(Teaching Plan → Cohorts → Distribute)."
            ),
        )

    # 1b. Pre-flight faculty check — if any distributed offering still has no
    # faculty (TBA), block with guidance. (Checked directly on offerings; does
    # not depend on the vestigial TargetCourseDemand rows.)
    if alloc_state.demands_without_faculty > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{alloc_state.demands_without_faculty} offering(s) have no faculty assigned. "
                "Assign faculty in Planning, or via PATCH /course-offerings/{id}, before solving."
            ),
        )

    # 1c. Validate term/grid linkage before enqueuing work.
    try:
        await time_grid_svc.resolve_slots_for_scenario(db, scenario)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # 2. Create SolverJob row
    # constraints_snapshot and config_snapshot are empty at dispatch time;
    # the Celery task populates them after loading the full scenario data.
    import app.services.solver_job_service as solver_job_svc
    job = await solver_job_svc.create_job(
        db,
        scenario_id,
        constraints_snapshot={},
        config_snapshot={
            "timeout_seconds": payload.timeout_seconds,
            "num_workers": payload.num_workers,
            "strategy": payload.strategy,
            "warm_start": payload.warm_start,
            "honor_pins": payload.honor_pins,
            "soft_pins": payload.soft_pins,
            "clear_pins": payload.clear_pins,
            "freeze_existing": payload.freeze_existing,
        },
    )
    await db.commit()
    await db.refresh(job)

    # 3. Enqueue Celery task and save the returned task ID immediately so
    #    the cancel endpoint can revoke it even while it is still queued.
    from app.core.celery_app import celery_app
    from sqlalchemy import update as _update
    from app.models.solver_job import SolverJob

    result = celery_app.send_task(
        "tasks.schedule_tasks.run_solver_task",
        args=[str(scenario_id)],
        kwargs={"job_id": str(job.id)},
        queue="solver",
    )
    await db.execute(
        _update(SolverJob)
        .where(SolverJob.id == job.id)
        .values(celery_task_id=result.id)
    )
    await db.commit()

    return _SolveResponse(
        job_id=job.id,
        scenario_id=scenario_id,
        status="QUEUED",
    )


# ---------------------------------------------------------------------------
# POST /{scenario_id}/cancel
# ---------------------------------------------------------------------------

@router.post(
    "/{scenario_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Cancel the active solver job for a scenario",
)
async def cancel_scenario_solve(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(require_admin),
) -> None:
    from datetime import datetime, timezone
    from sqlalchemy import update as _update, select
    from app.models.solver_job import SolverJob, SolverJobStatus
    from app.models.scenario import Scenario, ScenarioStatus
    from app.core.celery_app import celery_app
    from app.core.redis_client import get_sync_redis, solver_cancel_key
    from app.services.solver_job_service import CANCELLED_BY_USER_ERROR

    # Verify scenario ownership before cancelling
    _scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, _scenario.institution_id)

    # Find the latest active job (PENDING or RUNNING)
    result = await db.execute(
        select(SolverJob)
        .where(
            SolverJob.scenario_id == scenario_id,
            SolverJob.status.in_([SolverJobStatus.PENDING, SolverJobStatus.RUNNING]),
        )
        .order_by(SolverJob.started_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active solver job found for this scenario.",
        )

    # Cooperative cancel flag — checked by the Celery task during solve
    _r = get_sync_redis()
    try:
        _r.setex(solver_cancel_key(str(job.id)), 3600, "1")
    finally:
        _r.close()

    # Mark the job as FAILED in DB before revoke so queued workers abort on start
    await db.execute(
        _update(SolverJob)
        .where(SolverJob.id == job.id)
        .values(
            status=SolverJobStatus.FAILED,
            completed_at=datetime.now(timezone.utc),
            score_summary={"error": CANCELLED_BY_USER_ERROR},
        )
    )

    # Reset scenario status back to DRAFT
    await db.execute(
        _update(Scenario)
        .where(Scenario.id == scenario_id)
        .values(status=ScenarioStatus.DRAFT)
    )

    await db.commit()

    # Best-effort Celery revoke — terminate=False avoids killing solo-pool workers
    if job.celery_task_id:
        celery_app.control.revoke(job.celery_task_id, terminate=False)
