"""
models/solver_job.py
====================
Solver audit trail: immutable per-run snapshots and conflict diagnostics.

Tables:
  solver_jobs    — one row per CP-SAT solve attempt; stores full config +
                   constraint snapshots for rollback / diff-ing.
  job_conflicts  — per-constraint violation records when a solve returns
                   INFEASIBLE; read by the Agent's self-correction loop.

Architecture notes:
- `solver_jobs` rows are NEVER updated after creation (immutable audit log).
- The Agent reads `job_conflicts` to understand WHY a solve was infeasible
  and which constraints to relax.
- A `SolverJob` belongs to a Scenario (FK); deleting the scenario cascades.
- `constraints_snapshot` + `config_snapshot` capture the exact state fed to
  the solver so any past run can be reproduced or diffed.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
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


class SolverJobStatus(str, enum.Enum):
    PENDING = "PENDING"       # queued, not yet started
    RUNNING = "RUNNING"       # CP-SAT solver active
    OPTIMAL = "OPTIMAL"       # feasible + optimal solution found
    FEASIBLE = "FEASIBLE"     # feasible but time-limit hit (sub-optimal)
    INFEASIBLE = "INFEASIBLE"  # no valid schedule exists
    FAILED = "FAILED"         # Python / system error during solve


class ConflictSeverity(str, enum.Enum):
    HARD = "HARD"    # must be resolved — solve will remain INFEASIBLE
    SOFT = "SOFT"    # quality issue — increases penalty score


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SolverJob(Base):
    """
    Immutable audit record for a single CP-SAT solver run.

    Created when the Celery task starts; status + result fields are updated
    exactly once when the task completes.  Never updated after that.

    Key use-cases:
    1. Rollback: restore `result_schedule` from a previous OPTIMAL job.
    2. Diff: compare `constraints_snapshot` across jobs to see what changed.
    3. Performance: `score_summary` tracks objective value + wall-clock time.
    """

    __tablename__ = "solver_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Input snapshots (captured at task start) ---
    # Full JSON of all ScenarioRule rows fed to the solver.
    constraints_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    # SolverConfig dict (merged: system defaults → institution → scenario overrides).
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    # --- Output (written at task completion) ---
    # Serialised list of ScheduledSession dicts — mirrors the DB rows written.
    result_schedule: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[SolverJobStatus] = mapped_column(
        Enum(SolverJobStatus, name="solver_job_status"),
        nullable=False,
        default=SolverJobStatus.PENDING,
        server_default=SolverJobStatus.PENDING.value,
        index=True,
    )

    # Summary: objective value, gap %, wall-clock seconds, num_sessions_scheduled.
    # e.g. { "objective": 0, "gap_pct": 0.0, "wall_seconds": 4.2, "sessions": 48,
    #         "phase_times": {...}, "total_vars": 1200, "pruned_vars": 450 }
    score_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Full debug snapshot: constraint_results, conflicts, utilisation, phase_times.
    # Large blob — only loaded on demand (not eager-loaded by list queries).
    telemetry_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Ordered list of solver progress events captured during the run.
    # Each element is a JSON-serialisable dict (same shape as the Redis stream entries).
    # Written once at job completion so the log is available permanently, even
    # after the Redis stream key expires (1-hour TTL).
    # e.g. [{"phase": "pipeline_start", "sessions": 45}, {"phase": "solver_complete", ...}]
    log_entries: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Celery task UUID — set immediately when the task is dispatched so the
    # cancel endpoint can revoke it even before the worker picks it up.
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    conflicts: Mapped[list["JobConflict"]] = relationship(
        "JobConflict", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<SolverJob scenario={self.scenario_id} status={self.status}>"


class JobConflict(Base):
    """
    One infeasibility record produced by the constraint analysis pass.

    Populated when a solve returns INFEASIBLE. The Agent's self-correction
    loop reads these rows via the `get_conflicts` tool to decide which
    Tier 2 params to relax (e.g. reduce MAX_DAILY_HOURS from 4 to 5).

    `entities` is a free-form JSON array of the offending resource UUIDs:
    e.g. [{"type": "faculty", "id": "..."}]
    """

    __tablename__ = "job_conflicts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solver_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Which constraint definition triggered this conflict.
    constraint_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    severity: Mapped[ConflictSeverity] = mapped_column(
        Enum(ConflictSeverity, name="conflict_severity"),
        nullable=False,
        default=ConflictSeverity.HARD,
    )

    # Human-readable description generated by the solver analysis pass.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JSON array of involved entity references.
    # e.g. [{"type": "faculty", "id": "uuid"}, {"type": "room", "id": "uuid"}]
    entities: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # ── Conflict diagnosis fields (populated by UNSAT-core / preflight pass) ──

    # Short machine-readable code, e.g. "UNSAT_CORE", "DOMAIN_COLLAPSE".
    conflict_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Pipeline stage that produced this conflict:
    # "UNSAT_CORE" | "PREFLIGHT" | "HEURISTIC" | "fallback"
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 0.0–1.0 certainty score assigned by the analysis pass.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Supporting evidence (e.g. pruned slot codes, domain sizes).
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Suggested relaxation actions for the Agent's self-correction loop.
    recommended_actions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    job: Mapped["SolverJob"] = relationship("SolverJob", back_populates="conflicts")

    def __repr__(self) -> str:
        return (
            f"<JobConflict job={self.job_id} code={self.constraint_code!r}"
            f" severity={self.severity}>"
        )
