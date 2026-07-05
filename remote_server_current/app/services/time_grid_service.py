"""
app/services/time_grid_service.py
===================================
CRUD and slot-patch operations for TimeGrid (academic-term slot dictionaries).

The slot dictionary is the authoritative time mapping used by the solver.

Shape: { "A1": {"day": "MON", "start": "09:00", "end": "10:00", "period": "morning"}, ... }
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logger import logger
import app.services.audit_log_service as audit_log_service
from app.models.audit_log import AuditAction
from app.models.institution import AcademicTerm
from app.models.scenario import Scenario
from app.models.time_grid import TimeGrid
from app.schemas.time_grid import TimeGridCreate, TimeGridSlotPatch, TimeGridUpdate


async def _resolve_institution_id(db: AsyncSession, academic_term_id: uuid.UUID) -> uuid.UUID | None:
    """Look up the institution_id for a time grid via its academic term."""
    result = await db.execute(
        select(AcademicTerm.institution_id).where(AcademicTerm.id == academic_term_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_by_term(
    db: AsyncSession,
    academic_term_id: uuid.UUID,
) -> list[TimeGrid]:
    """Return all time grids for an academic term."""
    result = await db.execute(
        select(TimeGrid)
        .where(TimeGrid.academic_term_id == academic_term_id)
        .order_by(TimeGrid.name)
    )
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, grid_id: uuid.UUID) -> Optional[TimeGrid]:
    result = await db.execute(select(TimeGrid).where(TimeGrid.id == grid_id))
    return result.scalars().first()


async def get_or_404(db: AsyncSession, grid_id: uuid.UUID) -> TimeGrid:
    grid = await get_by_id(db, grid_id)
    if grid is None:
        raise NotFoundError(f"TimeGrid {grid_id} not found")
    return grid


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create(db: AsyncSession, payload: TimeGridCreate) -> TimeGrid:
    grid = TimeGrid(
        academic_term_id=payload.academic_term_id,
        name=payload.name,
        is_active=payload.is_active,
        slots={k: v.model_dump() for k, v in payload.slots.items()},
    )
    db.add(grid)
    await db.flush()
    if grid.is_active:
        await _deactivate_other_grids_for_term(
            db,
            academic_term_id=grid.academic_term_id,
            keep_grid_id=grid.id,
        )
    logger.info(
        "TimeGrid created",
        grid_id=str(grid.id),
        name=grid.name,
        slot_count=len(grid.slots),
    )
    institution_id = await _resolve_institution_id(db, grid.academic_term_id)
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="TimeGrid",
        entity_id=grid.id,
        entity_label=grid.name,
        institution_id=institution_id,
        after={"slot_count": len(grid.slots), "is_active": grid.is_active},
    )
    return grid


async def update(
    db: AsyncSession,
    grid_id: uuid.UUID,
    payload: TimeGridUpdate,
) -> TimeGrid:
    """
    Replace mutable fields (name and/or slots).
    Use ``patch_slots`` for surgical slot updates.
    """
    grid = await get_or_404(db, grid_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(grid, field, value)
    if changes.get("is_active") is True:
        await _deactivate_other_grids_for_term(
            db,
            academic_term_id=grid.academic_term_id,
            keep_grid_id=grid.id,
        )
    await db.flush()
    logger.info("TimeGrid updated", grid_id=str(grid_id))
    institution_id = await _resolve_institution_id(db, grid.academic_term_id)
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="TimeGrid",
        entity_id=grid_id,
        entity_label=grid.name,
        institution_id=institution_id,
        after={k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for k, v in changes.items() if k != "slots"},
    )
    return grid


async def patch_slots(
    db: AsyncSession,
    grid_id: uuid.UUID,
    patch: TimeGridSlotPatch,
) -> TimeGrid:
    """
    Surgical update of individual slots.

    * ``upsert`` — add or replace slot by code.
    * ``remove`` — delete slot code from the dict.

    This avoids replacing the entire JSON blob when only one slot changes.
    """
    grid = await get_or_404(db, grid_id)
    # Work on a shallow copy so SQLAlchemy detects the change
    slots: dict = dict(grid.slots or {})

    for code, definition in (patch.slots or {}).items():
        slots[code] = definition if isinstance(definition, dict) else definition.model_dump()

    for code in (patch.remove or []):
        slots.pop(code, None)

    grid.slots = slots
    await db.flush()
    logger.info(
        "TimeGrid slots patched",
        grid_id=str(grid_id),
        upserted=len(patch.slots or {}),
        removed=len(patch.remove or []),
    )
    institution_id = await _resolve_institution_id(db, grid.academic_term_id)
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="TimeGrid",
        entity_id=grid_id,
        entity_label=grid.name,
        institution_id=institution_id,
        after={"upserted": list((patch.slots or {}).keys()), "removed": list(patch.remove or [])},
    )
    return grid


async def delete(db: AsyncSession, grid_id: uuid.UUID) -> None:
    """Hard-delete a time grid."""
    grid = await get_or_404(db, grid_id)
    label = grid.name
    institution_id = await _resolve_institution_id(db, grid.academic_term_id)
    await db.delete(grid)
    await db.flush()
    logger.info("TimeGrid deleted", grid_id=str(grid_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="TimeGrid",
        entity_id=grid_id,
        entity_label=label,
        institution_id=institution_id,
    )


async def _deactivate_other_grids_for_term(
    db: AsyncSession,
    *,
    academic_term_id: uuid.UUID,
    keep_grid_id: uuid.UUID,
) -> None:
    """Ensure only one active grid exists for a term within the current transaction."""
    await db.execute(
        sa_update(TimeGrid)
        .where(
            TimeGrid.academic_term_id == academic_term_id,
            TimeGrid.id != keep_grid_id,
            TimeGrid.is_active == True,
        )
        .values(is_active=False)
    )


def resolve_grid_for_scenario(
    scenario: Scenario,
    selected_grid: Optional[TimeGrid],
    active_grids: list[TimeGrid],
) -> TimeGrid:
    """Resolve solver grid for a scenario with deterministic precedence.

    Order:
    1) selected_time_grid_id if present
    2) fallback active grid for scenario term
    3) raise error if no valid grid exists
    """
    if scenario.selected_time_grid_id:
        if selected_grid is None:
            raise ValueError(
                "Selected time grid is missing. Update selected_time_grid_id on scenario."
            )
        if selected_grid.academic_term_id != scenario.academic_term_id:
            raise ValueError(
                "Selected time grid does not belong to the scenario academic term."
            )
        return selected_grid

    term_active_grids = [
        g for g in active_grids if g.academic_term_id == scenario.academic_term_id
    ]
    if not term_active_grids:
        raise ValueError(
            "No active time grid found for scenario academic term. Activate a grid or set selected_time_grid_id."
        )

    # Deterministic fallback when legacy data has more than one active grid.
    term_active_grids.sort(
        key=lambda g: (
            g.updated_at if isinstance(g.updated_at, datetime) else datetime.min,
            g.created_at if isinstance(g.created_at, datetime) else datetime.min,
        ),
        reverse=True,
    )
    return term_active_grids[0]


async def resolve_slots_for_scenario(
    db: AsyncSession,
    scenario: Scenario,
) -> dict:
    """Resolve slot dictionary for solver input using scenario-first selection policy."""
    selected_grid: Optional[TimeGrid] = None
    if scenario.selected_time_grid_id:
        selected_grid = await get_by_id(db, scenario.selected_time_grid_id)

    result = await db.execute(
        select(TimeGrid).where(
            TimeGrid.academic_term_id == scenario.academic_term_id,
            TimeGrid.is_active == True,
        )
    )
    active_grids = list(result.scalars().all())
    grid = resolve_grid_for_scenario(scenario, selected_grid, active_grids)
    return grid.slots or {}
