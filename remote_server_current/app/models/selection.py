"""
app/models/selection.py
=======================
HYBRID student selection: department-controlled registration windows and
committed multi-offering bundle selections.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SelectionWindowStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PREVIEW = "PREVIEW"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GroupSelectionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    DROPPED = "DROPPED"
    WAITLISTED = "WAITLISTED"


class EligibilitySource(str, enum.Enum):
    CORE_AUTO = "CORE_AUTO"
    PE = "PE"
    OE = "OE"
    MANUAL = "MANUAL"


class DepartmentSelectionWindow(Base):
    """Per (term, department, study_semester) registration window."""

    __tablename__ = "department_selection_windows"
    __table_args__ = (
        UniqueConstraint(
            "academic_term_id",
            "department_id",
            "study_semester",
            name="uq_selection_window_term_dept_sem",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_terms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    study_semester: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[SelectionWindowStatus] = mapped_column(
        Enum(SelectionWindowStatus, name="selection_window_status"),
        nullable=False,
        default=SelectionWindowStatus.DRAFT,
        server_default=SelectionWindowStatus.DRAFT.value,
    )
    preview_opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    allow_changes_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    published_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    max_selections_per_student: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
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


class StudentGroupSelection(Base):
    """HYBRID bundle header — one committed pick set per student per sem scope."""

    __tablename__ = "student_group_selections"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "academic_term_id",
            "study_year",
            "study_semester",
            name="uq_student_group_selection_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    study_year: Mapped[int] = mapped_column(Integer, nullable=False)
    study_semester: Mapped[int] = mapped_column(Integer, nullable=False)
    group_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[GroupSelectionStatus] = mapped_column(
        Enum(GroupSelectionStatus, name="group_selection_status"),
        nullable=False,
        default=GroupSelectionStatus.DRAFT,
        server_default=GroupSelectionStatus.DRAFT.value,
    )
    selection_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    published_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    invalidation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    student: Mapped["StudentProfile"] = relationship(  # type: ignore[name-defined]
        "StudentProfile", back_populates="group_selections"
    )
    registrations: Mapped[list["StudentRegistration"]] = relationship(  # type: ignore[name-defined]
        "StudentRegistration", back_populates="group_selection"
    )


class StudentCourseEligibility(Base):
    """Per-student course eligibility for selective PE/OE and auto-seeded core courses."""

    __tablename__ = "student_course_eligibility"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "course_id",
            "academic_term_id",
            "study_semester",
            name="uq_student_course_eligibility_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    study_semester: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[EligibilitySource] = mapped_column(
        Enum(EligibilitySource, name="eligibility_source"),
        nullable=False,
        default=EligibilitySource.MANUAL,
        server_default=EligibilitySource.MANUAL.value,
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

    student: Mapped["StudentProfile"] = relationship(  # type: ignore[name-defined]
        "StudentProfile", back_populates="course_eligibility"
    )
