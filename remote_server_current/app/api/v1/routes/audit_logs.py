"""
app/api/v1/routes/audit_logs.py
================================
Read-only audit log query endpoint.  Admin + Super Admin only.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_db, require_admin
from app.models.audit_log import AuditAction
from app.schemas.audit_log import AuditLogListResponse, AuditLogResponse
from app.services import audit_log_service

router = APIRouter()


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    current_user: Annotated[CurrentUser, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    entity_type: str | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    actor_user_id: uuid.UUID | None = Query(None),
    action: AuditAction | None = Query(None),
    from_dt: datetime | None = Query(None, alias="from"),
    to_dt: datetime | None = Query(None, alias="to"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> AuditLogListResponse:
    """
    Query the audit log.  ADMIN and SUPER_ADMIN only.

    SUPER_ADMIN sees all institutions; ADMIN is scoped to their institution.
    """
    institution_id: uuid.UUID | None = None
    if not current_user.is_super_admin and current_user.institution_id:
        institution_id = uuid.UUID(current_user.institution_id)

    items, total = await audit_log_service.query_logs(
        db,
        institution_id=institution_id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        action=action,
        from_dt=from_dt,
        to_dt=to_dt,
        skip=skip,
        limit=limit,
    )

    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(item) for item in items],
        total=total,
        skip=skip,
        limit=limit,
    )
