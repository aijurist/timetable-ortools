"""Admin/HOD selection window management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    get_db,
    hod_dept_filter,
    require_hod,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.selection import (
    CompletionOverviewResponse,
    CompletionOverviewItem,
    CompletionStatsResponse,
    OfferingSeatDashboardItem,
    PublishedContextResponse,
    RegistrationStatsResponse,
    SelectionImpactResponse,
    SelectionWindowResponse,
    SelectionWindowUpsert,
)

import app.services.selection_cache_service as cache_svc
import app.services.selection_invalidation_service as invalidation_svc
import app.services.selection_monitor_service as monitor_svc
import app.services.selection_window_service as window_svc
import app.services.student_course_eligibility_service as eligibility_svc

router = APIRouter()


def _institution_id(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.institution_id:
        raise HTTPException(status_code=403, detail="Institution scope required")
    return uuid.UUID(current_user.institution_id)


def _window_response(window) -> SelectionWindowResponse:
    return SelectionWindowResponse(
        id=window.id,
        institution_id=window.institution_id,
        academic_term_id=window.academic_term_id,
        department_id=window.department_id,
        study_semester=window.study_semester,
        status=window.status,
        effective_phase=window_svc.compute_effective_phase(window),
        preview_opens_at=window.preview_opens_at,
        registration_opens_at=window.registration_opens_at,
        registration_closes_at=window.registration_closes_at,
        allow_changes_until=window.allow_changes_until,
        timezone=window.timezone,
        published_scenario_id=window.published_scenario_id,
        max_selections_per_student=window.max_selections_per_student,
        created_at=window.created_at,
        updated_at=window.updated_at,
    )


@router.get("/", response_model=list[SelectionWindowResponse])
async def list_windows(
    academic_term_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> list[SelectionWindowResponse]:
    inst_id = _institution_id(current_user)
    dept_filter = hod_dept_filter(current_user)
    windows = await window_svc.list_windows(
        db, inst_id, academic_term_id, dept_filter
    )
    return [_window_response(w) for w in windows]


@router.get("/completion-overview", response_model=CompletionOverviewResponse)
async def completion_overview(
    academic_term_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CompletionOverviewResponse:
    inst_id = _institution_id(current_user)
    dept_filter = hod_dept_filter(current_user)
    items = await monitor_svc.get_completion_overview(
        db,
        institution_id=inst_id,
        academic_term_id=academic_term_id,
        dept_filter=dept_filter,
    )
    return CompletionOverviewResponse(
        items=[CompletionOverviewItem(**item) for item in items]
    )


@router.put("/{dept_id}/{term_id}", response_model=SelectionWindowResponse)
async def upsert_window(
    dept_id: uuid.UUID,
    term_id: uuid.UUID,
    payload: SelectionWindowUpsert,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> SelectionWindowResponse:
    inst_id = _institution_id(current_user)
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and dept_filter != dept_id:
        raise HTTPException(status_code=403, detail="Not your department")

    try:
        window = await window_svc.upsert_window(
            db, inst_id, term_id, dept_id, payload,
            actor_user_id=current_user.user_uuid,
        )
        await db.commit()
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await cache_svc.invalidate_menu_cache(dept_id, payload.study_semester)
    return _window_response(window)


@router.post("/{dept_id}/{term_id}/open", response_model=SelectionWindowResponse)
async def open_window(
    dept_id: uuid.UUID,
    term_id: uuid.UUID,
    study_semester: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> SelectionWindowResponse:
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and dept_filter != dept_id:
        raise HTTPException(status_code=403, detail="Not your department")

    try:
        window = await window_svc.get_window_or_404(
            db, term_id, dept_id, study_semester
        )
        window = await window_svc.open_registration(db, window)
        await db.commit()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await cache_svc.invalidate_menu_cache(dept_id, study_semester)
    return _window_response(window)


@router.post("/{dept_id}/{term_id}/close", response_model=SelectionWindowResponse)
async def close_window(
    dept_id: uuid.UUID,
    term_id: uuid.UUID,
    study_semester: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> SelectionWindowResponse:
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and dept_filter != dept_id:
        raise HTTPException(status_code=403, detail="Not your department")

    try:
        window = await window_svc.get_window_or_404(
            db, term_id, dept_id, study_semester
        )
        window = await window_svc.close_registration(db, window)
        await db.commit()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await cache_svc.invalidate_menu_cache(dept_id, study_semester)
    return _window_response(window)


@router.get(
    "/{dept_id}/{term_id}/selection-impact",
    response_model=SelectionImpactResponse,
)
async def selection_impact(
    dept_id: uuid.UUID,
    term_id: uuid.UUID,
    study_semester: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> SelectionImpactResponse:
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and dept_filter != dept_id:
        raise HTTPException(status_code=403, detail="Not your department")

    count = await invalidation_svc.count_active_selections_for_window(
        db,
        academic_term_id=term_id,
        department_id=dept_id,
        study_semester=study_semester,
    )
    return SelectionImpactResponse(active_selection_count=count)


@router.get(
    "/{dept_id}/{term_id}/published-context",
    response_model=PublishedContextResponse,
)
async def published_context(
    dept_id: uuid.UUID,
    term_id: uuid.UUID,
    study_semester: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> PublishedContextResponse:
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and dept_filter != dept_id:
        raise HTTPException(status_code=403, detail="Not your department")

    ctx = await eligibility_svc.get_published_context(
        db,
        academic_term_id=term_id,
        department_id=dept_id,
        study_semester=study_semester,
    )
    return PublishedContextResponse(**ctx)


@router.get(
    "/{dept_id}/{term_id}/completion-stats",
    response_model=CompletionStatsResponse,
)
async def completion_stats(
    dept_id: uuid.UUID,
    term_id: uuid.UUID,
    study_semester: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CompletionStatsResponse:
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and dept_filter != dept_id:
        raise HTTPException(status_code=403, detail="Not your department")

    inst_id = _institution_id(current_user)
    stats = await monitor_svc.get_completion_stats(
        db,
        institution_id=inst_id,
        academic_term_id=term_id,
        department_id=dept_id,
        study_semester=study_semester,
    )
    return CompletionStatsResponse(**stats)


@router.get("/{dept_id}/offerings/seats", response_model=RegistrationStatsResponse)
async def offering_seat_dashboard(
    dept_id: uuid.UUID,
    study_semester: int = Query(...),
    academic_term_id: uuid.UUID | None = Query(None),
    scenario_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> RegistrationStatsResponse:
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and dept_filter != dept_id:
        raise HTTPException(status_code=403, detail="Not your department")

    inst_id = _institution_id(current_user)
    data = await monitor_svc.get_offering_seat_dashboard(
        db,
        institution_id=inst_id,
        department_id=dept_id,
        study_semester=study_semester,
        academic_term_id=academic_term_id,
        scenario_id=scenario_id,
    )
    completion = data.get("completion")
    return RegistrationStatsResponse(
        confirms_last_minute=data["confirms_last_minute"],
        confirmed_students=data["confirmed_students"],
        total_offering_bookings=data["total_offering_bookings"],
        completion=CompletionStatsResponse(**completion) if completion else None,
        offerings=[OfferingSeatDashboardItem(**item) for item in data["offerings"]],
    )
