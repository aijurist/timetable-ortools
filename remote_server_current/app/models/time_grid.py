import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimeGrid(Base):
    """
    Non-linear slot dictionary for a specific academic term.

    slots: a dict mapping slot codes to their time definitions.

    Example:
    {
        "A1": {"day": "MON", "start": "09:00", "end": "10:00", "period": "morning"},
        "A2": {"day": "MON", "start": "10:00", "end": "11:00", "period": "morning"},
        "B1": {"day": "MON", "start": "09:00", "end": "11:00", "period": "morning"},
        ...
    }

    Slot codes are opaque to the solver — it treats them as integer indices
    mapped from this dict at the start of each pipeline run.
    """

    __tablename__ = "time_grids"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # The full slot dictionary — read by the Celery task and passed
    # to the solver as SchedulerInput.time_grids.
    slots: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Soft-delete flag — inactive grids are excluded from solver input queries.
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
        slot_count = len(self.slots) if self.slots else 0
        return f"<TimeGrid name={self.name!r} slots={slot_count}>"
