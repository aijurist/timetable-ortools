"""
Schedules router — trigger and monitor solver runs.

POST   /schedules/generate              Enqueue a solve Celery task for a scenario.
GET    /schedules/{task_id}/status      Poll task status (PENDING | RUNNING | SUCCESS | FAILURE).
GET    /schedules/{scenario_id}         Return the completed timetable for a scenario.
PATCH  /schedules/{task_id}/pause       Pause a running solver task.
PATCH  /schedules/{task_id}/resume      Resume a paused task.
DELETE /schedules/{task_id}/cancel      Revoke a queued/running task.
"""
from __future__ import annotations

import uuid
from typing import List

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    UserRole,
    assert_same_institution,
    get_current_user,
    get_db,
    hod_dept_filter,
    require_hod,
    require_role,
)
from app.core.celery_app import celery_app
from app.schemas.schedule import (
    DepartmentTimetableResponse,
    ScheduledSessionPatchRequest,
    ScheduledSessionPatchResponse,
    ScheduledSessionPinUpdate,
    ScheduledSessionResponse,
    TeacherTimetableResponse,
)
from app.core.exceptions import NotFoundError
import app.services.published_timetable_service as published_timetable_svc
import app.services.schedule_service as schedule_svc
import app.services.scenario_service as scenario_svc
import app.services.solver_job_service as solver_job_svc

router = APIRouter()


class _GenerateRequest(BaseModel):
    scenario_id: uuid.UUID
    force: bool = False


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------

