"""
app/models/notification.py
===========================
User-facing alert system.

Two tables:
  notifications              — one row per delivered alert
  notification_preferences   — per-user channel opt-in/opt-out settings
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationType(str, enum.Enum):
    # Admin / HOD
    TIMETABLE_PUBLISHED     = "TIMETABLE_PUBLISHED"
    SOLVER_COMPLETED        = "SOLVER_COMPLETED"
    SOLVER_FAILED           = "SOLVER_FAILED"
    RULE_CONFLICT_DETECTED  = "RULE_CONFLICT_DETECTED"
    CONSTRAINT_ADDED        = "CONSTRAINT_ADDED"
    SCENARIO_LOCKED         = "SCENARIO_LOCKED"

    # Teacher
    SCHEDULE_AVAILABLE      = "SCHEDULE_AVAILABLE"
    AVAILABILITY_REMINDER   = "AVAILABILITY_REMINDER"
    ROOM_CHANGED            = "ROOM_CHANGED"

    # Student (FFCS / Elective)
    REGISTRATION_OPEN       = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED     = "REGISTRATION_CLOSED"
    WISHLIST_CONFIRMED      = "WISHLIST_CONFIRMED"
    SLOT_CLASH_DETECTED     = "SLOT_CLASH_DETECTED"
    EXAM_SCHEDULE_PUBLISHED = "EXAM_SCHEDULE_PUBLISHED"

    # Planning module — teacher request flow
    TEACHER_REQUEST_RECEIVED  = "TEACHER_REQUEST_RECEIVED"   # Service HOD: new request arrived
    TEACHER_REQUEST_FULFILLED = "TEACHER_REQUEST_FULFILLED"  # Academic HOD: request was filled

    # Planning module — plan publish/approve workflow
    PLAN_SUBMITTED = "PLAN_SUBMITTED"  # HOD submits → all institution admins notified
    PLAN_APPROVED  = "PLAN_APPROVED"   # Admin approves → HOD + dept faculty notified
    PLAN_SENT_BACK = "PLAN_SENT_BACK"  # Admin sends back → HOD notified

    # System-wide
    SYSTEM_MAINTENANCE      = "SYSTEM_MAINTENANCE"


class NotificationChannel(str, enum.Enum):
    IN_APP = "IN_APP"
    EMAIL  = "EMAIL"
    PUSH   = "PUSH"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"),
        nullable=False,
        default=NotificationChannel.IN_APP,
        server_default=NotificationChannel.IN_APP.value,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} type={self.notification_type} "
            f"recipient={self.recipient_user_id} read={self.is_read}>"
        )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    push_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # JSON list of NotificationType values the user has muted
    disabled_types: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    def __repr__(self) -> str:
        return f"<NotificationPreference user={self.user_id}>"
