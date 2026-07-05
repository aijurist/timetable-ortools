"""Department-controlled registration windows for HYBRID student selection."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logger import logger
from app.models.institution import Department
from app.models.notification import NotificationType
from app.models.selection import DepartmentSelectionWindow, SelectionWindowStatus
from app.models.user import UserRole
from app.schemas.selection import SelectionWindowUpsert

import app.services.notification_service as notification_svc
import app.services.selection_invalidation_service as invalidation_svc
from app.services.selection_invalidation_service import INVALIDATION_SCENARIO_SWITCHED


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_effective_phase(window: DepartmentSelectionWindow) -> str:
    """Return PREVIEW | OPEN | CLOSED based on status + timestamps."""
    now = _utcnow()
    if window.status == SelectionWindowStatus.CLOSED:
        return "CLOSED"
    if window.status == SelectionWindowStatus.OPEN:
        if window.registration_closes_at and now > window.registration_closes_at:
            return "CLOSED"
        return "OPEN"
    if window.status == SelectionWindowStatus.PREVIEW:
        if window.registration_opens_at and now >= window.registration_opens_at:
            if window.registration_closes_at and now > window.registration_closes_at:
                return "CLOSED"
            return "OPEN"
        return "PREVIEW"
    # DRAFT
    if window.preview_opens_at and now >= window.preview_opens_at:
        if window.registration_opens_at and now >= window.registration_opens_at:
            if window.registration_closes_at and now > window.registration_closes_at:
                return "CLOSED"
            return "OPEN"
        return "PREVIEW"
    return "DRAFT"


async def get_window(
    db: AsyncSession,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> DepartmentSelectionWindow | None:
    return await db.scalar(
        select(DepartmentSelectionWindow).where(
            DepartmentSelectionWindow.academic_term_id == academic_term_id,
            DepartmentSelectionWindow.department_id == department_id,
            DepartmentSelectionWindow.study_semester == study_semester,
        )
    )


async def get_window_or_404(
    db: AsyncSession,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> DepartmentSelectionWindow:
    window = await get_window(db, academic_term_id, department_id, study_semester)
    if window is None:
        raise NotFoundError(
            f"Selection window not found for dept={department_id} sem={study_semester}"
        )
    return window


async def list_windows(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = None,
) -> list[DepartmentSelectionWindow]:
    q = select(DepartmentSelectionWindow).where(
        DepartmentSelectionWindow.institution_id == institution_id
    )
    if academic_term_id is not None:
        q = q.where(DepartmentSelectionWindow.academic_term_id == academic_term_id)
    if department_id is not None:
        q = q.where(DepartmentSelectionWindow.department_id == department_id)
    result = await db.execute(q.order_by(DepartmentSelectionWindow.study_semester))
    return list(result.scalars().all())


async def upsert_window(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    payload: SelectionWindowUpsert,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> DepartmentSelectionWindow:
    dept = await db.get(Department, department_id)
    if dept is None or dept.institution_id != institution_id:
        raise ValidationError("Department not in institution")

    window = await get_window(db, academic_term_id, department_id, payload.study_semester)
    data = payload.model_dump()
    study_semester = data.pop("study_semester")
    old_scenario_id = window.published_scenario_id if window is not None else None
    new_scenario_id = data.get("published_scenario_id")

    if window is None:
        window = DepartmentSelectionWindow(
            institution_id=institution_id,
            academic_term_id=academic_term_id,
            department_id=department_id,
            study_semester=study_semester,
            **data,
        )
        db.add(window)
    else:
        for field, value in data.items():
            setattr(window, field, value)

    await db.flush()

    if old_scenario_id != new_scenario_id:
        await invalidation_svc.invalidate_for_window(
            db,
            academic_term_id=academic_term_id,
            department_id=department_id,
            study_semester=study_semester,
            reason=INVALIDATION_SCENARIO_SWITCHED,
            institution_id=institution_id,
            actor_user_id=actor_user_id,
            audit_metadata={
                "old_scenario_id": str(old_scenario_id) if old_scenario_id else None,
                "new_scenario_id": str(new_scenario_id) if new_scenario_id else None,
            },
        )

    return window


async def open_registration(
    db: AsyncSession,
    window: DepartmentSelectionWindow,
) -> DepartmentSelectionWindow:
    window.status = SelectionWindowStatus.OPEN
    if window.registration_opens_at is None:
        window.registration_opens_at = _utcnow()
    await db.flush()
    logger.info("Selection window opened", window_id=str(window.id))
    return window


async def close_registration(
    db: AsyncSession,
    window: DepartmentSelectionWindow,
) -> DepartmentSelectionWindow:
    window.status = SelectionWindowStatus.CLOSED
    if window.registration_closes_at is None:
        window.registration_closes_at = _utcnow()
    await db.flush()
    logger.info("Selection window closed", window_id=str(window.id))
    return window


def assert_student_can_read(window: DepartmentSelectionWindow) -> None:
    phase = compute_effective_phase(window)
    if phase in ("DRAFT",):
        raise ValidationError("Selection is not yet available for your department")


def assert_student_can_write_draft(window: DepartmentSelectionWindow) -> None:
    phase = compute_effective_phase(window)
    if phase not in ("PREVIEW", "OPEN"):
        raise ValidationError("Selection window is not open for drafting")


def assert_student_can_confirm(window: DepartmentSelectionWindow) -> None:
    phase = compute_effective_phase(window)
    if phase != "OPEN":
        raise ValidationError("Registration is not open — cannot confirm selection")


async def transition_windows_by_schedule(db: AsyncSession) -> int:
    """Celery Beat: auto-transition windows based on timestamps. Returns count updated."""
    now = _utcnow()
    updated = 0
    result = await db.execute(select(DepartmentSelectionWindow))
    windows = list(result.scalars().all())

    for window in windows:
        old_status = window.status
        if window.status == SelectionWindowStatus.CLOSED:
            continue

        if window.preview_opens_at and now >= window.preview_opens_at:
            if window.status == SelectionWindowStatus.DRAFT:
                window.status = SelectionWindowStatus.PREVIEW

        if window.registration_opens_at and now >= window.registration_opens_at:
            if window.registration_closes_at and now > window.registration_closes_at:
                window.status = SelectionWindowStatus.CLOSED
            elif window.status in (
                SelectionWindowStatus.DRAFT,
                SelectionWindowStatus.PREVIEW,
            ):
                window.status = SelectionWindowStatus.OPEN

        if window.registration_closes_at and now > window.registration_closes_at:
            window.status = SelectionWindowStatus.CLOSED

        if window.status != old_status:
            updated += 1
            if window.status == SelectionWindowStatus.OPEN:
                await notification_svc.send_to_role(
                    db,
                    institution_id=window.institution_id,
                    role=UserRole.STUDENT,
                    notification_type=NotificationType.REGISTRATION_OPEN,
                    title="Course selection open",
                    body=f"Registration is now open for semester {window.study_semester}.",
                )
            elif window.status == SelectionWindowStatus.CLOSED and old_status == SelectionWindowStatus.OPEN:
                await notification_svc.send_to_role(
                    db,
                    institution_id=window.institution_id,
                    role=UserRole.STUDENT,
                    notification_type=NotificationType.REGISTRATION_CLOSED,
                    title="Course selection closed",
                    body=f"Registration has closed for semester {window.study_semester}.",
                )

    if updated:
        await db.flush()
    return updated