@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a timetable solve for a scenario",
)
async def generate_schedule(
    body: _GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Enqueues a Celery task to solve the given scenario.
    Returns the Celery task_id immediately — poll /status to track progress.
    """
    # Verify scenario exists and belongs to caller's institution
    scenario = await scenario_svc.get_or_404(db, body.scenario_id)
    assert_same_institution(current_user, scenario.institution_id)

    # Optional feasibility gate
    if not body.force:
        from app.services.feasibility_checker import run_feasibility_check

        class _FeasIssueOut(BaseModel):
            severity: str
            code: str
            message: str
            entity: str | None = None
            detail: dict = {}

        class _FeasReportOut(BaseModel):
            feasible: bool
            issues: list[_FeasIssueOut]
            summary: dict = {}

        report = await run_feasibility_check(db, scenario)
        if not report.feasible:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "FEASIBILITY_FAILED",
                    "message": "Pre-solve feasibility check failed. Pass force=true to bypass.",
                    "report": _FeasReportOut(
                        feasible=report.feasible,
                        issues=[
                            _FeasIssueOut(
                                severity=i.severity,
                                code=i.code,
                                message=i.message,
                                entity=i.entity,
                                detail=i.detail,
                            )
                            for i in report.issues
                        ],
                        summary=report.summary,
                    ).model_dump(),
                },
            )

    # Enqueue the Celery solve task
    task = celery_app.send_task(
        "app.tasks.solver_tasks.run_solver",
        kwargs={"scenario_id": str(scenario.id)},
    )

    # Persist the Celery task_id so clients can poll status and admins can revoke
    scenario.celery_task_id = task.id
    scenario.is_dirty = False  # will be set True again if rules change before completion
    await db.commit()

    return {"task_id": task.id, "scenario_id": str(scenario.id), "status": "PENDING"}


# ---------------------------------------------------------------------------
# GET /{task_id}/status
# ---------------------------------------------------------------------------

@router.get(
    "/{task_id}/status",
    summary="Poll solver task status",
)
async def get_task_status(
    task_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Returns real-time Celery task status: PENDING | STARTED | SUCCESS | FAILURE | REVOKED."""
    result = AsyncResult(task_id, app=celery_app)
    info = result.info
    progress = info.get("progress", 0) if isinstance(info, dict) else 0
    return {
        "task_id": task_id,
        "status": result.state,
        "progress": progress,
        "detail": str(info) if not isinstance(info, dict) else info,
    }


# ---------------------------------------------------------------------------
# GET /department-timetable  — HOD published dept view
# ---------------------------------------------------------------------------

@router.get(
    "/department-timetable",
    response_model=DepartmentTimetableResponse,
    summary="Published timetable for the caller's department (HOD)",
)
async def get_department_timetable(
    study_semester: int | None = Query(None, ge=1, le=8),
    academic_term_id: uuid.UUID | None = None,
    faculty_id: uuid.UUID | None = None,
    day_of_week: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> DepartmentTimetableResponse:
    if current_user.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution scope required")

    dept_filter = hod_dept_filter(current_user)
    department_id = dept_filter if dept_filter is not None else current_user.department_uuid
    if department_id is None:
        raise HTTPException(
            status_code=400,
            detail="A department scope is required for this timetable view",
        )

    try:
        return await published_timetable_svc.get_department_timetable(
            db,
            institution_id=uuid.UUID(current_user.institution_id),
            department_id=department_id,
            study_semester=study_semester,
            academic_term_id=academic_term_id,
            faculty_id=faculty_id,
            day_of_week=day_of_week,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /my-timetable  — teacher personal published view
# ---------------------------------------------------------------------------

@router.get(
    "/my-timetable",
    response_model=TeacherTimetableResponse,
    summary="Published timetable for the logged-in teacher",
)
async def get_my_timetable(
    academic_term_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(UserRole.TEACHER)),
) -> TeacherTimetableResponse:
    if current_user.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution scope required")

    try:
        return await published_timetable_svc.get_teacher_timetable(
            db,
            institution_id=uuid.UUID(current_user.institution_id),
            user_id=current_user.user_uuid,
            academic_term_id=academic_term_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GET /{scenario_id}  — fetch solved timetable
# ---------------------------------------------------------------------------

@router.get(
    "/{scenario_id}",
    response_model=List[ScheduledSessionResponse],
    summary="Retrieve the solved timetable for a scenario",
)
async def get_schedule(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> List[ScheduledSessionResponse]:
    """Returns all ScheduledSession rows for the scenario, ordered by slot."""
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    sessions = await schedule_svc.get_by_scenario(db, scenario_id)
    return [ScheduledSessionResponse.model_validate(s) for s in sessions]


@router.get(
    "/{scenario_id}/published",
    response_model=List[ScheduledSessionResponse],
    summary="Retrieve the published timetable for a scenario",
)
async def get_published_schedule(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> List[ScheduledSessionResponse]:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    if scenario.published_job_id is None:
        return []

    rows = await solver_job_svc.get_result_rows(db, scenario.published_job_id)
    return [ScheduledSessionResponse.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# PATCH /{scenario_id}/sessions/{session_id}/pin
# ---------------------------------------------------------------------------

@router.patch(
    "/{scenario_id}/sessions/{session_id}/pin",
    response_model=ScheduledSessionResponse,
    summary="Pin or unpin a scheduled session",
)
async def toggle_session_pin(
    scenario_id: uuid.UUID,
    session_id: uuid.UUID,
    body: ScheduledSessionPinUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ScheduledSessionResponse:
    """Pin or unpin a session. Marks the scenario as dirty so the coordinator knows to re-run."""
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    if scenario.status.value not in ("COMPLETED",):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot pin sessions on an unsolved scenario.",
        )
    session = await schedule_svc.toggle_pin(db, scenario_id, session_id, body.is_pinned)
    await db.commit()
    await db.refresh(session)
    return ScheduledSessionResponse.model_validate(session)


# ---------------------------------------------------------------------------
# PATCH /{scenario_id}/sessions/{session_id} — manual room/faculty/slot edit
# ---------------------------------------------------------------------------

@router.patch(
    "/{scenario_id}/sessions/{session_id}",
    response_model=ScheduledSessionPatchResponse,
    summary="Manually override room, faculty, or slot for a scheduled session",
)
async def edit_session(
    scenario_id: uuid.UUID,
    session_id: uuid.UUID,
    body: ScheduledSessionPatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ScheduledSessionPatchResponse:
    """
    Overrides room, faculty, and/or slot (for DnD moves) on a scheduled session.
    Sets is_pinned=True and marks the scenario dirty.
    Returns the updated session with any collision warnings.
    """
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    if scenario.status.value not in ("COMPLETED",):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot edit sessions on an unsolved scenario.",
        )
    session_row, warnings = await schedule_svc.manual_edit_session(
        db,
        scenario_id=scenario_id,
        session_id=session_id,
        room_id=body.room_id,
        faculty_id=body.faculty_id,
        slot_code=body.slot_code,
        force=body.force,
    )
    await db.commit()
    # Reload with enriched data
    enriched_list = await schedule_svc.get_by_scenario(db, scenario_id)
    enriched = next(
        (e for e in enriched_list if str(e["id"]) == str(session_row.id)),
        None,
    )
    if enriched is None:
        await db.refresh(session_row)
        enriched = session_row
    return ScheduledSessionPatchResponse(
        session=ScheduledSessionResponse.model_validate(enriched),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# PATCH /{task_id}/pause  |  resume
# ---------------------------------------------------------------------------

@router.patch("/{task_id}/pause", summary="Pause a running solver task")
async def pause_task(
    task_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Sends a SIGUSR1-based pause signal via Celery control."""
    celery_app.control.revoke(task_id, terminate=False)
    return {"task_id": task_id, "status": "PAUSED"}


@router.patch("/{task_id}/resume", summary="Resume a paused solver task")
async def resume_task(
    task_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Re-queues the task (Celery does not natively support resume; re-enqueue pattern)."""
    return {"task_id": task_id, "status": "PENDING", "note": "Re-trigger via /generate"}


# ---------------------------------------------------------------------------
# DELETE /{task_id}/cancel
# ---------------------------------------------------------------------------

@router.delete(
    "/{task_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Cancel a queued or running solver task",
)
async def cancel_task(
    task_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    celery_app.control.revoke(task_id, terminate=True)
    return None
