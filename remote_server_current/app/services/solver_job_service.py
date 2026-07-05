"""
app/services/solver_job_service.py
====================================
Read/write operations for SolverJob and JobConflict (solver audit trail).

Who uses this service
---------------------
* Celery solve task  → ``create_job``, ``mark_complete``, ``create_conflict``
* Agent analyze_conflict tool → ``list_conflicts``
* Route handlers (GET)       → ``list_jobs``, ``get_job_or_404``, ``get_latest_job``

Architecture notes
------------------
- SolverJob rows are IMMUTABLE after ``mark_complete`` — never updated again.
- JobConflict rows are written by the solver analysis pass on INFEASIBLE result.
- The Agent reads conflicts via ``list_conflicts`` to decide which Tier 2
  params to relax before re-triggering a solve.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logger import logger
from app.models.course import Course
from app.models.curriculum import CourseOffering, OfferingBucket
from app.models.faculty import Faculty
from app.models.institution import Department
from app.models.room import Room
from app.models.scenario import Scenario
from app.models.solver_job import ConflictSeverity, JobConflict, SolverJob, SolverJobStatus
from app.models.user import User
from app.schemas.solver_job import SolverJobResponse
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


from app.models.curriculum import CourseOffering, OfferingBucket, SchedulingTarget, TargetRequirement


# ---------------------------------------------------------------------------
# SolverJob queries
# ---------------------------------------------------------------------------


async def list_jobs(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 20,
) -> list[SolverJob]:
    """Return solver jobs for *scenario_id*, newest first."""
    result = await db.execute(
        select(SolverJob)
        .where(SolverJob.scenario_id == scenario_id)
        .order_by(SolverJob.started_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_jobs(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> int:
    """Return the total number of solver jobs for *scenario_id*."""
    result = await db.execute(
        select(func.count())
        .select_from(SolverJob)
        .where(SolverJob.scenario_id == scenario_id)
    )
    return int(result.scalar_one() or 0)


async def get_job_or_404(db: AsyncSession, job_id: uuid.UUID) -> SolverJob:
    result = await db.execute(select(SolverJob).where(SolverJob.id == job_id))
    job = result.scalars().first()
    if job is None:
        raise NotFoundError(f"SolverJob {job_id} not found")
    return job


async def get_latest_job(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> Optional[SolverJob]:
    """
    Return the most recent SolverJob for *scenario_id*, or None.

    Useful for the Agent to check the last solve status before triggering
    a new one.
    """
    result = await db.execute(
        select(SolverJob)
        .where(SolverJob.scenario_id == scenario_id)
        .order_by(SolverJob.started_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_job_for_scenario_or_404(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    job_id: uuid.UUID,
) -> SolverJob:
    result = await db.execute(
        select(SolverJob).where(
            SolverJob.id == job_id,
            SolverJob.scenario_id == scenario_id,
        )
    )
    job = result.scalars().first()
    if job is None:
        raise NotFoundError(
            f"SolverJob {job_id} not found for scenario {scenario_id}"
        )
    return job


async def get_scenario_job_state(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> dict[str, uuid.UUID | None]:
    result = await db.execute(
        select(Scenario.current_job_id, Scenario.published_job_id).where(
            Scenario.id == scenario_id
        )
    )
    row = result.first()
    if row is None:
        return {"current_job_id": None, "published_job_id": None}
    return {
        "current_job_id": row.current_job_id,
        "published_job_id": row.published_job_id,
    }


async def serialize_job_response(
    db: AsyncSession,
    job: SolverJob,
    *,
    latest_job_id: uuid.UUID | None = None,
) -> SolverJobResponse:
    if latest_job_id is None:
        latest_job = await get_latest_job(db, job.scenario_id)
        latest_job_id = latest_job.id if latest_job else None

    scenario_state = await get_scenario_job_state(db, job.scenario_id)
    payload = SolverJobResponse.model_validate(job).model_dump()
    payload.update(
        {
            "is_latest": latest_job_id == job.id,
            "is_current": scenario_state["current_job_id"] == job.id,
            "is_published": scenario_state["published_job_id"] == job.id,
            "has_result_schedule": bool(job.result_schedule),
        }
    )
    return SolverJobResponse.model_validate(payload)


async def serialize_job_responses(
    db: AsyncSession,
    jobs: list[SolverJob],
) -> list[SolverJobResponse]:
    latest_job_id = jobs[0].id if jobs else None
    scenario_state = await get_scenario_job_state(db, jobs[0].scenario_id) if jobs else {
        "current_job_id": None,
        "published_job_id": None,
    }
    responses: list[SolverJobResponse] = []
    for job in jobs:
        payload = SolverJobResponse.model_validate(job).model_dump()
        payload.update(
            {
                "is_latest": latest_job_id == job.id,
                "is_current": scenario_state["current_job_id"] == job.id,
                "is_published": scenario_state["published_job_id"] == job.id,
                "has_result_schedule": bool(job.result_schedule),
            }
        )
        responses.append(SolverJobResponse.model_validate(payload))
    return responses


async def get_result_rows(
    db: AsyncSession,
    job_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """
    Return a hydrated schedule for a historical solver job.

    Converts ``SolverJob.result_schedule`` into the same enriched row shape used
    by the live schedule endpoint so the frontend can render historical runs with
    the existing grid and table components.
    """
    job = await get_job_or_404(db, job_id)
    if not job.result_schedule:
        return []

    if any(
        item.get("session_id") and (
            item.get("course_code") is not None
            or item.get("course_name") is not None
            or item.get("faculty_name") is not None
            or item.get("room_name") is not None
            or item.get("department_name") is not None
        )
        for item in job.result_schedule
        if isinstance(item, dict)
    ):
        rows = [dict(item) for item in job.result_schedule if isinstance(item, dict)]
        rows.sort(key=lambda row: (row.get("slot_code", ""), row.get("session_id", "")))
        return rows

    scenario_result = await db.execute(
        select(Scenario).where(Scenario.id == job.scenario_id)
    )
    scenario = scenario_result.scalar_one_or_none()

    slot_day_map: dict[str, str] = {}
    if scenario is not None:
        slots = await resolve_slots_for_scenario(db, scenario)
        if isinstance(slots, dict):
            slot_day_map = {
                code: info.get("day", "")
                for code, info in slots.items()
                if isinstance(info, dict)
            }

    offering_ids = [
        uuid.UUID(str(item["offering_id"]))
        for item in job.result_schedule
        if item.get("offering_id")
    ]
    course_ids = [
        uuid.UUID(str(item["course_id"]))
        for item in job.result_schedule
        if item.get("course_id")
    ]
    faculty_ids = [
        uuid.UUID(str(item["faculty_id"]))
        for item in job.result_schedule
        if item.get("faculty_id")
    ]
    room_ids = [
        uuid.UUID(str(item["room_id"]))
        for item in job.result_schedule
        if item.get("room_id")
    ]

    offering_map: dict[uuid.UUID, dict[str, Any]] = {}
    if offering_ids:
        offerings_result = await db.execute(
            select(
                CourseOffering.id.label("offering_id"),
                CourseOffering.bucket_id.label("bucket_id"),
                CourseOffering.course_id.label("course_id"),
                CourseOffering.faculty_id.label("faculty_id"),
                CourseOffering.study_semester.label("study_semester"),
                CourseOffering.group_number.label("group_number"),
                OfferingBucket.name.label("bucket_name"),
                Course.code.label("course_code"),
                Course.name.label("course_name"),
                Department.id.label("department_id"),
                Department.name.label("department_name"),
                Department.code.label("department_code"),
                Faculty.name.label("faculty_name"),
                User.department_id.label("faculty_department_id"),
            )
            .outerjoin(Course, Course.id == CourseOffering.course_id)
            .outerjoin(OfferingBucket, OfferingBucket.id == CourseOffering.bucket_id)
            .outerjoin(
                Department,
                Department.id == func.coalesce(OfferingBucket.department_id, Course.department_id),
            )
            .outerjoin(Faculty, Faculty.id == CourseOffering.faculty_id)
            .outerjoin(User, User.id == Faculty.user_id)
            .where(CourseOffering.id.in_(offering_ids))
        )
        for row in offerings_result.all():
            offering_map[row.offering_id] = {
                "bucket_id": str(row.bucket_id),
                "course_id": str(row.course_id),
                "faculty_id": str(row.faculty_id) if row.faculty_id else None,
                "study_semester": row.study_semester,
                "group_number": row.group_number,
                "bucket_name": row.bucket_name,
                "course_code": row.course_code,
                "course_name": row.course_name,
                "department_id": str(row.department_id) if row.department_id else None,
                "department_name": row.department_name,
                "department_code": row.department_code,
                "faculty_name": row.faculty_name,
                "faculty_department_id": str(row.faculty_department_id) if row.faculty_department_id else None,
            }

    bucket_context_map: dict[str, dict[str, Any]] = {}
    bucket_ids = {
        offering["bucket_id"]
        for offering in offering_map.values()
        if offering.get("bucket_id")
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

    course_map: dict[uuid.UUID, dict[str, Any]] = {}
    if course_ids:
        courses_result = await db.execute(
            select(
                Course.id,
                Course.code,
                Course.name,
                Department.id.label("department_id"),
                Department.name.label("department_name"),
                Department.code.label("department_code"),
            )
            .outerjoin(Department, Department.id == Course.department_id)
            .where(Course.id.in_(course_ids))
        )
        for row in courses_result.all():
            course_map[row.id] = {
                "course_code": row.code,
                "course_name": row.name,
                "department_id": str(row.department_id) if row.department_id else None,
                "department_name": row.department_name,
                "department_code": row.department_code,
            }

    faculty_map: dict[uuid.UUID, dict[str, Any]] = {}
    if faculty_ids:
        faculty_result = await db.execute(
            select(Faculty.id, Faculty.name, User.department_id.label("department_id"))
            .outerjoin(User, User.id == Faculty.user_id)
            .where(Faculty.id.in_(faculty_ids))
        )
        for row in faculty_result.all():
            faculty_map[row.id] = {
                "faculty_name": row.name,
                "faculty_department_id": str(row.department_id) if row.department_id else None
            }

    room_map: dict[uuid.UUID, dict[str, Any]] = {}
    if room_ids:
        rooms_result = await db.execute(
            select(Room.id, Room.name, Room.code).where(Room.id.in_(room_ids))
        )
        for row in rooms_result.all():
            room_map[row.id] = {
                "room_name": row.name,
                "room_code": row.code,
            }

    rows: list[dict[str, Any]] = []
    for item in job.result_schedule:
        offering_id_raw = item.get("offering_id")
        course_id_raw = item.get("course_id")
        faculty_id_raw = item.get("faculty_id")
        room_id_raw = item.get("room_id")
        offering_id = uuid.UUID(str(offering_id_raw)) if offering_id_raw else None
        course_id = uuid.UUID(str(course_id_raw)) if course_id_raw else None
        faculty_id = uuid.UUID(str(faculty_id_raw)) if faculty_id_raw else None
        room_id = uuid.UUID(str(room_id_raw)) if room_id_raw else None
        offering = offering_map.get(offering_id) if offering_id else None
        bucket_context = (
            bucket_context_map.get(offering["bucket_id"])
            if offering and offering.get("bucket_id")
            else None
        )
        resolved_course_id = course_id or (uuid.UUID(offering["course_id"]) if offering and offering.get("course_id") else None)
        resolved_faculty_id = faculty_id or (uuid.UUID(offering["faculty_id"]) if offering and offering.get("faculty_id") else None)
        course = course_map.get(resolved_course_id) if resolved_course_id else None
        faculty = faculty_map.get(resolved_faculty_id) if resolved_faculty_id else None
        room = room_map.get(room_id) if room_id else None

        department_id = (
            course["department_id"] if course and course.get("department_id") else
            offering["department_id"] if offering and offering.get("department_id") else None
        )
        department_name = (
            course["department_name"] if course and course.get("department_name") else
            offering["department_name"] if offering and offering.get("department_name") else None
        )
        department_code = (
            course["department_code"] if course and course.get("department_code") else
            offering["department_code"] if offering and offering.get("department_code") else None
        )

        rows.append(
            {
                "id": uuid.uuid4(),
                "scenario_id": job.scenario_id,
                "session_id": item.get("session_key", ""),
                "course_id": str(resolved_course_id) if resolved_course_id else "",
                "faculty_id": str(resolved_faculty_id) if resolved_faculty_id else "",
                "room_id": str(room_id_raw) if room_id_raw else "",
                "slot_code": item.get("slot_code", ""),
                "offering_id": offering_id,
                "created_at": job.completed_at or job.started_at,
                "course_code": (
                    course["course_code"] if course and course.get("course_code")
                    else offering["course_code"] if offering and offering.get("course_code")
                    else None
                ),
                "course_name": (
                    course["course_name"] if course and course.get("course_name")
                    else offering["course_name"] if offering and offering.get("course_name")
                    else None
                ),
                "department_id": department_id,
                "department_name": department_name,
                "department_code": department_code,
                "faculty_name": (
                    faculty["faculty_name"] if faculty and faculty.get("faculty_name")
                    else offering["faculty_name"] if offering and offering.get("faculty_name")
                    else None
                ),
                "faculty_department_id": (
                    faculty["faculty_department_id"] if faculty and faculty.get("faculty_department_id")
                    else offering["faculty_department_id"] if offering and offering.get("faculty_department_id")
                    else None
                ),
                "room_name": room["room_name"] if room else None,
                "room_code": room["room_code"] if room else None,
                "day_of_week": slot_day_map.get(item.get("slot_code", "")),
                "batch_name": bucket_context["batch_name"] if bucket_context else None,
                "bucket_name": (
                    bucket_context["bucket_name"]
                    if bucket_context
                    else offering["bucket_name"] if offering else None
                ),
                "group_number": offering["group_number"] if offering else None,
                "study_semester": offering["study_semester"] if offering else None,
                "section_label": bucket_context["section_label"] if bucket_context else None,
                "is_pinned": item.get("is_pinned", False),
            }
        )

    rows.sort(key=lambda row: (row["slot_code"], row["session_id"]))
    return rows


# ---------------------------------------------------------------------------
# SolverJob mutations (called by Celery solve task only)
# ---------------------------------------------------------------------------

CANCELLED_BY_USER_ERROR = "Cancelled by user"


def is_job_cancelled(job: SolverJob) -> bool:
    """True when the admin cancel endpoint marked this job as user-cancelled."""
    if job.status != SolverJobStatus.FAILED:
        return False
    summary = job.score_summary or {}
    return summary.get("error") == CANCELLED_BY_USER_ERROR


async def create_job(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    constraints_snapshot: dict[str, Any],
    config_snapshot: dict[str, Any],
) -> SolverJob:
    """
    Create a PENDING SolverJob at the start of a Celery solve task.

    Parameters
    ----------
    constraints_snapshot:
        Full serialised list of ScenarioRule dicts fed to the solver.
    config_snapshot:
        Merged SolverConfig dict (system defaults → institution → scenario).

    Returns the job row so the Celery task can track its ID.
    """
    job = SolverJob(
        scenario_id=scenario_id,
        constraints_snapshot=constraints_snapshot,
        config_snapshot=config_snapshot,
        status=SolverJobStatus.PENDING,
    )
    db.add(job)
    await db.flush()
    logger.info("SolverJob created", job_id=str(job.id), scenario_id=str(scenario_id))
    return job


async def mark_running(db: AsyncSession, job_id: uuid.UUID) -> SolverJob:
    """Transition a PENDING job to RUNNING."""
    job = await mark_running_if_pending(db, job_id)
    if job is None:
        job = await get_job_or_404(db, job_id)
    return job


async def mark_running_if_pending(db: AsyncSession, job_id: uuid.UUID) -> SolverJob | None:
    """Atomically PENDING → RUNNING. Returns None if already cancelled or started."""
    result = await db.execute(
        update(SolverJob)
        .where(
            SolverJob.id == job_id,
            SolverJob.status == SolverJobStatus.PENDING,
        )
        .values(status=SolverJobStatus.RUNNING)
        .returning(SolverJob.id)
    )
    if result.first() is None:
        return None
    return await get_job_or_404(db, job_id)


async def mark_complete(
    db: AsyncSession,
    job_id: uuid.UUID,
    status: SolverJobStatus,
    result_schedule: Optional[dict[str, Any]] = None,
    score_summary: Optional[dict[str, Any]] = None,
) -> SolverJob:
    """
    Write final status + results to a SolverJob row.

    Called exactly once per job by the Celery task on completion.
    After this call the row is immutable — never call this twice.

    Parameters
    ----------
    status:
        OPTIMAL | FEASIBLE | INFEASIBLE | FAILED
    result_schedule:
        Serialised ScheduledSession list; None if INFEASIBLE / FAILED.
    score_summary:
        Dict with objective, gap_pct, wall_seconds, sessions count.
    """
    job = await get_job_or_404(db, job_id)
    job.status = status
    job.result_schedule = result_schedule
    job.score_summary = score_summary
    job.completed_at = datetime.now(tz=timezone.utc)
    await db.flush()
    logger.info(
        "SolverJob completed",
        job_id=str(job_id),
        status=status.value,
        sessions=score_summary.get("sessions") if score_summary else None,
    )
    return job


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def conflict_info_to_dict(ci: "Any") -> dict[str, Any]:
    """Convert a ``solver_engine.contracts.ConflictInfo`` dataclass to a dict
    compatible with ``bulk_create_conflicts``.

    Using a late import avoids any risk of circular imports between the app
    layer and the pure-computation solver_engine package.

    Parameters
    ----------
    ci:
        A ``ConflictInfo`` instance produced by the conflict analysis pass.
    """
    from solver_engine.contracts import ConflictInfo  # noqa: PLC0415 (local import by design)

    if not isinstance(ci, ConflictInfo):
        raise TypeError(f"Expected ConflictInfo, got {type(ci).__name__}")

    return {
        "constraint_code": ci.constraint_id,
        "severity": ci.severity,
        "description": ci.description,
        "entities": list(ci.entities) if ci.entities else [],
        "conflict_code": ci.conflict_code or None,
        "source": ci.source or None,
        "confidence": ci.confidence if ci.confidence != 1.0 else None,
        "evidence": list(ci.evidence) if ci.evidence else None,
        "recommended_actions": list(ci.recommended_actions) if ci.recommended_actions else None,
    }


# JobConflict mutations (written by solver analysis pass on INFEASIBLE)
# ---------------------------------------------------------------------------


async def list_conflicts(
    db: AsyncSession,
    job_id: uuid.UUID,
    *,
    severity: Optional[ConflictSeverity] = None,
    skip: int = 0,
    limit: int = 20,
) -> list[JobConflict]:
    """
    Return all JobConflicts for *job_id*.

    The Agent's ``analyze_conflict`` tool calls this to understand why a
    solve was INFEASIBLE and which constraints to relax.
    """
    q = select(JobConflict).where(JobConflict.job_id == job_id)
    if severity is not None:
        q = q.where(JobConflict.severity == severity)
    q = q.order_by(JobConflict.id).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def create_conflict(
    db: AsyncSession,
    job_id: uuid.UUID,
    constraint_code: Optional[str],
    severity: ConflictSeverity,
    description: Optional[str] = None,
    entities: Optional[list[dict[str, Any]]] = None,
    *,
    conflict_code: Optional[str] = None,
    source: Optional[str] = None,
    confidence: Optional[float] = None,
    evidence: Optional[list] = None,
    recommended_actions: Optional[list] = None,
) -> JobConflict:
    """
    Persist one infeasibility record for *job_id*.

    Parameters
    ----------
    constraint_code:
        Tier 2 code (e.g. "MAX_DAILY_HOURS") or None for generic conflicts.
    entities:
        List of offending resource refs, e.g.
        [{"type": "faculty", "id": "uuid"}, {"type": "room", "id": "uuid"}]
    conflict_code:
        Machine-readable diagnosis code (e.g. "UNSAT_CORE", "DOMAIN_COLLAPSE").
    source:
        Pipeline stage that produced this conflict
        ("UNSAT_CORE" | "PREFLIGHT" | "HEURISTIC" | "fallback").
    confidence:
        0.0–1.0 certainty score assigned by the analysis pass.
    evidence:
        Supporting data points (pruned slot codes, domain sizes, etc.).
    recommended_actions:
        Suggested relaxation steps for the Agent's self-correction loop.
    """
    conflict = JobConflict(
        job_id=job_id,
        constraint_code=constraint_code,
        severity=severity,
        description=description,
        entities=entities or [],
        conflict_code=conflict_code,
        source=source,
        confidence=confidence,
        evidence=evidence,
        recommended_actions=recommended_actions,
    )
    db.add(conflict)
    await db.flush()
    logger.info(
        "JobConflict recorded",
        job_id=str(job_id),
        code=constraint_code,
        severity=severity.value,
    )
    return conflict


async def bulk_create_conflicts(
    db: AsyncSession,
    job_id: uuid.UUID,
    conflicts: list[dict[str, Any]],
) -> list[JobConflict]:
    """
    Bulk-insert conflict records for a failed solve run.

    Each dict in *conflicts* must have keys:
        constraint_code (str|None), severity (str), description (str|None),
        entities (list|None).

    Called by the Celery task's conflict analysis pass.
    """
    rows: list[JobConflict] = []
    for c in conflicts:
        row = JobConflict(
            job_id=job_id,
            constraint_code=c.get("constraint_code"),
            severity=ConflictSeverity(c["severity"]),
            description=c.get("description"),
            entities=c.get("entities") or [],
            conflict_code=c.get("conflict_code"),
            source=c.get("source"),
            confidence=c.get("confidence"),
            evidence=c.get("evidence"),
            recommended_actions=c.get("recommended_actions"),
        )
        db.add(row)
        rows.append(row)

    await db.flush()
    logger.info(
        "JobConflicts bulk recorded",
        job_id=str(job_id),
        count=len(rows),
    )
    return rows
