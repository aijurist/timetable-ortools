"""
app/models/audit_log.py
========================
Immutable audit ledger — one row per significant state-change event.

Design rules:
- No UPDATE or DELETE (enforced by removing those API endpoints)
- No updated_at column
- actor_user_id is nullable (system/Celery actions have no human actor)
- institution_id is nullable (SUPER_ADMIN cross-org actions)
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditAction(str, enum.Enum):
    CREATED          = "CREATED"
    UPDATED          = "UPDATED"
    DELETED          = "DELETED"
    PUBLISHED        = "PUBLISHED"
    ARCHIVED         = "ARCHIVED"
    SOLVED           = "SOLVED"
    EXPORTED         = "EXPORTED"
    LOGIN            = "LOGIN"
    LOGOUT           = "LOGOUT"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    RULE_ADDED       = "RULE_ADDED"
    RULE_REMOVED     = "RULE_REMOVED"
    SCENARIO_LOCKED  = "SCENARIO_LOCKED"
    RESTORED         = "RESTORED"
    TOGGLED          = "TOGGLED"


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Scoping — nullable for cross-org (SUPER_ADMIN) actions
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Actor — nullable for system / Celery actions
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # What happened
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action"),
        nullable=False,
        index=True,
    )

    # Target object
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Change snapshot (only set on UPDATED actions)
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Request metadata
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_audit_log_institution_created", "institution_id", "created_at"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action} "
            f"entity={self.entity_type}/{self.entity_id}>"
        )
