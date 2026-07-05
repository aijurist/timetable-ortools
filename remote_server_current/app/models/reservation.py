"""
app/models/reservation.py
==========================
Ad-hoc Resource Reservation module ORM model.

Table
-----
reservations    — room booking requests outside the scheduled timetable.
                  Conflict detection is handled at the API layer by querying
                  course_offerings (timetable) and exam_assignments — no solver needed.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# NOTE: requested_by / approved_by deliberately point to users.id, not faculty.id.
# This allows non-faculty roles (admin, HOD) to manage reservations.

from app.db.base import Base


class ReservationStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id"),
        nullable=False,
        index=True,
    )
    # User who submitted the reservation request (any role: faculty, HOD, admin).
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    # Admin / HOD who approved or rejected the request.
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    # Date + time stored as plain strings so we don't depend on a time-grid model.
    # The API layer handles time-grid expansion before conflict checks.
    date: Mapped[str] = mapped_column(String(10), nullable=False)        # "2026-11-10"
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)   # "14:00"
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)     # "16:00"

    # Human label for the booking: "Guest lecture", "Extra class CS202"
    purpose: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="reservation_status"),
        nullable=False,
        default=ReservationStatus.PENDING,
        server_default=ReservationStatus.PENDING.value,
    )

    # Timestamp of the last API-layer conflict check for audit trail.
    conflict_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    # Relationships
    requester: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[requested_by]
    )
    approver: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[approved_by]
    )

    def __repr__(self) -> str:
        return (
            f"<Reservation room={self.room_id} date={self.date}"
            f" {self.start_time}–{self.end_time} status={self.status}>"
        )
