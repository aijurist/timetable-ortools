"""Invalidate student selections when published timetables change."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.models.notification import NotificationType
from app.models.scenario import Scenario
from app.models.selection import (
    DepartmentSelectionWindow,
    GroupSelectionStatus,
    StudentGroupSelection,
)
from app.models.student import StudentProfile
from app.models.user import User

import app.services.audit_log_service as audit_log_service
import app.services.notification_service as notification_svc
import app.services.offering_seat_bundle_service as seat_bundle_svc
from app.models.audit_log import AuditAction


INVALIDATION_TIMETABLE_CHANGED = "TIMETABLE_REPUBLISHED"
INVALIDATION_SCENARIO_UNPUBLISHED = "TIMETABLE_UNPUBLISHED"
INVALIDATION_SCENARIO_SWITCHED = "TIMETABLE_SCENARIO_SWITCHED"


async def count_active_selections_for_window(
    db: AsyncSession,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
) -> int:
    """Count DRAFT + CONFIRMED selections for a window scope."""
    result = await db.execute(
        select(func.count())
        .select_from(StudentGroupSelection)
        .where(
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.department_id == department_id,
            StudentGroupSelection.study_semester == study_semester,
            StudentGroupSelection.status.in_(
                (GroupSelectionStatus.DRAFT, GroupSelectionStatus.CONFIRMED)
            ),
        )
    )
    return int(result.scalar_one())


def is_publish_snapshot_stale(
    sel: StudentGroupSelection,
    window: DepartmentSelectionWindow,
    scenario: Scenario | None,
) -> bool:
    """True when a CONFIRMED selection no longer matches the live published timetable."""
    if sel.status != GroupSelectionStatus.CONFIRMED:
        return False
    if window.published_scenario_id is None:
        return False
    if scenario is None or scenario.published_job_id is None:
        return True
    return (
        sel.published_scenario_id != window.published_scenario_id
        or sel.published_job_id != scenario.published_job_id
    )


async def drop_if_publish_snapshot_stale(
    db: AsyncSession,
    sel: StudentGroupSelection,
    window: DepartmentSelectionWindow,
    scenario: Scenario | None,
    *,
    institution_id: uuid.UUID,
) -> bool:
    """Drop a stale CONFIRMED selection on read. Returns True if dropped."""
    if not is_publish_snapshot_stale(sel, window, scenario):
        return False
    await _drop_selections(
        db,
        [sel],
        INVALIDATION_TIMETABLE_CHANGED,
        institution_id,
    )
    return True


async def invalidate_for_window(
    db: AsyncSession,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
    reason: str,
    institution_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    audit_metadata: dict[str, Any] | None = None,
) -> int:
    """Drop all active selections for one selection window scope."""
    result = await db.execute(
        select(StudentGroupSelection).where(
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.department_id == department_id,
            StudentGroupSelection.study_semester == study_semester,
            StudentGroupSelection.status.in_(
                (GroupSelectionStatus.DRAFT, GroupSelectionStatus.CONFIRMED)
            ),
        )
    )
    selections = list(result.scalars().all())
    return await _drop_selections(
        db,
        selections,
        reason,
        institution_id,
        actor_user_id=actor_user_id,
        audit_metadata=audit_metadata,
    )


async def invalidate_for_scenario(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    *,
    reason: str,
    institution_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> int:
    """Drop active selections for every window linked to *scenario_id*."""
    windows_result = await db.execute(
        select(DepartmentSelectionWindow).where(
            DepartmentSelectionWindow.published_scenario_id == scenario_id
        )
    )
    windows = list(windows_result.scalars().all())
    total = 0
    for window in windows:
        total += await invalidate_for_window(
            db,
            academic_term_id=window.academic_term_id,
            department_id=window.department_id,
            study_semester=window.study_semester,
            reason=reason,
            institution_id=window.institution_id,
            actor_user_id=actor_user_id,
            audit_metadata={"scenario_id": str(scenario_id)},
        )
    return total


async def get_selection_reset_reason(
    db: AsyncSession,
    student_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    study_year: int,
    study_semester: int,
) -> Optional[str]:
    """Return user-facing reset message if the latest selection was auto-dropped."""
    result = await db.execute(
        select(StudentGroupSelection)
        .where(
            StudentGroupSelection.student_id == student_id,
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.study_year == study_year,
            StudentGroupSelection.study_semester == study_semester,
            StudentGroupSelection.status == GroupSelectionStatus.DROPPED,
            StudentGroupSelection.invalidation_reason.isnot(None),
        )
        .order_by(StudentGroupSelection.updated_at.desc())
        .limit(1)
    )
    sel = result.scalars().first()
    if sel is None:
        return None
    return _reason_to_message(sel.invalidation_reason)


def _reason_to_message(reason: str | None) -> str:
    if reason == INVALIDATION_SCENARIO_UNPUBLISHED:
        return (
            "Your previous selection was reset because the timetable was unpublished. "
            "Please select again when a new timetable is published."
        )
    return (
        "Your previous selection was reset because the timetable was updated. "
        "Please review and confirm your choices again."
    )


async def _notify_affected_students(
    db: AsyncSession,
    selections: list[StudentGroupSelection],
    *,
    institution_id: uuid.UUID,
    reason: str,
) -> None:
    if not selections:
        return
    student_ids = [s.student_id for s in selections]
    users_result = await db.execute(
        select(User)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .where(StudentProfile.id.in_(student_ids))
    )
    recipients = list(users_result.scalars().unique().all())
    if not recipients:
        return
    await notification_svc.send(
        db,
        institution_id=institution_id,
        notification_type=NotificationType.REGISTRATION_OPEN,
        recipients=recipients,
        title="Course selection reset",
        body=_reason_to_message(reason),
    )


async def _drop_selections(
    db: AsyncSession,
    selections: list[StudentGroupSelection],
    reason: str,
    institution_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    audit_metadata: dict[str, Any] | None = None,
) -> int:
    if not selections:
        return 0

    for sel in selections:
        if sel.status == GroupSelectionStatus.CONFIRMED:
            await seat_bundle_svc.release_selection_bundle(db, sel)
        sel.status = GroupSelectionStatus.DROPPED
        sel.invalidation_reason = reason
        sel.confirmed_at = None
        sel.selection_payload = {}

    await db.flush()

    await _notify_affected_students(
        db, selections, institution_id=institution_id, reason=reason
    )

    after: dict[str, Any] = {
        "invalidated_count": len(selections),
        "reason": reason,
    }
    if audit_metadata:
        after.update(audit_metadata)

    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="StudentGroupSelection",
        institution_id=institution_id,
        after=after,
    )

    logger.info(
        "Selections invalidated",
        count=len(selections),
        reason=reason,
    )
    return len(selections)
