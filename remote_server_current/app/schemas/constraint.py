"""
constraint.py
=============
Pydantic V2 schemas for ConstraintDefinition and ScenarioRule.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import PaginatedResponse


# ---------------------------------------------------------------------------
# ConstraintDefinition (read-only — written via Alembic seed, not the API)
# ---------------------------------------------------------------------------

class ConstraintDefinitionResponse(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    tier: int
    category: Optional[str] = None
    param_schema: Optional[dict[str, Any]]
    keywords: Optional[list[str]]
    agent_guide: Optional[str]
    natural_language_template: Optional[str] = None
    is_physics: bool = False
    domain: str = "constraint"
    penalty_mode: str = "hard"
    entity_type: Optional[str] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# ScenarioRule
# ---------------------------------------------------------------------------

class ScenarioRuleCreate(BaseModel):
    """
    A rule is either Tier 2 OR Tier 3 — never both.

    Tier 2: set ``definition_code`` + ``params``.
    Tier 3: set ``script_trigger`` + ``script_logic`` (DSL expression).
    """

    # Tier 2 fields
    definition_code: Optional[str] = None
    params: Optional[dict[str, Any]] = None

    # Tier 3 fields
    script_trigger: Optional[str] = Field(default=None, max_length=500)
    script_logic: Optional[str] = Field(
        default=None,
        description="simpleeval DSL expression, e.g. 'Faculty.age > 50'",
    )

    # Dual parent (timetable XOR exam — never both)
    exam_scenario_id: Optional[uuid.UUID] = Field(
        default=None,
        description="FK → exam_scenarios.id; set for exam rules, leave None for timetable rules",
    )

    # Constraint weighting
    is_hard_constraint: bool = Field(True, description="Hard (INFEASIBLE if violated) vs soft (penalty)")
    penalty_weight: int = Field(100, ge=0, description="Penalty objective weight for soft constraints")
    soft_tier: int = Field(2, ge=1, le=3, description="Penalty tier: 1=Critical(×10k), 2=Important(×100), 3=Preferred(×1)")

    # Optional per-entity override/disable target. This does not limit the
    # constraint to only this entity; it overrides how this entity is handled
    # while other entities still follow global/model defaults.
    target_id: Optional[uuid.UUID] = Field(
        default=None,
        description=(
            "Loose UUID for a per-entity override/disable target. Other entities still "
            "follow global or model defaults for the same constraint."
        ),
    )

    # Distribution vs solver-constraint discriminator
    rule_type: Optional[str] = Field(
        default=None,
        description="'CONSTRAINT' (default) or 'DISTRIBUTION'. Distribution rules bypass solver registry validation.",
    )

    # Agent provenance
    created_by_agent: bool = False
    original_prompt: Optional[str] = Field(default=None, description="Raw user prompt that triggered this rule")
    agent_reasoning: Optional[str] = Field(default=None, description="LLM reasoning chain for audit")

    @model_validator(mode="after")
    def validate_tier_exclusivity(self) -> "ScenarioRuleCreate":
        has_tier2 = self.definition_code is not None
        has_tier3 = self.script_logic is not None
        if not has_tier2 and not has_tier3:
            raise ValueError(
                "Provide either 'definition_code' (Tier 2) or 'script_logic' (Tier 3)."
            )
        if has_tier2 and has_tier3:
            raise ValueError(
                "A rule cannot be both Tier 2 (definition_code) and Tier 3 (script_logic)."
            )
        # Per-entity rules (target_id set) are always HARD — invariant enforced here
        if self.target_id is not None:
            object.__setattr__(self, "is_hard_constraint", True)
        return self


class ScenarioRuleUpdate(BaseModel):
    params: Optional[dict[str, Any]] = None
    script_trigger: Optional[str] = Field(default=None, max_length=500)
    script_logic: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_hard_constraint: Optional[bool] = None
    penalty_weight: Optional[int] = Field(None, ge=0)
    soft_tier: Optional[int] = Field(None, ge=1, le=3)
    target_id: Optional[uuid.UUID] = None


class ScenarioRuleResponse(BaseModel):
    id: uuid.UUID
    scenario_id: Optional[uuid.UUID]  # None for exam-scoped rules
    exam_scenario_id: Optional[uuid.UUID]
    definition_code: Optional[str]
    tier: int
    params: Optional[dict[str, Any]]
    script_trigger: Optional[str]
    script_logic: Optional[str]
    is_hard_constraint: bool
    penalty_weight: int
    soft_tier: int
    target_id: Optional[uuid.UUID]
    is_enabled: bool
    rule_type: Optional[str] = None
    created_by_agent: bool
    original_prompt: Optional[str]
    agent_reasoning: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


ScenarioRuleListResponse = PaginatedResponse[ScenarioRuleResponse]
ConstraintDefinitionListResponse = PaginatedResponse[ConstraintDefinitionResponse]
