"""
models/elective_pool.py
=======================
An ElectivePool groups the teaching assignments that belong to ONE professional
or open elective slot (PE-1, OE-1, …) for a given dept + semester.

Scope: term-level (same as TeachingAssignment — no scenario_id).
The distribution engine puts all pool members into a single CHOOSE_COURSE bucket
with force_parallel_slots=True at cohort-distribution time.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.course import ElectiveType


class ElectivePool(Base):
    __tablename__ = "elective_pools"
    __table_args__ = (
        UniqueConstraint(
            "academic_term_id", "department_id", "study_semester", "label",
            name="uq_elective_pool_label",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # The CONSUMING dept (whose students attend this elective).
    # For OE, teaching assignments may come from a different dept.
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    study_semester: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Semester this elective pool is offered in.",
    )
    # "PE-1", "PE-2", "OE-1" — coordinator-chosen, unique per dept+sem+term.
    label: Mapped[str] = mapped_column(String(30), nullable=False)

    # PROFESSIONAL (PE) or OPEN (OE) — mirrors Course.elective_type.
    elective_type: Mapped[ElectiveType] = mapped_column(
        Enum(ElectiveType, name="elective_type"),
        nullable=False,
        default=ElectiveType.PROFESSIONAL,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ElectivePool {self.label} dept={self.department_id} sem={self.study_semester}>"
