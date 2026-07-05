"""Admin API for Selection Window Access Configuration."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_db, require_admin
from app.models.selection_access_config import SelectionAccessConfig
from app.schemas.selection_access_config import (
    SelectionAccessConfigResponse,
    SelectionAccessConfigUpsert,
)

router = APIRouter()


def _institution_id(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.institution_id:
        raise HTTPException(status_code=403, detail="Institution scope required")
    return uuid.UUID(current_user.institution_id)


def _to_response(cfg: SelectionAccessConfig) -> SelectionAccessConfigResponse:
    return SelectionAccessConfigResponse(
        id=cfg.id,
        institution_id=cfg.institution_id,
        academic_term_id=cfg.academic_term_id,
        allowed_login_years=cfg.allowed_login_years or [],
        allowed_booking_years=cfg.allowed_booking_years or [],
        allowed_login_departments=[
            uuid.UUID(d) if isinstance(d, str) else d
            for d in (cfg.allowed_login_departments or [])
        ],
        allowed_booking_departments=[
            uuid.UUID(d) if isinstance(d, str) else d
            for d in (cfg.allowed_booking_departments or [])
        ],
        early_access_emails=cfg.early_access_emails or [],
        group_seat_overrides=cfg.group_seat_overrides or [],
        default_max_group_size=cfg.default_max_group_size,
        notes=cfg.notes,
    )


@router.get(
    "/access-config",
    response_model=SelectionAccessConfigResponse | None,
    summary="Get student access configuration for a term",
)
async def get_access_config(
    academic_term_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> SelectionAccessConfigResponse | None:
    inst_id = _institution_id(current_user)
    cfg = await db.scalar(
        select(SelectionAccessConfig).where(
            SelectionAccessConfig.institution_id == inst_id,
            SelectionAccessConfig.academic_term_id == academic_term_id,
        )
    )
    return _to_response(cfg) if cfg else None


@router.put(
    "/access-config",
    response_model=SelectionAccessConfigResponse,
    summary="Upsert student access configuration for a term",
)
async def upsert_access_config(
    academic_term_id: uuid.UUID = Query(...),
    payload: SelectionAccessConfigUpsert = ...,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> SelectionAccessConfigResponse:
    inst_id = _institution_id(current_user)
    cfg = await db.scalar(
        select(SelectionAccessConfig).where(
            SelectionAccessConfig.institution_id == inst_id,
            SelectionAccessConfig.academic_term_id == academic_term_id,
        )
    )

    def _dept_ids(ids: list) -> list[str]:
        return [str(d) for d in ids]

    data = {
        "allowed_login_years": payload.allowed_login_years,
        "allowed_booking_years": payload.allowed_booking_years,
        "allowed_login_departments": _dept_ids(payload.allowed_login_departments),
        "allowed_booking_departments": _dept_ids(payload.allowed_booking_departments),
        "early_access_emails": payload.early_access_emails,
        "group_seat_overrides": [
            {"department_id": str(o.department_id), "max_seats": o.max_seats}
            for o in payload.group_seat_overrides
        ],
        "default_max_group_size": payload.default_max_group_size,
        "notes": payload.notes,
    }

    if cfg is None:
        cfg = SelectionAccessConfig(
            institution_id=inst_id,
            academic_term_id=academic_term_id,
            **data,
        )
        db.add(cfg)
    else:
        for field, value in data.items():
            setattr(cfg, field, value)

    await db.commit()
    await db.refresh(cfg)
    return _to_response(cfg)
