"""
app/services/constraint_service.py
=====================================
Operations on ConstraintDefinitions (Tier 2 catalogue) and ScenarioRules.

Responsibilities
----------------
* ``list_definitions`` / ``search_definitions`` — used by the Agent tool layer.
* ``list_rules`` — all active/inactive rules for a scenario.
* ``add_rule`` — create a Tier 2 or Tier 3 rule for a scenario.
* ``toggle_rule`` — enable / disable without deleting.
* ``delete_rule`` — hard-delete (admin only).

Architecture note
-----------------
A rule is NEVER both Tier 2 and Tier 3.  The Pydantic validator in
``ScenarioRuleCreate`` enforces this; the service trusts it.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import any_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logger import logger
from app.models.constraint import ConstraintDefinition, ScenarioRule
from app.schemas.constraint import ScenarioRuleCreate, ScenarioRuleUpdate


# ---------------------------------------------------------------------------
# Param schema enrichment helpers
# ---------------------------------------------------------------------------

def _serialize_param_schema(code: str) -> dict | None:
    """
    Load a constraint class from the solver registry, call param_schema(),
    and return a JSON-serialisable dict of {param_key: {type, default, ...}}.

    Returns None when the constraint has no params or the module isn't loaded yet.
    """
    from solver_engine.constraints.registry import FULL_CATALOGUE, _import_build  # noqa: PLC0415

    defn = FULL_CATALOGUE.get(code)
    if defn is None:
        return None

    factory = _import_build(defn["module"])
    if factory is None:
        return None

    try:
        instance = factory({})
        raw_schema: dict = instance.param_schema()
    except Exception:
        return None

    if not raw_schema:
        return None

    _TYPE_NAMES = {int: "int", float: "float", str: "str", bool: "bool", list: "list[str]"}

    serialised: dict = {}
    for key, pdef in raw_schema.items():
        type_name = _TYPE_NAMES.get(pdef.type, str(pdef.type))
        # Override generic "list[str]" when item_schema describes a structured list
        if pdef.type is list and pdef.item_schema is not None:
            type_name = "list[object]"
        serialised[key] = {
            "type": type_name,
            "default": pdef.default,
            "required": pdef.required,
            "min_val": pdef.min_val,
            "max_val": pdef.max_val,
            "description": pdef.description or "",
            "item_schema": pdef.item_schema,
        }
    return serialised


# ---------------------------------------------------------------------------
# ConstraintDefinition queries (Agent tools use these)
# ---------------------------------------------------------------------------


async def list_definitions(
    db: AsyncSession,
    *,
    tier: Optional[int] = None,
) -> list[ConstraintDefinition]:
    """
    Return all Tier 2 constraint definitions, optionally filtered by tier.
    Each definition's param_schema is enriched at runtime from the solver engine
    so the frontend always sees current param types, defaults, and bounds even
    when the DB column is NULL.
    """
    from solver_engine.constraints.registry import FULL_CATALOGUE  # noqa: PLC0415

    q = select(ConstraintDefinition)
    if tier is not None:
        q = q.where(ConstraintDefinition.tier == tier)
    q = q.order_by(ConstraintDefinition.code)
    result = await db.execute(q)
    definitions = list(result.scalars().all())

    stale_codes = sorted(
        defn.code for defn in definitions if defn.code not in FULL_CATALOGUE
    )
    if stale_codes:
        logger.warning(
            "constraint_definitions contains stale rows not present in active solver registry",
            stale_codes=stale_codes,
        )
    definitions = [defn for defn in definitions if defn.code in FULL_CATALOGUE]

    # Enrich param_schema from live solver engine — overrides NULL DB values
    for defn in definitions:
        live = _serialize_param_schema(defn.code)
        if live is not None:
            defn.param_schema = live  # type: ignore[assignment]

    return definitions


async def search_definitions(
    db: AsyncSession,
    query: str,
) -> list[ConstraintDefinition]:
    """
    Full-text keyword search over ``ConstraintDefinition.keywords``.

    Uses PostgreSQL ``ANY`` operator for array overlap.
    Falls back to ILIKE on ``code`` and ``agent_guide`` if no results.
    """
    # Simple keyword split for array search
    terms = [t.lower() for t in query.split() if t]

    # Primary: match any keyword in the keywords[] array
    q_primary = select(ConstraintDefinition).where(
        any_(ConstraintDefinition.keywords).ilike(f"%{terms[0]}%") if terms else True  # type: ignore[arg-type]
    )
    result = await db.execute(q_primary)
    rows = list(result.scalars().all())
    if rows:
        return rows

    # Fallback: ILIKE on code or agent_guide
    if terms:
        pattern = f"%{terms[0]}%"
        q_fallback = select(ConstraintDefinition).where(
            ConstraintDefinition.code.ilike(pattern)
            | ConstraintDefinition.agent_guide.ilike(pattern)
        )
        result = await db.execute(q_fallback)
        rows = list(result.scalars().all())
    return rows


# ---------------------------------------------------------------------------
# ScenarioRule queries
# ---------------------------------------------------------------------------


async def list_rules(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    *,
    enabled_only: bool = False,
) -> list[ScenarioRule]:
    """List timetable scenario rules (scenario_id FK)."""
    q = select(ScenarioRule).where(ScenarioRule.scenario_id == scenario_id)
    if enabled_only:
        q = q.where(ScenarioRule.is_enabled == True)  # noqa: E712
    q = q.order_by(ScenarioRule.tier, ScenarioRule.created_at)
    result = await db.execute(q)
    return list(result.scalars().all())


async def list_rules_for_exam_scenario(
    db: AsyncSession,
    exam_scenario_id: uuid.UUID,
    *,
    enabled_only: bool = False,
) -> list[ScenarioRule]:
    """List exam scenario rules (exam_scenario_id FK)."""
    q = select(ScenarioRule).where(ScenarioRule.exam_scenario_id == exam_scenario_id)
    if enabled_only:
        q = q.where(ScenarioRule.is_enabled == True)  # noqa: E712
    q = q.order_by(ScenarioRule.tier, ScenarioRule.created_at)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_rule_or_404(
    db: AsyncSession,
    rule_id: uuid.UUID,
    *,
    scenario_id: uuid.UUID | None = None,
) -> ScenarioRule:
    q = select(ScenarioRule).where(ScenarioRule.id == rule_id)
    if scenario_id is not None:
        q = q.where(ScenarioRule.scenario_id == scenario_id)
    result = await db.execute(q)
    rule = result.scalars().first()
    if rule is None:
        raise NotFoundError(f"ScenarioRule {rule_id} not found")
    return rule


async def _mark_owner_scenario_dirty(
    db: AsyncSession,
    scenario_id: uuid.UUID | None,
) -> None:
    """Mark the owning timetable scenario dirty when a rule changes."""
    if scenario_id is None:
        return

    import app.services.scenario_service as scenario_svc  # noqa: PLC0415

    await scenario_svc.mark_dirty(db, scenario_id)


# ---------------------------------------------------------------------------
# ScenarioRule mutations
# ---------------------------------------------------------------------------


def _validate_rule_params(
    definition_code: str,
    params: dict | None,
    is_hard_constraint: bool | None,
) -> None:
    """
    Validate *params* against the constraint's declared ``param_schema()``.

    Raises ``ValidationError`` (→ 422) when:
    - An unknown param key is present.
    - A param value fails type/bounds check.
    - A required param is absent.
    - ``is_hard_constraint=False`` is set on a physics HARD constraint.

    Imports are lazy to avoid loading ortools at service startup.
    """
    from solver_engine.constraints.registry import FULL_CATALOGUE, _import_build  # noqa: PLC0415
    from solver_engine.contracts import PenaltyMode  # noqa: PLC0415

    defn = FULL_CATALOGUE.get(definition_code)
    if defn is None:
        return  # virtual/DSL constraint — no schema to validate

    factory = _import_build(defn["module"])
    if factory is None:
        return  # module not implemented yet — skip rather than block rule creation

    try:
        instance = factory({})
    except Exception:
        return  # can't instantiate — skip rather than block rule creation

    schema: dict = instance.param_schema()

    # ── Validate each supplied param ───────────────────────────────────────
    for key, value in (params or {}).items():
        param_def = schema.get(key)
        if param_def is None:
            raise ValidationError(
                f"Unknown param '{key}' for constraint '{definition_code}'"
            )
        try:
            param_def.validate(value)
        except ValueError as exc:
            raise ValidationError(
                f"Invalid value for param '{key}' on constraint '{definition_code}': {exc}"
            ) from exc

    # ── Check required params ──────────────────────────────────────────────
    for key, param_def in schema.items():
        if param_def.required and (params is None or key not in params):
            raise ValidationError(
                f"Required param '{key}' missing for constraint '{definition_code}'"
            )

    # ── Physics / hard-soft guard ──────────────────────────────────────────
    if defn.get("is_physics") and is_hard_constraint is False:
        if instance.metadata.penalty_mode == PenaltyMode.HARD:
            raise ValidationError(
                f"Constraint '{definition_code}' is a physics constraint with HARD "
                f"penalty mode and cannot be configured as soft (is_hard_constraint=False)."
            )


async def add_rule(
    db: AsyncSession,
    scenario_id: uuid.UUID | None,
    payload: ScenarioRuleCreate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> ScenarioRule:
    """
    Add a new rule to *scenario_id*.

    The ScenarioRuleCreate validator already ensures Tier 2 XOR Tier 3 logic.
    Params are validated against the constraint's declared param_schema().
    """
    from app.models.constraint import RuleType  # noqa: PLC0415
    is_distribution = (
        getattr(payload, "rule_type", None) == "DISTRIBUTION"
        or getattr(payload, "rule_type", None) == RuleType.DISTRIBUTION
    )

    if payload.definition_code is not None and not is_distribution:
        from solver_engine.constraints.registry import FULL_CATALOGUE  # noqa: PLC0415

        if payload.definition_code not in FULL_CATALOGUE:
            raise ValidationError(
                f"Constraint '{payload.definition_code}' is not available in the active solver registry."
            )
        if payload.definition_code in ("REQUIRED_TAGS", "ROOM_PREFERENCE", "ROOM_EQUIPMENT"):
            raise ValidationError(
                f"'{payload.definition_code}' is deprecated. "
                "Use ROOM_TAGS or ROOM_ASSIGNMENT instead. "
                "Equipment identifiers belong in Room.tags and Course.room_tags."
            )

    # Pre-fill params with defaults from the constraint's param_schema so the
    # solver always receives explicit values rather than falling back silently.
    # Distribution rules have no solver param schema — skip.
    filled_params = dict(payload.params or {})
    if payload.definition_code is not None and not is_distribution:
        live_schema = _serialize_param_schema(payload.definition_code)
        if live_schema:
            for key, pdef in live_schema.items():
                if key not in filled_params and pdef.get("default") is not None:
                    filled_params[key] = pdef["default"]

    # Validate params before touching the DB (skip for distribution rules)
    if payload.definition_code is not None and not is_distribution:
        _validate_rule_params(
            payload.definition_code,
            filled_params or None,
            payload.is_hard_constraint,
        )

    # Determine tier from payload
    tier = 2 if payload.definition_code is not None else 3

    # Defense-in-depth: per-entity rules are always HARD regardless of payload value.
    # The Pydantic validator already enforces this; this is a second guard at the DB layer.
    is_hard = True if payload.target_id is not None else payload.is_hard_constraint

    rule = ScenarioRule(
        scenario_id=scenario_id,
        exam_scenario_id=payload.exam_scenario_id,
        definition_code=payload.definition_code,
        tier=tier,
        params=filled_params or None,
        script_trigger=payload.script_trigger,
        script_logic=payload.script_logic,
        is_hard_constraint=is_hard,
        penalty_weight=payload.penalty_weight,
        soft_tier=payload.soft_tier,
        target_id=payload.target_id,
        is_enabled=True,
        created_by_agent=payload.created_by_agent,
        original_prompt=payload.original_prompt,
        agent_reasoning=payload.agent_reasoning,
        rule_type=RuleType.DISTRIBUTION if is_distribution else RuleType.CONSTRAINT,
    )
    db.add(rule)
    await db.flush()
    await _mark_owner_scenario_dirty(db, rule.scenario_id)

    kind = f"Tier{rule.tier}:{rule.definition_code or 'DSL'}"
    logger.info("Rule added", scenario_id=str(scenario_id), rule_id=str(rule.id), kind=kind)

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.RULE_ADDED,
        entity_type="ScenarioRule",
        entity_id=rule.id,
        entity_label=rule.definition_code or "DSL",
    )

    # Notify admins of the new constraint rule
    if rule.scenario_id is not None:
        try:
            from app.services import notification_service as _notif_svc  # noqa: PLC0415
            from app.models.notification import NotificationType  # noqa: PLC0415
            from app.models.user import UserRole  # noqa: PLC0415
            from app.models.scenario import Scenario as _Scenario  # noqa: PLC0415
            _scen = (await db.execute(select(_Scenario).where(_Scenario.id == rule.scenario_id))).scalars().first()
            if _scen and _scen.institution_id:
                await _notif_svc.send_to_role(
                    db,
                    institution_id=_scen.institution_id,
                    role=UserRole.ADMIN,
                    notification_type=NotificationType.CONSTRAINT_ADDED,
                    title="Constraint Rule Added",
                    body=f"Rule '{rule.definition_code or 'Custom'}' added to scenario '{_scen.name}'.",
                    metadata={
                        "scenario_id": str(rule.scenario_id),
                        "rule_id": str(rule.id),
                        "deep_link": f"/timetable?scenario={rule.scenario_id}",
                    },
                )
        except Exception:
            logger.warning("Failed to send CONSTRAINT_ADDED notification", exc_info=True)

    return rule


async def update_rule(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: ScenarioRuleUpdate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> ScenarioRule:
    rule = await get_rule_or_404(db, rule_id, scenario_id=scenario_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    # Defense-in-depth: per-entity rules must always remain HARD.
    # Coerce silently so that agents/coordinators can't accidentally soften them.
    if rule.target_id is not None:
        rule.is_hard_constraint = True
    await db.flush()
    await _mark_owner_scenario_dirty(db, rule.scenario_id)
    logger.info("Rule updated", rule_id=str(rule_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="ScenarioRule",
        entity_id=rule_id,
        entity_label=rule.definition_code or "DSL",
    )
    return rule


async def toggle_rule(
    db: AsyncSession,
    rule_id: uuid.UUID,
    enabled: bool,
    *,
    scenario_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> ScenarioRule:
    """Enable or disable a rule without deleting it."""
    rule = await get_rule_or_404(db, rule_id, scenario_id=scenario_id)
    rule.is_enabled = enabled
    await db.flush()
    await _mark_owner_scenario_dirty(db, rule.scenario_id)
    logger.info("Rule toggled", rule_id=str(rule_id), enabled=enabled)

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.TOGGLED,
        entity_type="ScenarioRule",
        entity_id=rule_id,
        entity_label=rule.definition_code or "DSL",
        after={"is_enabled": enabled},
    )
    return rule


async def delete_rule(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    rule_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> None:
    """Hard-delete a rule (admin action)."""
    rule = await get_rule_or_404(db, rule_id, scenario_id=scenario_id)
    owner_scenario_id = rule.scenario_id
    label = rule.definition_code or "DSL"
    await db.delete(rule)
    await db.flush()
    await _mark_owner_scenario_dirty(db, owner_scenario_id)
    logger.info("Rule deleted", rule_id=str(rule_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.RULE_REMOVED,
        entity_type="ScenarioRule",
        entity_id=rule_id,
        entity_label=label,
    )
