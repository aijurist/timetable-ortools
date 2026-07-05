"""
app/models/exam.py
==================
Exam Scheduling module ORM models.

Tables
------
exam_scenarios      — one per exam period (e.g. "End Sem Nov 2026").
                      Separate CP-SAT model; shares rooms / batches / faculty from core.
exam_slots          — date + time windows available for exams within a scenario.
exam_assignments    — solver output: course × slot × room × invigilator × batch.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExamScenarioStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SOLVING = "SOLVING"
    SOLVED = "SOLVED"
    LOCKED = "LOCKED"


class ExamScenario(Base):
    __tablename__ = "exam_scenarios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # FK → scenarios' academic_term_id equivalent; kept as plain UUID (no FK constraint)
    # so exam module stays loosely coupled from the timetable scenario table.
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ExamScenarioStatus] = mapped_column(
        Enum(ExamScenarioStatus, name="exam_scenario_status"),
        nullable=False,
        default=ExamScenarioStatus.DRAFT,
        server_default=ExamScenarioStatus.DRAFT.value,
    )
    # Shape: {"timeout_seconds": 120, "min_gap_hours": 24}
    solver_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    # Relationships
    slots: Mapped[list["ExamSlot"]] = relationship(
        "ExamSlot", back_populates="exam_scenario", cascade="all, delete-orphan"
    )
    assignments: Mapped[list["ExamAssignment"]] = relationship(
        "ExamAssignment", back_populates="exam_scenario", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ExamScenario name={self.name!r} status={self.status}>"


class ExamSlot(Base):
    __tablename__ = "exam_slots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exam_scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # e.g. "2026-11-10"
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)   # "09:00"
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)     # "12:00"
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)  # "FN Session 1"

    # Relationships
    exam_scenario: Mapped["ExamScenario"] = relationship(
        "ExamScenario", back_populates="slots"
    )
    assignments: Mapped[list["ExamAssignment"]] = relationship(
        "ExamAssignment", back_populates="exam_slot"
    )

    def __repr__(self) -> str:
        return f"<ExamSlot date={self.date} {self.start_time}–{self.end_time}>"


class ExamAssignment(Base):
    """Solver output: one row per course × slot × room × batch."""

    __tablename__ = "exam_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exam_scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id"),
        nullable=False,
    )
    exam_slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_slots.id"),
        nullable=False,
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id"),
        nullable=False,
    )
    invigilator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("faculty.id"),
        nullable=True,
    )
    # Which batch (SchedulingTarget) sits this exam.
    # FK enforces referential integrity; SET NULL so deleting a target doesn't wipe assignments.
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduling_targets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    exam_scenario: Mapped["ExamScenario"] = relationship(
        "ExamScenario", back_populates="assignments"
    )
    exam_slot: Mapped["ExamSlot"] = relationship(
        "ExamSlot", back_populates="assignments"
    )

    def __repr__(self) -> str:
        return (
            f"<ExamAssignment course={self.course_id} slot={self.exam_slot_id}"
            f" room={self.room_id}>"
        )
