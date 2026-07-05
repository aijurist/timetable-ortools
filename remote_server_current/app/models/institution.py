"""
models/institution.py
=====================
Infrastructure tier: tenants, departments, and academic terms.

These are the top-level "container" entities that all other resources
(Faculty, Room, Course, Scenario, TimeGrid) belong to via institution_id
or academic_term_id foreign keys.

Tables:
  institutions    — one row per university / college tenant.
  departments     — sub-units within an institution (e.g. CSE, ECE).
  academic_terms  — a semester / term period (e.g. "Fall 2026").
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SchedulingMode(str, enum.Enum):
    """Determines which solver strategy is applied institution-wide."""

    TRADITIONAL = "TRADITIONAL"  # fixed batch scheduling
    HYBRID = "HYBRID"  # choose-faculty elective system
    FFCS = "FFCS"  # fully-flexible credit system (VIT-style)


class AcademicTermStatus(str, enum.Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class TermType(str, enum.Enum):
    """Calendar structure of the academic term."""

    SEMESTER = "SEMESTER"
    TRIMESTER = "TRIMESTER"
    QUARTER = "QUARTER"
    ANNUAL = "ANNUAL"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Institution(Base):
    """
    Multi-tenant root entity.

    Every resource (faculty, room, course, scenario) is scoped to an
    institution via institution_id — stored as a plain UUID field (no FK)
    on the resource tables to allow cross-service decoupling.

    scheduling_mode drives which bucket/offering strategy the solver uses.
    """

    __tablename__ = "institutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Subdomain for the institution's login portal, e.g. "vit.exovance.io"
    domain: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

    # Controls which solver & UI features are enabled.
    scheduling_mode: Mapped[SchedulingMode | None] = mapped_column(
        Enum(SchedulingMode, name="scheduling_mode"),
        nullable=True,
        default=SchedulingMode.TRADITIONAL,
    )

    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UTC", server_default="UTC"
    )

    # Institution-wide solver defaults (overridable per-scenario via solver_config)
    # Shape: { "timeout_seconds": 120, "max_daily_hours": 8 }
    default_solver_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Regulatory body this institution falls under (e.g. "UGC", "AICTE", "VTU", "JNTU").
    # Used by the constraint recommendation engine to suggest compliance templates.
    regulatory_body: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Institution-wide default students-per-class.
    # Used when COHORT doesn't have explicit class_count and department.class_size is also NULL.
    # Resolution chain: explicit class_count > dept.class_size > institution.default_class_size.
    # NULL means coordinator must always provide explicit class_count on COHORT.
    default_class_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    # Relationships
    departments: Mapped[list["Department"]] = relationship(
        "Department", back_populates="institution", cascade="all, delete-orphan"
    )
    academic_terms: Mapped[list["AcademicTerm"]] = relationship(
        "AcademicTerm", back_populates="institution", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Institution name={self.name!r} mode={self.scheduling_mode}>"


class Department(Base):
    """
    Sub-unit of an institution (e.g. "Computer Science Engineering").

    Used for:
    - User/Course/OfferingBucket scoping (HOD access boundaries).
    - Reporting breakdowns by department.
    """

    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Short code used in JWT "dept" claim and display — e.g. "CSE", "ECE"
    code: Mapped[str] = mapped_column(String(20), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ACADEMIC = has students and builds its own course plan.
    # SERVICE  = provides faculty to other depts (Maths, Physics, English, etc.)
    dept_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ACADEMIC",
        server_default="ACADEMIC",
        comment="ACADEMIC = has students, builds own course plan. SERVICE = provides faculty to other depts.",
    )

    # Working days for this department — controls which days the solver assigns
    # sessions to.  NULL means "inherit all days from the institution time grid".
    # Example: ["MON","TUE","WED","THU","FRI"] for a Mon–Fri department,
    #          ["TUE","WED","THU","FRI","SAT"] for a Tue–Sat department.
    # Consumed by solver_input_service._load_department_working_days().
    working_days: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    # Early/late slot block thresholds for this department.
    # NULL = fall back to global BLOCK_EARLY_SLOTS / BLOCK_LATE_SLOTS ScenarioRule param.
    early_block_period: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    early_block_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    late_block_period: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    late_block_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Department-specific break windows for the solver.
    # Shape: [{"name": str, "slot_codes": [str], "duration_minutes": int}]
    # NULL = no department overrides; fall back to global MANDATORY_BREAK ScenarioRule.
    break_config: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    # If True, department breaks are enforced as soft penalties instead of hard blocks.
    breaks_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Dept-specific class size override for COHORT auto-setup.
    # Overrides institution.default_class_size for this dept's COHORTs.
    # NULL = use institution.default_class_size.
    class_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Head of Department — nullable FK to a faculty member in this department.
    # ondelete=SET NULL: faculty deletion self-heals to null instead of blocking.
    hod_faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("faculty.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        default=None,
    )
    hod_faculty: Mapped["Faculty | None"] = relationship(
        "Faculty", foreign_keys="[Department.hod_faculty_id]", lazy="select"
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

    # Relationship back to institution
    institution: Mapped["Institution"] = relationship(
        "Institution", back_populates="departments"
    )

    def __repr__(self) -> str:
        return f"<Department code={self.code!r} institution={self.institution_id}>"


class AcademicTerm(Base):
    """
    A semester / academic period tied to an institution.

    TimeGrid, ExamScenario, Scenario, and AnalyticsSnapshot all reference
    an academic_term_id (as a loose UUID — not FK — on most tables, to
    survive term deletion without cascading deletes on schedules).

    This table IS the authoritative definition of that UUID.
    """

    __tablename__ = "academic_terms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)  # "Fall 2026"
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Calendar structure — drives credit-to-session derivation and term-length assumptions.
    # NULL = SEMESTER (backward-compatible default).
    term_type: Mapped[TermType | None] = mapped_column(
        Enum(TermType, name="term_type", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )

    # Non-teaching dates within the term.  Consumed by solver_input_service to
    # exclude these dates from the available slot grid.
    # Shape: [{"date": "2026-10-02", "label": "Gandhi Jayanti"}, ...]
    holidays: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    status: Mapped[AcademicTermStatus] = mapped_column(
        Enum(AcademicTermStatus, name="academic_term_status"),
        nullable=False,
        default=AcademicTermStatus.PLANNING,
        server_default=AcademicTermStatus.PLANNING.value,
    )

    # Soft-delete flag — inactive terms are hidden from scheduling UI but preserved for history.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Soft-delete timestamp — set when user archives (soft-deletes) the term.
    # NULL = active/visible; non-NULL = hidden from normal queries.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
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

    # Relationship back to institution
    institution: Mapped["Institution"] = relationship(
        "Institution", back_populates="academic_terms"
    )

    def __repr__(self) -> str:
        return f"<AcademicTerm name={self.name!r} status={self.status}>"
