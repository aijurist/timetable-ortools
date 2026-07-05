import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RoomType(str, enum.Enum):
    LAB = "LAB"
    LECTURE = "LECTURE"
    SEMINAR = "SEMINAR"
    AUDITORIUM = "AUDITORIUM"  # large-capacity venue for common events


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    room_type: Mapped[RoomType] = mapped_column(
        Enum(RoomType, name="room_type"),
        nullable=False,
        default=RoomType.LECTURE,
    )

    # Freeform tags for room filtering (equipment, accessibility, features).
    # e.g. ["PROJECTOR", "WHITEBOARD", "AIR_CONDITIONED", "SMART_BOARD", "OSCILLOSCOPE"]
    # Equipment identifiers go here too — there is no separate equipment column.
    # Enforced by: Course.room_tags ⊆ Room.tags  (ROOM_TAGS constraint)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Physical location — used by multi-campus/building transit constraints.
    # NULL is safe (single-campus institutions omit this).
    campus: Mapped[str | None] = mapped_column(String(100), nullable=True)
    building: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Per-room utilisation target for the ROOM_UTILISATION solver constraint.
    # Fraction of total session vars this room should ideally carry (0.0–1.0).
    # NULL = use the computed average across all active rooms (default).
    # Example: 0.15 means "this room should carry ~15% of all sessions".
    target_utilisation_pct: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True, default=None
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Room code={self.code!r} type={self.room_type} cap={self.capacity}>"
