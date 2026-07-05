"""
app/models/allocation_rule.py
=============================
AllocationRule: per-scenario toggle for allocation engine rules.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AllocationRule(Base):
    """
    Per-scenario allocation rule toggle.

    rule_code: one of the catalogue codes (WORKLOAD_CAP, DEPT_PREFERENCE, etc.)
    is_enabled: whether the rule is active
    params: JSON with optional parameters (e.g. {penalty: 0.3, max_courses: 3})
    """

    __tablename__ = "allocation_rules"
    __table_args__ = (
        UniqueConstraint("scenario_id", "rule_code", name="uq_allocation_rule_scenario_code"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True, default=lambda: str(uuid.uuid4()))
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    params: Mapped[dict] = mapped_column(JSONB, nullable=True, default=dict, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AllocationRule scenario={self.scenario_id} code={self.rule_code} enabled={self.is_enabled}>"
