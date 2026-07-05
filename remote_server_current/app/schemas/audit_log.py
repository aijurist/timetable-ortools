"""
app/schemas/audit_log.py
=========================
Pydantic schemas for audit log API responses.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.audit_log import AuditAction


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    action: AuditAction
    entity_type: str
    entity_id: uuid.UUID | None
    entity_label: str | None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    skip: int
    limit: int
