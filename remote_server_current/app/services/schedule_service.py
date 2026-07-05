"""
app/services/schedule_service.py
==================================
Read and persist solver output sessions for a Scenario.

Responsibilities
----------------
* ``get_by_scenario`` — return all ScheduledSessions for a scenario.
* ``clear_and_persist`` — atomic replace: delete old sessions, bulk-insert new ones.
  Called by the Celery schedule task after a successful solve.

Architecture note
-----------------
ScheduledSessions are immutable solver output.  They are never updated in place.
The only write path is ``clear_and_persist`` (full replace after each solve).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, and_, cast, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.models.course import Course
from app.models.curriculum import CourseOffering, OfferingBucket, SchedulingTarget, TargetRequirement, TeachingAssignment
from app.models.faculty import Faculty
from app.models.institution import Department
from app.models.room import Room
from app.models.scenario import Scenario
from app.models.schedule import ScheduledSession
from app.models.user import User
from app.services.time_grid_service import resolve_slots_for_scenario


def _derive_section_label(
    target_name: str | None,
    target_extra_data: dict[str, Any] | None,
) -> str | None:
    if isinstance(target_extra_data, dict):
        section_label = target_extra_data.get("section_label")
        if isinstance(section_label, str) and section_label.strip():
            return section_label.strip()

    if not target_name:
        return None

    if "-" in target_name:
        suffix = target_name.rsplit("-", 1)[-1].strip()
        return suffix or None

    return None


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_by_scenario(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> list[dict]:
    """Return all scheduled sessions for *scenario_id* with enriched course/faculty/room names."""

    # 1. Main query with LEFT JOINs for course / faculty / room enrichment.
    #    ScheduledSession stores IDs as VARCHAR strings; ORM PKs are UUID —
    #    so we cast the UUID PK to String for the join condition.
    rows_result = await db.execute(
        select(
            ScheduledSession,
            OfferingBucket.id.label("bucket_id"),
            OfferingBucket.name.label("bucket_name"),
            Course.code.label("course_code"),
            Course.name.label("course_name"),
            CourseOffering.group_number.label("group_number"),
            CourseOffering.study_semester.label("study_semester"),
            Department.id.label("department_id"),
            Department.name.label("department_name"),
            Department.code.label("department_code"),
            Faculty.name.label("faculty_name"),
            User.department_id.label("faculty_department_id"),
            Room.name.label("room_name"),
            Room.code.label("room_code"),
        )
        .join(Scenario, Scenario.id == ScheduledSession.scenario_id)
        .outerjoin(Course, cast(Course.id, String) == ScheduledSession.course_id)
        .outerjoin(CourseOffering, CourseOffering.id == ScheduledSession.offering_id)
        .outerjoin(OfferingBucket, OfferingBucket.id == CourseOffering.bucket_id)
        .outerjoin(
            TeachingAssignment,
            and_(
                TeachingAssignment.academic_term_id == Scenario.academic_term_id,
                cast(TeachingAssignment.faculty_id, String) == ScheduledSession.faculty_id,
                cast(TeachingAssignment.course_id, String) == ScheduledSession.course_id,
                TeachingAssignment.is_active.is_(True),
            ),
        )
        .outerjoin(
            Department,
            Department.id == func.coalesce(
                OfferingBucket.department_id,
                TeachingAssignment.department_id,
                Course.department_id,
            ),
        )
        .outerjoin(Faculty, cast(Faculty.id, String) == ScheduledSession.faculty_id)
        .outerjoin(User, User.id == Faculty.user_id)
        .outerjoin(Room, cast(Room.id, String) == ScheduledSession.room_id)
        .where(ScheduledSession.scenario_id == scenario_id)
        .order_by(ScheduledSession.slot_code, ScheduledSession.session_id)
    )
    rows = rows_result.all()

    # 2. Build slot_code → day_of_week using the scenario's effective time grid.
    slot_day_map: dict[str, str] = {}
    scenario = await db.get(Scenario, scenario_id)
    if scenario is not None:
        slots = await resolve_slots_for_scenario(db, scenario)
        if isinstance(slots, dict):
            slot_day_map = {
                code: info.get("day", "")
                for code, info in slots.items()
                if isinstance(info, dict)
            }

    bucket_context_map: dict[str, dict[str, Any]] = {}
    bucket_ids = {
        str(row.bucket_id)
        for row in rows
        if getattr(row, "bucket_id", None) is not None
    }
    if bucket_ids:
        bucket_result = await db.execute(
            select(
                OfferingBucket.id.label("bucket_id"),
                OfferingBucket.name.label("bucket_name"),
                SchedulingTarget.name.label("target_name"),
                SchedulingTarget.extra_data.label("target_extra_data"),
            )
            .outerjoin(TargetRequirement, TargetRequirement.bucket_id == OfferingBucket.id)
            .outerjoin(SchedulingTarget, SchedulingTarget.id == TargetRequirement.target_id)
            .where(OfferingBucket.id.in_([uuid.UUID(bucket_id) for bucket_id in bucket_ids]))
        )
        for bucket_row in bucket_result.all():
            bucket_id = str(bucket_row.bucket_id)
            existing = bucket_context_map.get(bucket_id)
            section_label = _derive_section_label(
                bucket_row.target_name,
                bucket_row.target_extra_data,
            )
            if existing is None:
                bucket_context_map[bucket_id] = {
                    "bucket_name": bucket_row.bucket_name,
                    "batch_name": bucket_row.target_name,
                    "section_label": section_label,
                }
            elif existing.get("section_label") is None and section_label is not None:
                existing["batch_name"] = bucket_row.target_name
                existing["section_label"] = section_label

    # 3. Merge into enriched dicts compatible with ScheduledSessionResponse.
    enriched: list[dict] = []
    for row in rows:
        session = row.ScheduledSession
        bucket_context = (
            bucket_context_map.get(str(row.bucket_id))
            if getattr(row, "bucket_id", None) is not None
            else None
        )
        enriched.append(
            {
                "id": session.id,
                "scenario_id": session.scenario_id,
                "session_id": session.session_id,
                "course_id": session.course_id,
                "faculty_id": session.faculty_id,
                "room_id": session.room_id,
                "slot_code": session.slot_code,
                "offering_id": session.offering_id,
                "created_at": session.created_at,
                "course_code": row.course_code,
                "course_name": row.course_name,
                "department_id": str(row.department_id) if row.department_id else None,
                "department_name": row.department_name,
                "department_code": row.department_code,
                "faculty_name": row.faculty_name,
                "faculty_department_id": str(row.faculty_department_id) if row.faculty_department_id else None,
                "room_name": row.room_name,
                "room_code": row.room_code,
                "day_of_week": slot_day_map.get(session.slot_code),
                "batch_name": bucket_context["batch_name"] if bucket_context else None,
                "bucket_name": row.bucket_name,
                "group_number": row.group_number,
                "study_semester": row.study_semester,
                "section_label": bucket_context["section_label"] if bucket_context else None,
                "is_pinned": session.is_pinned,
                "original_room_id": session.original_room_id,
                "original_slot_code": session.original_slot_code,
                "original_faculty_id": session.original_faculty_id,
            }
        )
    return enriched


async def get_session_count(db: AsyncSession, scenario_id: uuid.UUID) -> int:
    """Return the number of scheduled sessions for *scenario_id*."""
    from sqlalchemy import func

    result = await db.execute(
        select(func.count(ScheduledSession.id)).where(
            ScheduledSession.scenario_id == scenario_id
        )
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Pin helpers
# ---------------------------------------------------------------------------


async def get_pinned_sessions(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> list[ScheduledSession]:
    """Return all is_pinned=True rows for a scenario."""
    result = await db.execute(
        select(ScheduledSession).where(
            ScheduledSession.scenario_id == scenario_id,
            ScheduledSession.is_pinned == True,  # noqa: E712
        )
    )
    return result.scalars().all()


async def toggle_pin(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    session_id: uuid.UUID,
    is_pinned: bool,
) -> ScheduledSession:
    """Pin or unpin a session; marks the scenario as dirty."""
    row = await db.get(ScheduledSession, session_id)
    if row is None or row.scenario_id != scenario_id:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("ScheduledSession not found")
    row.is_pinned = is_pinned
    await db.execute(
        update(Scenario).where(Scenario.id == scenario_id).values(is_dirty=True)
    )
    return row


async def clear_pins(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> int:
    """Reset all pins for a scenario. Returns count cleared."""
    result = await db.execute(
        update(ScheduledSession)
        .where(
            ScheduledSession.scenario_id == scenario_id,
            ScheduledSession.is_pinned == True,  # noqa: E712
        )
        .values(is_pinned=False)
    )
    return result.rowcount


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def clear_and_persist(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    sessions: list[dict[str, Any]],
) -> list[ScheduledSession]:
    """
    Atomically replace all scheduled sessions for *scenario_id*.

    Parameters
    ----------
    sessions:
        List of dicts with keys: ``session_id``, ``course_id``, ``faculty_id``,
        ``room_id``, ``slot_code``.  These come directly from the solver's
        ``SchedulerOutput.sessions`` list.

    Returns
    -------
    The newly persisted ScheduledSession rows.
    """
    # 1. Delete old results
    await db.execute(
        delete(ScheduledSession).where(ScheduledSession.scenario_id == scenario_id)
    )

    # 2. Bulk-insert new results
    new_rows: list[ScheduledSession] = []
    for s in sessions:
        offering_id = s.get("offering_id")
        if isinstance(offering_id, str) and offering_id:
            offering_id = uuid.UUID(offering_id)
        row = ScheduledSession(
            scenario_id=scenario_id,
            session_id=s["session_id"],
            course_id=s["course_id"],
            faculty_id=s["faculty_id"],
            room_id=s["room_id"],
            slot_code=s["slot_code"],
            offering_id=offering_id,  # nullable — populated post-solve by Celery task
        )
        db.add(row)
        new_rows.append(row)

    await db.flush()
    logger.info(
        "Schedule persisted",
        scenario_id=str(scenario_id),
        session_count=len(new_rows),
    )
    return new_rows


async def manual_edit_session(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    session_id: uuid.UUID,
    room_id: str | None = None,
    faculty_id: str | None = None,
    slot_code: str | None = None,
    force: bool = False,
) -> tuple["ScheduledSession", list[str]]:
    """
    Manually override room, faculty, and/or slot for a single scheduled session.

    On first edit each field's original value is saved to original_* for display.
    Sets is_pinned=True and marks the scenario dirty so re-solve respects the pin.

    Returns (updated_row, warnings).  If force=False and a collision is found the
    collision is returned as a warning; the edit is still applied because the caller
    already confirmed via the force=True path.  When force=False and there are
    collisions we raise HTTPException 409 so the UI can show the Force Save button.
    """
    from app.core.exceptions import NotFoundError
    from fastapi import HTTPException, status as http_status

    row = await db.get(ScheduledSession, session_id)
    if row is None or row.scenario_id != scenario_id:
        raise NotFoundError("ScheduledSession not found")

    warnings: list[str] = []

    # ── Room change ─────────────────────────────────────────────────────────
    if room_id is not None and room_id != row.room_id:
        # Collision: another session in the same scenario using the same room at the same slot
        effective_slot = slot_code if slot_code else row.slot_code
        collision_result = await db.execute(
            select(ScheduledSession.id).where(
                ScheduledSession.scenario_id == scenario_id,
                ScheduledSession.room_id == room_id,
                ScheduledSession.slot_code == effective_slot,
                ScheduledSession.id != session_id,
            )
        )
        if collision_result.scalar_one_or_none() is not None:
            msg = f"Room collision: another session occupies room {room_id} at slot {effective_slot}."
            if not force:
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail={"warnings": [msg]},
                )
            warnings.append(msg)

        if row.original_room_id is None:
            row.original_room_id = row.room_id
        row.room_id = room_id

    # ── Faculty change ───────────────────────────────────────────────────────
    if faculty_id is not None and faculty_id != row.faculty_id:
        effective_slot = slot_code if slot_code else row.slot_code
        collision_result = await db.execute(
            select(ScheduledSession.id).where(
                ScheduledSession.scenario_id == scenario_id,
                ScheduledSession.faculty_id == faculty_id,
                ScheduledSession.slot_code == effective_slot,
                ScheduledSession.id != session_id,
            )
        )
        if collision_result.scalar_one_or_none() is not None:
            msg = f"Faculty double-book: {faculty_id} is already scheduled at slot {effective_slot}."
            warnings.append(msg)

        if row.original_faculty_id is None:
            row.original_faculty_id = row.faculty_id
        row.faculty_id = faculty_id
        warnings.append(
            "Faculty override is display-only; re-solve will reset it unless "
            "the Teaching Assignment is also updated."
        )

    # ── Slot change (DnD) ───────────────────────────────────────────────────
    if slot_code is not None and slot_code != row.slot_code:
        if row.original_slot_code is None:
            row.original_slot_code = row.slot_code
        row.slot_code = slot_code

    # ── Pin + dirty ──────────────────────────────────────────────────────────
    row.is_pinned = True
    await db.execute(
        update(Scenario).where(Scenario.id == scenario_id).values(is_dirty=True)
    )

    return row, warnings


async def clear(db: AsyncSession, scenario_id: uuid.UUID) -> int:
    """
    Delete all scheduled sessions for *scenario_id*.

    Returns the number of deleted rows.
    """
    result = await db.execute(
        delete(ScheduledSession)
        .where(ScheduledSession.scenario_id == scenario_id)
        .returning(ScheduledSession.id)
    )
    deleted = len(result.fetchall())
    await db.flush()
    logger.info("Schedule cleared", scenario_id=str(scenario_id), deleted=deleted)
    return deleted
