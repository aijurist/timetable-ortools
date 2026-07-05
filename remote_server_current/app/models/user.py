"""
user.py
=======
ORM model for platform identity, authentication, and role-based access.

Table
-----
  users   — one row per registered platform user across all institutions.

Role Hierarchy
--------------
  SUPER_ADMIN  Exovance staff.  Cross-institution.  Can impersonate any user.
  ADMIN        Institution registrar / timetable coordinator.
               Full CRUD on scenarios, courses, rooms, faculty for their institution.
  HOD          Head of Department.  Can add/edit constraints for their department.
               Read-only on other departments.
  TEACHER      Maps 1-to-1 with a Faculty row via faculty.user_id.
               Can view their timetable and submit availability preferences.
  STUDENT      Can view published timetables for their enrolled courses.
               No write access to scheduling resources.

Auth Notes
----------
* Passwords are stored as bcrypt hashes (passlib CryptContext).
* JWTs contain: { sub: user.id, role: user.role, institution_id, dept: departments.code }.
* The link between User and Faculty lives on Faculty.user_id (mirrors the
  StudentProfile.user_id pattern). A Faculty row may exist without a User.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.faculty import DesignationType


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UserRole(str, enum.Enum):
    """Platform-wide role.  Checked at the service layer, not just JWT."""

    STUDENT = "student"
    TEACHER = "teacher"
    HOD = "hod"               # Head of Department
    ADMIN = "admin"           # Institution-level administrator
    SUPER_ADMIN = "super_admin"  # Exovance platform staff


class GenderType(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(Base):
    """
    Platform identity record.

    One row per registered user.  ``institution_id`` is nullable to
    accommodate SUPER_ADMIN accounts that span all institutions.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Null only for SUPER_ADMIN accounts (cross-institution Exovance staff).
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )

    # bcrypt hash via passlib.  Never expose in API responses.
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserRole.STUDENT,
        server_default=UserRole.STUDENT.value,
        index=True,
    )

    # Typed FK to the departments table — enables proper DB joins for HOD scoping.
    # Nullable: SUPER_ADMIN has no department; ADMIN may span departments.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ---- Account state ----
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Profile
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Academic title (e.g. Principal, Dean) — mirrors Faculty.designation for
    # institution-wide leadership roles that don't require a department.
    academic_title: Mapped[DesignationType | None] = mapped_column(
        Enum(DesignationType, name="designationtype"),
        nullable=True,
        default=None,
    )

    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gender: Mapped["GenderType | None"] = mapped_column(
        Enum(GenderType, name="gendertype", create_type=False),
        nullable=True,
        default=None,
    )

    # Last successful JWT login — useful for security audits and session expiry.
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    # -----------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------

    # Primary Department resolved from department_id FK (loaded via selectinload in auth flow).
    department_rel: Mapped["Department | None"] = relationship(  # type: ignore[name-defined]
        "Department", foreign_keys=[department_id]
    )

    # The linked StudentProfile (present only for STUDENT-role users).
    student_profile: Mapped["StudentProfile | None"] = relationship(  # type: ignore[name-defined]
        "StudentProfile",
        primaryjoin="User.id == foreign(StudentProfile.user_id)",
        back_populates="user",
        uselist=False,
    )

    # Conversation threads started by this user.
    agent_sessions: Mapped[list["AgentSession"]] = relationship(  # type: ignore[name-defined]
        "AgentSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<User id={self.id} email={self.email!r} "
            f"role={self.role} institution={self.institution_id}>"
        )

