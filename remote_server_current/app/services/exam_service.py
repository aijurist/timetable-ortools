"""
app/services/exam_service.py
==============================
Exam scheduling domain — scenarios, slots, and solver assignment results.

Responsibilities
----------------
* CRUD for ExamScenario (exam periods, e.g. "End Sem Nov 2026").
* ``add_slot`` / ``list_slots`` — manage date-time windows.
* ``get_assignments`` / ``clear_assignments`` — manage solver output rows.

The exam solver (Celery task) calls ``clear_assignments`` then bulk-inserts
ExamAssignment rows after a successful solve — same pattern as schedule_service.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.logger import logger
from app.models.audit_log import AuditAction
from app.models.exam import ExamAssignment, ExamScenario, ExamScenarioStatus, ExamSlot
from app.schemas.exam import (
    ExamScenarioCreate,
    ExamScenarioUpdate,
    ExamSlotCreate,
    ExamSlotUpdate,
)
import app.services.audit_log_service as audit_log_service


# ---------------------------------------------------------------------------
# ExamScenario
# ---------------------------------------------------------------------------


async def list_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[ExamScenario]:
    result = await db.execute(
        select(ExamScenario)
        .where(ExamScenario.institution_id == institution_id)
        .order_by(ExamScenario.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_exam_scenario_or_404(
    db: AsyncSession, scenario_id: uuid.UUID
) -> ExamScenario:
    result = await db.execute(
        select(ExamScenario).where(ExamScenario.id == scenario_id)
    )
    scenario = result.scalars().first()
    if scenario is None:
        raise NotFoundError(f"ExamScenario {scenario_id} not found")
    return scenario


async def create_scenario(
    db: AsyncSession,
    institution_id: uuid.UUID,
    payload: ExamScenarioCreate,
) -> ExamScenario:
    scenario = ExamScenario(
        institution_id=institution_id,
        academic_term_id=payload.academic_term_id,
        name=payload.name,
        status=ExamScenarioStatus.DRAFT,
        solver_config=payload.solver_config,
    )
    db.add(scenario)
    await db.flush()
    logger.info("ExamScenario created", exam_scenario_id=str(scenario.id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="ExamScenario",
        entity_id=scenario.id,
        entity_label=scenario.name,
        institution_id=institution_id,
    )
    return scenario


async def update_scenario(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    payload: ExamScenarioUpdate,
) -> ExamScenario:
    from app.models.notification import NotificationType  # noqa: PLC0415
    from app.models.user import UserRole  # noqa: PLC0415

    scenario = await get_exam_scenario_or_404(db, scenario_id)
    changes = payload.model_dump(exclude_unset=True)
    prev_status = scenario.status
    for field, value in changes.items():
        setattr(scenario, field, value)
    await db.flush()
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="ExamScenario",
        entity_id=scenario_id,
        entity_label=scenario.name,
        institution_id=scenario.institution_id,
        after={k: str(v) if v is not None else None for k, v in changes.items()},
    )
    # Notify admins when exam scenario is locked
    if "status" in changes and scenario.status == ExamScenarioStatus.LOCKED and prev_status != ExamScenarioStatus.LOCKED:
        try:
            import app.services.notification_service as _notif_svc  # noqa: PLC0415
            await _notif_svc.send_to_role(
                db,
                institution_id=scenario.institution_id,
                role=UserRole.ADMIN,
                notification_type=NotificationType.SCENARIO_LOCKED,
                title="Exam Scenario Locked",
                body=f"Exam scenario '{scenario.name}' is now locked for editing.",
                metadata={"exam_scenario_id": str(scenario_id)},
            )
        except Exception:
            logger.warning("Failed to send SCENARIO_LOCKED notification", exc_info=True)
    return scenario


# ---------------------------------------------------------------------------
# ExamSlot
# ---------------------------------------------------------------------------


async def list_slots(
    db: AsyncSession,
    exam_scenario_id: uuid.UUID,
) -> list[ExamSlot]:
    result = await db.execute(
        select(ExamSlot)
        .where(ExamSlot.exam_scenario_id == exam_scenario_id)
        .order_by(ExamSlot.date, ExamSlot.start_time)
    )
    return list(result.scalars().all())


async def get_slot_or_404(db: AsyncSession, slot_id: uuid.UUID) -> ExamSlot:
    result = await db.execute(select(ExamSlot).where(ExamSlot.id == slot_id))
    slot = result.scalars().first()
    if slot is None:
        raise NotFoundError(f"ExamSlot {slot_id} not found")
    return slot


async def add_slot(
    db: AsyncSession,
    exam_scenario_id: uuid.UUID,
    payload: ExamSlotCreate,
) -> ExamSlot:
    # Ensure the parent scenario exists
    parent_scenario = await get_exam_scenario_or_404(db, exam_scenario_id)

    slot = ExamSlot(
        exam_scenario_id=exam_scenario_id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        label=payload.label,
    )
    db.add(slot)
    await db.flush()
    logger.info("ExamSlot added", slot_id=str(slot.id), date=slot.date)
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="ExamSlot",
        entity_id=slot.id,
        entity_label=f"{payload.date} {payload.start_time}–{payload.end_time}",
        institution_id=parent_scenario.institution_id,
        after={"exam_scenario_id": str(exam_scenario_id), "date": payload.date},
    )
    return slot


async def update_slot(
    db: AsyncSession,
    slot_id: uuid.UUID,
    payload: ExamSlotUpdate,
) -> ExamSlot:
    slot = await get_slot_or_404(db, slot_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(slot, field, value)
    await db.flush()
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="ExamSlot",
        entity_id=slot_id,
        institution_id=None,
        after={k: str(v) if v is not None else None for k, v in changes.items()},
    )
    return slot


async def delete_slot(db: AsyncSession, slot_id: uuid.UUID) -> None:
    slot = await get_slot_or_404(db, slot_id)
    _exam_scenario_id = slot.exam_scenario_id
    await db.delete(slot)
    await db.flush()
    logger.info("ExamSlot deleted", slot_id=str(slot_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="ExamSlot",
        entity_id=slot_id,
        institution_id=None,
        before={"exam_scenario_id": str(_exam_scenario_id)},
    )


# ---------------------------------------------------------------------------
# ExamAssignment (solver output)
# ---------------------------------------------------------------------------


async def get_assignments(
    db: AsyncSession,
    exam_scenario_id: uuid.UUID,
) -> list[ExamAssignment]:
    result = await db.execute(
        select(ExamAssignment)
        .where(ExamAssignment.exam_scenario_id == exam_scenario_id)
        .order_by(ExamAssignment.created_at)
    )
    return list(result.scalars().all())


async def clear_assignments(
    db: AsyncSession,
    exam_scenario_id: uuid.UUID,
) -> int:
    """
    Delete all exam assignments for *exam_scenario_id*.

    Returns number of deleted rows.
    Called by the exam Celery task before writing new solver output.
    """
    result = await db.execute(
        delete(ExamAssignment)
        .where(ExamAssignment.exam_scenario_id == exam_scenario_id)
        .returning(ExamAssignment.id)
    )
    deleted = len(result.fetchall())
    await db.flush()
    logger.info(
        "ExamAssignments cleared",
        exam_scenario_id=str(exam_scenario_id),
        deleted=deleted,
    )
    return deleted
