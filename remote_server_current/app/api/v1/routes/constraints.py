"""
Constraints router — manage constraint definitions and scenario rules.

GET    /constraints/definitions               List all ConstraintDefinitions.
GET    /constraints/definitions/{code}        Get a single definition by code.
GET    /constraints/scenarios/{id}/rules      List active rules for a scenario.
POST   /constraints/scenarios/{id}/rules      Add a rule to a scenario.
PATCH  /constraints/scenarios/{id}/rules/{rule_id}   Update params or toggle.
DELETE /constraints/scenarios/{id}/rules/{rule_id}   Remove a rule.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser, PaginationParams, get_current_user, get_db, get_pagination,
    assert_same_institution,
)
from app.schemas.constraint import (
    ConstraintDefinitionResponse,
    ScenarioRuleCreate,
    ScenarioRuleResponse,
    ScenarioRuleUpdate,
)
import app.services.constraint_service as constraint_svc
import app.services.scenario_service as scenario_svc

router = APIRouter()


# ---------------------------------------------------------------------------
# Definitions (read-only — seeded by developers via migrations)
# ---------------------------------------------------------------------------

@router.get(
    "/definitions",
    response_model=List[ConstraintDefinitionResponse],
    summary="List all constraint definitions (the AI instruction manual)",
)
async def list_definitions(
    tier: Optional[int] = Query(default=None, ge=1, le=3, description="Filter by tier (1, 2, or 3)"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> List[ConstraintDefinitionResponse]:
    items = await constraint_svc.list_definitions(db, tier=tier)
    return [ConstraintDefinitionResponse.model_validate(d) for d in items]


@router.get(
    "/definitions/{code}",
    response_model=ConstraintDefinitionResponse,
    summary="Get a single constraint definition by its code",
)
async def get_definition(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ConstraintDefinitionResponse:
    items = await constraint_svc.list_definitions(db)
    match = next((d for d in items if d.code == code), None)
    if match is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(f"Constraint definition '{code}' not found")
    return ConstraintDefinitionResponse.model_validate(match)


# ---------------------------------------------------------------------------
# Scenario rules
# ---------------------------------------------------------------------------

@router.get(
    "/scenarios/{scenario_id}/rules",
    response_model=List[ScenarioRuleResponse],
    summary="List constraint rules for a scenario",
)
async def list_rules(
    scenario_id: uuid.UUID,
    enabled_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> List[ScenarioRuleResponse]:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    rules = await constraint_svc.list_rules(db, scenario_id, enabled_only=enabled_only)
    return [ScenarioRuleResponse.model_validate(r) for r in rules]


@router.post(
    "/scenarios/{scenario_id}/rules",
    response_model=ScenarioRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a Tier 2 or Tier 3 constraint rule to a scenario",
)
async def add_rule(
    scenario_id: uuid.UUID,
    payload: ScenarioRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ScenarioRuleResponse:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    rule = await constraint_svc.add_rule(
        db, scenario_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(rule)
    return ScenarioRuleResponse.model_validate(rule)


@router.patch(
    "/scenarios/{scenario_id}/rules/{rule_id}",
    response_model=ScenarioRuleResponse,
    summary="Update rule params or enable/disable toggle",
)
async def update_rule(
    scenario_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: ScenarioRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ScenarioRuleResponse:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    rule = await constraint_svc.update_rule(
        db, scenario_id, rule_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(rule)
    return ScenarioRuleResponse.model_validate(rule)


@router.delete(
    "/scenarios/{scenario_id}/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a constraint rule",
)
async def delete_rule(
    scenario_id: uuid.UUID,
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    await constraint_svc.delete_rule(
        db, scenario_id, rule_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Exam scenario rules
# ---------------------------------------------------------------------------

@router.get(
    "/exam-scenarios/{exam_scenario_id}/rules",
    response_model=List[ScenarioRuleResponse],
    summary="List constraint rules for an exam scenario",
)
async def list_exam_rules(
    exam_scenario_id: uuid.UUID,
    enabled_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> List[ScenarioRuleResponse]:
    rules = await constraint_svc.list_rules_for_exam_scenario(
        db, exam_scenario_id, enabled_only=enabled_only
    )
    return [ScenarioRuleResponse.model_validate(r) for r in rules]


@router.post(
    "/exam-scenarios/{exam_scenario_id}/rules",
    response_model=ScenarioRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a Tier 2 or Tier 3 constraint rule to an exam scenario",
)
async def add_exam_rule(
    exam_scenario_id: uuid.UUID,
    payload: ScenarioRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ScenarioRuleResponse:
    """Adds a rule scoped to an exam scenario (exam_scenario_id is injected automatically)."""
    patched = payload.model_copy(update={"exam_scenario_id": exam_scenario_id})
    rule = await constraint_svc.add_rule(
        db, None, patched,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(rule)
    return ScenarioRuleResponse.model_validate(rule)
