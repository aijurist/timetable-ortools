import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ScheduledSession(Base):
    """
    One row per session-slot assignment produced by the solver.
    Written by tasks/schedule_tasks.py after a COMPLETED solve.
    Cleared and rewritten on every new successful solve for the scenario.
    """

    __tablename__ = "scheduled_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identifiers passed through from SchedulerOutput — kept as strings
    # so the solver stays decoupled from ORM model types.
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    course_id: Mapped[str] = mapped_column(String(255), nullable=False)
    faculty_id: Mapped[str] = mapped_column(String(255), nullable=False)
    room_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Slot code maps back to time_grids.slots key (e.g. "A1" = Mon 09:00-10:00).
    slot_code: Mapped[str] = mapped_column(String(50), nullable=False)

    # True when a coordinator has pinned this session; solver preserves pinned sessions
    # on re-run instead of starting from scratch.
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Original assignment values — set on first manual edit, never overwritten again.
    # Allows the UI to show "Originally: X" chips and detect coordinator overrides.
    original_room_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_slot_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_faculty_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Loose reference to the CourseOffering this session fulfils.
    # Required for FFCS seat counter updates and post-solve offering reconciliation.
    # Loose UUID (no FK) so the solver output stays decoupled from ORM types.
    offering_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    scenario: Mapped["Scenario"] = relationship(  # type: ignore[name-defined]
        "Scenario", back_populates="sessions"
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduledSession scenario={self.scenario_id} "
            f"session={self.session_id} slot={self.slot_code}>"
        )
