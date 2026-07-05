"""
Allocation rules endpoints.

GET    /scenarios/{scenario_id}/allocation-rules
PATCH  /scenarios/{scenario_id}/allocation-rules/{rule_code}
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, assert_same_institution, get_current_user, get_db
from app.schemas.allocation_rule import AllocationRuleResponse, AllocationRuleUpdate
import app.services.allocation_rule_service as rule_svc
import app.services.scenario_service as scenario_svc

router = APIRouter()


@router.get(
    "/scenarios/{scenario_id}/allocation-rules",
    response_model=list[AllocationRuleResponse],
    summary="List allocation rules for a scenario",
)
async def list_allocation_rules(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[AllocationRuleResponse]:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    # Ensure rules are seeded
    await rule_svc.seed_rules_for_scenario(db, scenario_id)
    await db.commit()
    return await rule_svc.get_rules_for_scenario(db, scenario_id)


@router.patch(
    "/scenarios/{scenario_id}/allocation-rules/{rule_code}",
    response_model=AllocationRuleResponse,
    summary="Update a single allocation rule",
)
async def update_allocation_rule(
    scenario_id: uuid.UUID,
    rule_code: str,
    body: AllocationRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> AllocationRuleResponse:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    result = await rule_svc.update_rule(db, scenario_id, rule_code, body)
    await db.commit()
    return result
