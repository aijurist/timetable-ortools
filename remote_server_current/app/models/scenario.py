import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.institution import SchedulingMode


class ScenarioStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INFEASIBLE = "INFEASIBLE"
    FAILED = "FAILED"
    STALE = "STALE"
    PAUSED = "PAUSED"


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    academic_term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    selected_time_grid_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    scheduling_mode: Mapped[SchedulingMode | None] = mapped_column(
        Enum(SchedulingMode, name="scheduling_mode"),
        nullable=True,
        default=None,
        comment="Overrides institution.scheduling_mode. NULL = inherit from institution.",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Self-referential FK for scenario forking ("Git branch" for schedules).
    # NULL = root scenario; non-NULL = forked from parent_scenario_id.
    parent_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    current_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solver_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solver_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    auto_publish_latest: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[ScenarioStatus] = mapped_column(
        Enum(ScenarioStatus, name="scenario_status"),
        nullable=False,
        default=ScenarioStatus.DRAFT,
        server_default=ScenarioStatus.DRAFT.value,
    )

    # Per-scenario solver tuning — overrides system defaults.
    # Shape: { "timeout_seconds": 60, "strategy": "AUTOMATIC", "num_workers": 4 }
    solver_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Live Celery task id — used to revoke/pause a running job.
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Warm-start hint snapshot from the last solve (var_name → value).
    # Passed to solver on resume via SolverConfig.warm_start_hints.
    best_hint: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # True whenever scenario_rules or data changed since last COMPLETED solve.
    # Frontend shows "⚠ Changes pending — re-run to apply".
    is_dirty: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    assignment_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="MANUAL",
        server_default="MANUAL",
        comment="MANUAL = HOD assigns all; SOLVER_FILL = solver auto-fills unassigned sections.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    rules: Mapped[list["ScenarioRule"]] = relationship(  # type: ignore[name-defined]
        "ScenarioRule", back_populates="scenario", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["ScheduledSession"]] = relationship(  # type: ignore[name-defined]
        "ScheduledSession", back_populates="scenario", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Scenario id={self.id} name={self.name!r} status={self.status}>"
