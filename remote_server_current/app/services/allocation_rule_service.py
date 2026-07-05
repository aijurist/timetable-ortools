"""
app/services/allocation_rule_service.py
=======================================
CRUD for AllocationRule + per-scenario seeding from the catalogue.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allocation_rule import AllocationRule
from app.models.audit_log import AuditAction
from app.schemas.allocation_rule import (
    ALLOCATION_RULE_CATALOGUE,
    AllocationRuleResponse,
    AllocationRuleUpdate,
)
import app.services.audit_log_service as audit_log_service


async def seed_rules_for_scenario(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> list[AllocationRule]:
    """
    Create default AllocationRule rows for a new scenario.
    Idempotent: skips rules that already exist.
    """
    created: list[AllocationRule] = []
    for entry in ALLOCATION_RULE_CATALOGUE:
        # Check if already exists
        stmt = select(AllocationRule).where(
            AllocationRule.scenario_id == scenario_id,
            AllocationRule.rule_code == entry["rule_code"],
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            continue

        rule = AllocationRule(
            scenario_id=scenario_id,
            rule_code=entry["rule_code"],
            is_enabled=entry["is_enabled"],
            params=entry["params"],
        )
        db.add(rule)
        created.append(rule)

    await db.flush()
    return created


async def get_rules_for_scenario(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> list[AllocationRuleResponse]:
    """Return all AllocationRule rows for the scenario."""
    stmt = select(AllocationRule).where(
        AllocationRule.scenario_id == scenario_id
    ).order_by(AllocationRule.rule_code)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [AllocationRuleResponse.model_validate(r) for r in rows]


async def get_rules_dict(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> dict[str, AllocationRule]:
    """Return {rule_code: AllocationRule} for quick lookup during allocation."""
    stmt = select(AllocationRule).where(
        AllocationRule.scenario_id == scenario_id
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {r.rule_code: r for r in rows}


async def update_rule(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    rule_code: str,
    payload: AllocationRuleUpdate,
) -> AllocationRuleResponse:
    """Update a single AllocationRule. Creates it from catalogue defaults if missing."""
    stmt = select(AllocationRule).where(
        AllocationRule.scenario_id == scenario_id,
        AllocationRule.rule_code == rule_code,
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()

    _before = {"is_enabled": rule.is_enabled, "params": rule.params} if rule is not None else None

    if rule is None:
        # Seed from catalogue
        catalogue_entry = next(
            (e for e in ALLOCATION_RULE_CATALOGUE if e["rule_code"] == rule_code), None
        )
        if catalogue_entry is None:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"AllocationRule code {rule_code!r} not in catalogue")

        rule = AllocationRule(
            scenario_id=scenario_id,
            rule_code=rule_code,
            is_enabled=catalogue_entry["is_enabled"],
            params=catalogue_entry["params"],
        )
        db.add(rule)
        await db.flush()

    if payload.is_enabled is not None:
        rule.is_enabled = payload.is_enabled
    if payload.params is not None:
        rule.params = payload.params

    await db.flush()
    await db.refresh(rule)
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="AllocationRule",
        entity_id=rule.id,
        entity_label=rule.rule_code,
        institution_id=None,
        before=_before,
        after={"is_enabled": rule.is_enabled, "params": rule.params},
    )
    return AllocationRuleResponse.model_validate(rule)
