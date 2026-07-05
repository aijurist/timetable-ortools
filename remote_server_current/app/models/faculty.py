import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EmploymentType(str, enum.Enum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    ADJUNCT = "ADJUNCT"


class DesignationType(str, enum.Enum):
    # Leadership
    PRINCIPAL = "PRINCIPAL"
    DIRECTOR = "DIRECTOR"
    DEAN_OF_ACADEMICS = "DEAN_OF_ACADEMICS"
    DEAN_OF_STUDENT_AFFAIRS = "DEAN_OF_STUDENT_AFFAIRS"
    DEAN_OF_RESEARCH = "DEAN_OF_RESEARCH"
    ASSOCIATE_DEAN = "ASSOCIATE_DEAN"
    # Teaching ranks
    EMERITUS_PROFESSOR = "EMERITUS_PROFESSOR"
    PROFESSOR = "PROFESSOR"
    PROFESSOR_OF_PRACTICE = "PROFESSOR_OF_PRACTICE"
    VISITING_PROFESSOR = "VISITING_PROFESSOR"
    ASSOCIATE_PROFESSOR = "ASSOCIATE_PROFESSOR"
    ASSISTANT_PROFESSOR = "ASSISTANT_PROFESSOR"
    SENIOR_LECTURER = "SENIOR_LECTURER"
    LECTURER = "LECTURER"
    LAB_INSTRUCTOR = "LAB_INSTRUCTOR"
    TEACHING_ASSISTANT = "TEACHING_ASSISTANT"


class Faculty(Base):
    __tablename__ = "faculty"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # Department is resolved from linked User.department_id (single source of truth).
    # This is consistent with StudentProfile which also relies on User.department_id.
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Bridge to the auth layer — 1-to-1 (mirrors StudentProfile.user_id pattern)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )
    user_rel: Mapped["User | None"] = relationship(
        "User", foreign_keys=[user_id]
    )

    staff_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    age: Mapped[int | None] = mapped_column(Integer, nullable=True)

    employment_type: Mapped[EmploymentType] = mapped_column(
        Enum(EmploymentType, name="employment_type"),
        nullable=False,
        default=EmploymentType.FULL_TIME,
    )

    designation: Mapped[DesignationType | None] = mapped_column(
        Enum(DesignationType, name="designationtype"),
        nullable=True,
        default=None,
    )

    # Hard cap — used by Tier 1 solver constraints
    max_weekly_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=20)

    # List of slot codes where this faculty is NOT available.
    # e.g. ["A3", "B5"] — cross-referenced against time_grids at solve time.
    availability_blacklist: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Positive scheduling preferences (soft constraints for the solver).
    # Shape: {"preferred_slots": ["A1","A2"], "preferred_days": ["MON","TUE","WED"],
    #         "preferred_rooms": ["<uuid>"], "max_daily_hours": 4}
    # NULL = no preferences (backward-compatible).
    preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)

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
        return f"<Faculty name={self.name!r} type={self.employment_type}>"
