"""
app/services/audit_log_service.py
===================================
Write-only ledger service for audit events.

Key contract:
  record() NEVER raises — a logging failure must not abort the real operation.
  Call it within the same DB transaction as the domain write so both commit
  or roll back together.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.core.request_context import get_request_ip, get_request_ua
from app.models.audit_log import AuditAction, AuditLog


def _sanitize(value: Any) -> Any:
    """Recursively convert non-JSON-serializable types to JSON-safe equivalents."""
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


async def record(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    actor_role: str | None,
    action: AuditAction,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    entity_label: str | None = None,
    institution_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """
    Append one row to the audit ledger.

    Never raises — exceptions are caught and logged at WARNING level so that
    a log failure can never abort a domain operation.
    """
    try:
        # Fall back to per-request context vars so callers don't have to pass
        # ip_address / user_agent explicitly — the middleware sets them once.
        resolved_ip = ip_address if ip_address is not None else get_request_ip()
        resolved_ua = user_agent if user_agent is not None else get_request_ua()
        entry = AuditLog(
            institution_id=institution_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=entity_label,
            before_state=_sanitize(before),
            after_state=_sanitize(after),
            ip_address=resolved_ip,
            user_agent=resolved_ua,
        )
        db.add(entry)
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "audit_log.record failed — continuing without audit entry",
            action=str(action),
            entity_type=entity_type,
            error=str(exc),
        )


async def query_logs(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    action: AuditAction | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AuditLog], int]:
    """
    Query audit log with filters.  Returns (items, total_count).
    """
    q = select(AuditLog)
    count_q = select(func.count()).select_from(AuditLog)

    def _apply_filters(stmt):
        if institution_id is not None:
            stmt = stmt.where(AuditLog.institution_id == institution_id)
        if entity_type is not None:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if actor_user_id is not None:
            stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if from_dt is not None:
            stmt = stmt.where(AuditLog.created_at >= from_dt)
        if to_dt is not None:
            stmt = stmt.where(AuditLog.created_at <= to_dt)
        return stmt

    q = _apply_filters(q).order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
    count_q = _apply_filters(count_q)

    items_result = await db.execute(q)
    count_result = await db.execute(count_q)

    items = list(items_result.scalars().all())
    total = count_result.scalar_one()
    return items, total
