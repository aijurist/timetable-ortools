"""
app/models/student.py
=====================
Student academic profile and FFCS registration module.

Why this is separate from Faculty
----------------------------------
``Faculty`` is a **solver resource** — the CP-SAT model reads its
``max_weekly_hours``, ``availability_blacklist``, and ``employment_type``
directly as constraint data.

``Student`` is NOT a solver resource.  The solver works with
``SchedulingTarget`` (batches), never with individual students.
This module exists for three reasons:

  1. Enrollment metadata (batch, semester, program) — needed by Campus Brain
     to personalise the AI study assistant per student.
  2. FFCS registration — students self-register against ``CourseOffering`` rows
     once the timetable is published.  ``student_registrations`` records the
     confirmed picks + seat deduction.
  3. Wishlist — pre-registration shopping cart: students plan their schedule
     BEFORE the registration window opens.  Soft selections, no seat lock.

Tables
------
student_profiles      — 1-to-1 extension of ``users`` for STUDENT-role accounts.
student_registrations — confirmed FFCS offering registrations (seat deducted).
student_wishlists     — pre-registration shopping cart (draft; no seat lock).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RegistrationStatus(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"


# ---------------------------------------------------------------------------
# StudentProfile
# ---------------------------------------------------------------------------


class StudentProfile(Base):
    """
    Academic profile for a STUDENT-role User.

    One-to-one with ``users`` (via ``user_id`` unique FK).
    Mirrors the ``Faculty.user_id`` pattern from solver resources:
    the FK lives on ``StudentProfile``, keeping ``users`` clean.

    ``batch_id`` → ``scheduling_targets.id`` is the most critical field:
    it tells the solver which ``SchedulingTarget`` to use for NoGroupOverlap
    checks, and tells Campus Brain which study guide + timetable to show.
    ``batch_id`` is nullable (SET NULL on delete) because a student can exist
    before their batch is created (e.g., freshers before term setup).
    """

    __tablename__ = "student_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Bridge to the auth layer — 1-to-1
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # The batch / section this student belongs to.
    # Drives: timetable visibility, NoGroupOverlap constraint, study guide.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduling_targets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ---------- Academic identity ----------

    # University-issued enrollment / roll number.  Unique within institution.
    enrollment_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True, unique=True, index=True
    )

    # Degree family captured separately from the specific programme.
    # Examples: B.Tech, M.Tech, MBA, MCA.
    degree_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Full degree programme name (e.g. "B.Tech Computer Science Engineering").
    program: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Current academic semester (1-indexed; e.g. 5 = 3rd year, 1st sem).
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Year of study (1-4 for UG, 1-2 for PG).
    year_of_study: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ---------- Timestamps ----------

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # -----------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------

    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[user_id], back_populates="student_profile"
    )
    batch: Mapped["SchedulingTarget | None"] = relationship(  # type: ignore[name-defined]
        "SchedulingTarget"
    )
    registrations: Mapped[list["StudentRegistration"]] = relationship(
        "StudentRegistration", back_populates="student", cascade="all, delete-orphan"
    )
    wishlists: Mapped[list["StudentWishlist"]] = relationship(
        "StudentWishlist", back_populates="student", cascade="all, delete-orphan"
    )
    group_selections: Mapped[list["StudentGroupSelection"]] = relationship(
        "StudentGroupSelection", back_populates="student", cascade="all, delete-orphan"
    )
    course_eligibility: Mapped[list["StudentCourseEligibility"]] = relationship(
        "StudentCourseEligibility", back_populates="student", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StudentProfile user={self.user_id} "
            f"enr={self.enrollment_number!r} sem={self.semester}>"
        )


# ---------------------------------------------------------------------------
# StudentRegistration  (FFCS confirmed picks)
# ---------------------------------------------------------------------------


class StudentRegistration(Base):
    """
    A confirmed FFCS course-offering registration.

    Written by the registration API after:
      1. Verifying the offering has available seats (``booked_seats < max_seats``).
      2. Atomically incrementing ``course_offerings.booked_seats``.
      3. Checking the student's timetable has no slot clash.

    Dropping a registration decrements ``booked_seats`` and sets
    status = DROPPED (soft delete — preserve history).

    ``student_id`` → ``student_profiles.id`` (not users.id directly) so that
    enrollment and registration data stay in the same bounded context.
    """

    __tablename__ = "student_registrations"
    __table_args__ = (
        # One confirmed row per student × offering (re-registration is a new row
        # only after the previous one is DROPPED).
        UniqueConstraint(
            "student_id", "offering_id",
            name="uq_registration_student_offering",
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
    offering_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("course_offerings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[RegistrationStatus] = mapped_column(
        String(20),
        nullable=False,
        default=RegistrationStatus.CONFIRMED,
        server_default=RegistrationStatus.CONFIRMED.value,
    )

    student_group_selection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_group_selections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Timestamp the seat was locked — useful for conflict audit and race-condition
    # debugging on high-traffic FFCS registration days.
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # -----------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------

    student: Mapped["StudentProfile"] = relationship(
        "StudentProfile", back_populates="registrations"
    )
    offering: Mapped["CourseOffering"] = relationship(  # type: ignore[name-defined]
        "CourseOffering"
    )
    group_selection: Mapped["StudentGroupSelection | None"] = relationship(  # type: ignore[name-defined]
        "StudentGroupSelection", back_populates="registrations"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StudentRegistration student={self.student_id} "
            f"offering={self.offering_id} status={self.status}>"
        )


# ---------------------------------------------------------------------------
# StudentWishlist  (pre-registration shopping cart)
# ---------------------------------------------------------------------------


class StudentWishlist(Base):
    """
    Pre-registration shopping cart for FFCS planning.

    Students build their ideal timetable BEFORE the registration window opens.
    No seats are locked — this is purely a planning artefact.

    ``offering_ids`` is stored as a JSON array of UUIDs because:
      - It's a draft snapshot, not live relational data.
      - Students may add/remove offerings rapidly during planning.
      - A single row per named plan is simpler to version than many JOIN rows.

    A student can have multiple named wishlists per term
    (e.g. "Plan A — Morning", "Plan B — Backup").
    """

    __tablename__ = "student_wishlists"

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
        UUID(as_uuid=True),
        # Loose reference — wishlists survive term deletion (historical record).
        nullable=False,
        index=True,
    )

    # Human name for this plan: "Plan A - Morning", "Plan B - No 8 AM"
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Draft list of CourseOffering UUIDs the student is considering.
    # Not FK-constrained — allows stale offering IDs without constraint violations.
    # The registration API validates liveness before confirming.
    offering_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # -----------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------

    student: Mapped["StudentProfile"] = relationship(
        "StudentProfile", back_populates="wishlists"
    )

    def __repr__(self) -> str:  # pragma: no cover
        n = len(self.offering_ids or [])
        return (
            f"<StudentWishlist student={self.student_id} "
            f"name={self.name!r} offerings={n}>"
        )
