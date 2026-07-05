import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SessionType(str, enum.Enum):
    LAB = "LAB"
    THEORY = "THEORY"
    BOTH = "BOTH"


class ElectiveType(str, enum.Enum):
    PROFESSIONAL = "PROFESSIONAL"
    OPEN = "OPEN"


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # Department this course belongs to (loose UUID — no FK for cross-service decoupling).
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # How many hours per week this course must be scheduled
    weekly_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    session_type: Mapped[SessionType] = mapped_column(
        Enum(SessionType, name="session_type"),
        nullable=False,
        default=SessionType.THEORY,
    )

    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Richer session breakdown for FFCS / Hybrid mode.
    # Traditional: None (rely on weekly_hours + session_type instead).
    # FFCS/Hybrid: {"L": 3, "T": 1, "P": 2} — Lecture/Tutorial/Practical hours.
    structure: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="e.g. {\"L\": 3, \"T\": 1, \"P\": 2}"
    )

    # Room tags this course needs — e.g. ["CORE"], ["SMART_BOARD"].
    # Also used as fallback when preferred_room_ids is empty.
    # NULL = no tag-based routing.
    room_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # If True, room_tags are treated as soft preference (penalty) rather than hard prune.
    # This is the permanent per-course default; overridable per-scenario via ScenarioRule(ROOM_TAGS).
    # Resolution: per-entity ScenarioRule > global ScenarioRule > this field > hard (default).
    room_tags_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Direct room pins (lecture/tutorial) — specific room UUIDs the course must use.
    # Takes priority over room_tags. Empty list = no pin → fall back to room_tags.
    preferred_room_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="List of room UUID strings for L/T components. Empty/null = fall back to room_tags.",
    )
    preferred_room_ids_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Direct room pins for the P (lab/practical) component — only used when course has structure.L/P/T.
    lab_preferred_room_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="List of room UUID strings for P (lab) component. Empty/null = fall back to lab_room_tags.",
    )
    lab_preferred_room_ids_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Tag filter for the P (lab) component — separate from room_tags which covers L/T.
    lab_room_tags: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Required room tags for the lab/practical component only.",
    )
    lab_room_tags_soft: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    elective_type: Mapped[ElectiveType | None] = mapped_column(
        Enum(ElectiveType, name="elective_type"), nullable=True
    )
    elective_semester: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
        return f"<Course code={self.code!r} name={self.name!r}>"
