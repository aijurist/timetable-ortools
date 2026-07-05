import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RuleType(str, enum.Enum):
    """Discriminates solver constraint rules from distribution strategy rules."""
    CONSTRAINT   = "CONSTRAINT"    # CP-SAT clause or DSL expression
    DISTRIBUTION = "DISTRIBUTION"  # controls cohort allocation strategy (no CP-SAT math)


class ConstraintCategory(str, enum.Enum):
    """Grouping used by the agent search UI and definition browser."""

    GLOBAL = "GLOBAL"      # applies across the whole schedule
    RESOURCE = "RESOURCE"  # targets a specific room, faculty, or timegrid
    ENTITY = "ENTITY"      # targets a specific course or batch


class ConstraintDefinition(Base):
    """
    The static 'instruction manual' for the AI agent.
    One row per supported Tier 2 constraint type.
    Written by developers via Alembic seed migrations — not by users.
    """

    __tablename__ = "constraint_definitions"

    # Short uppercase identifier, e.g. "MAX_DAILY_HOURS", "MIN_GAP"
    code: Mapped[str] = mapped_column(String(100), primary_key=True)

    # Human-readable display name shown in the UI and agent responses.
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    # Plain-English description of what this constraint does.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    tier: Mapped[int] = mapped_column(Integer, nullable=False)  # always 2 for this table

    # Grouping for the agent's constraint browser and scope-based filtering.
    category: Mapped[ConstraintCategory | None] = mapped_column(
        Enum(ConstraintCategory, name="constraint_category"),
        nullable=True,
        default=ConstraintCategory.GLOBAL,
    )

    # JSON Schema describing valid param shapes.
    # e.g. {"max_hours": {"type": "int", "min": 1, "max": 12}}
    param_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Postgres text array — used by agent's search_definitions tool.
    # e.g. ["faculty", "max", "hours", "daily", "load"]
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Natural-language guide shown to the LLM when it picks this constraint.
    agent_guide: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Template the agent fills in when explaining a rule to the user.
    # e.g. "Limit {target} to {limit} hours per day."
    natural_language_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # TRUE for always-on physics constraints.
    # These can still be disabled via ScenarioRule.is_enabled=False but the UI
    # should warn the coordinator before they do so.
    is_physics: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Internal implementation domain — never exposed to coordinators.
    # "constraint"       → CP-SAT clause (registry-backed)
    # "variable_pruning" → var_builder pruning layer (on/off only, no params)
    domain: Mapped[str] = mapped_column(
        String(32), nullable=False, default="constraint", server_default="constraint"
    )

    # Intrinsic penalty pattern: hard | excess | binary
    # Developer-set via Alembic seed — not user-editable.
    # Exposed in ConstraintDefinitionResponse so the frontend shows the right UI controls.
    penalty_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hard", server_default="hard",
        comment="Intrinsic penalty pattern: hard|excess|binary (developer-set, not user-editable)",
    )

    # Entity type that per-entity ScenarioRule overrides target.
    # "faculty" | "department" | "course" | "room" | NULL (physics/global-only)
    # NULL = constraint has no per-entity override support (e.g. SESSION_COVERAGE).
    # Exposed in ConstraintDefinitionResponse so the frontend knows which entity picker to show.
    entity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Relationships
    rules: Mapped[list["ScenarioRule"]] = relationship(
        "ScenarioRule", back_populates="definition"
    )

    def __repr__(self) -> str:
        return f"<ConstraintDefinition code={self.code!r} tier={self.tier}>"


class ScenarioRule(Base):
    """
    An active constraint row for a specific scenario.

    Tier 2 rule: definition_code is set, params holds the JSON values.
    Tier 3 rule: definition_code is NULL, script_logic holds the DSL expression.
    A rule is NEVER both.

    Toggle active/inactive with is_enabled — never hard-delete.
    """

    __tablename__ = "scenario_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Tier 2: FK to constraint_definitions.code
    definition_code: Mapped[str | None] = mapped_column(
        String(100),
        ForeignKey("constraint_definitions.code", ondelete="SET NULL"),
        nullable=True,
    )

    tier: Mapped[int] = mapped_column(Integer, nullable=False)  # 2 or 3

    # Tier 2: validated JSON params matching definition.param_schema
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Tier 3: human-readable description of the rule's intent
    script_trigger: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tier 3: DSL expression compiled by solver_engine/compiler.py via simpleeval
    script_logic: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Toggle without deleting — Celery task reads WHERE is_enabled=TRUE only
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # --- Scope & Priority ---
    # UUID of a specific entity this rule applies to (e.g. a Faculty or Room id).
    # NULL = rule applies globally to all entities of the relevant type.
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Hard constraint = must be satisfied; soft = adds to penalty score on violation.
    is_hard_constraint: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Weight used by CP-SAT for soft constraints (higher = more costly to violate).
    penalty_weight: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )

    # Penalty tier: 1=Critical(×10k) 2=Important(×100) 3=Preferred(×1).
    # Controls how heavily this rule's soft penalty is weighted in the objective.
    soft_tier: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default="2",
        comment="Penalty tier: 1=Critical(×10k), 2=Important(×100), 3=Preferred(×1)",
    )

    # Discriminates CP-SAT constraint rules from distribution strategy rules.
    # CONSTRAINT (default) = solver clause; DISTRIBUTION = cohort allocation strategy.
    rule_type: Mapped[RuleType] = mapped_column(
        Enum(RuleType, name="rule_type", create_type=False),
        nullable=False,
        default=RuleType.CONSTRAINT,
        server_default="CONSTRAINT",
        comment="CONSTRAINT=CP-SAT/DSL rule; DISTRIBUTION=cohort allocation strategy",
    )

    # --- AI Audit Trail ---
    # TRUE when this row was inserted by the LangGraph agent (not a human admin).
    created_by_agent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # The raw user message that caused the agent to create this rule.
    # e.g. "Don't give Prof Smith morning classes"
    original_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The agent's explanation of why it chose this particular constraint.
    # e.g. "Mapped 'morning' to 08:00–12:00 availability blocker for Faculty X."
    agent_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Links this rule to an exam scenario instead of a timetable scenario.
    # A rule belongs to EITHER a timetable scenario OR an exam scenario — never both.
    exam_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_scenarios.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    # Relationships
    scenario: Mapped["Scenario"] = relationship(  # type: ignore[name-defined]
        "Scenario", back_populates="rules"
    )
    definition: Mapped["ConstraintDefinition | None"] = relationship(
        "ConstraintDefinition", back_populates="rules"
    )

    def __repr__(self) -> str:
        kind = f"Tier2:{self.definition_code}" if self.definition_code else "Tier3:DSL"
        return f"<ScenarioRule {kind} enabled={self.is_enabled}>"
