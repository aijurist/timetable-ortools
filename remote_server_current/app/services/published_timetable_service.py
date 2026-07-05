"""Read-only published timetable views for HOD and teacher roles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.curriculum import CourseOffering, OfferingBucket
from app.models.faculty import Faculty
from app.models.institution import AcademicTerm, Department
from app.models.scenario import Scenario
from app.schemas.schedule import (
    DepartmentTimetableMeta,
    DepartmentTimetableResponse,
    ScheduledSessionResponse,
    TeacherTimetableMeta,
    TeacherTimetableResponse,
)

import app.services.institution_service as institution_svc
import app.services.schedule_service as schedule_svc
import app.services.selection_window_service as window_svc
import app.services.solver_job_service as solver_job_svc
from app.services.time_grid_service import resolve_slots_for_scenario


@dataclass(frozen=True)
class ResolvedPublishedScenario:
    scenario_id: uuid.UUID
    published_job_id: uuid.UUID
    published_at: datetime | None


async def resolve_published_scenario(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID | None = None,
    study_semester: int | None = None,
) -> ResolvedPublishedScenario | None:
    """Resolve the published scenario for a dept/semester (HYBRID window or TRADITIONAL fallback)."""
    if department_id is not None and study_semester is not None:
        window = await window_svc.get_window(
            db, academic_term_id, department_id, study_semester
        )
        if window is not None:
            if window.published_scenario_id is not None:
                scenario = await db.get(Scenario, window.published_scenario_id)
                if scenario is not None and scenario.published_job_id is not None:
                    assert_same_institution_guard(institution_id, scenario.institution_id)
                    return ResolvedPublishedScenario(
                        scenario_id=scenario.id,
                        published_job_id=scenario.published_job_id,
                        published_at=scenario.published_at,
                    )
                # Window linked to a scenario that is not published yet.
                return None
            # Window configured without a linked scenario — fall through to TRADITIONAL.

    if department_id is not None:
        scenario = await _resolve_traditional_fallback(
            db,
            institution_id=institution_id,
            academic_term_id=academic_term_id,
            department_id=department_id,
            study_semester=study_semester,
        )
        if scenario is not None:
            return ResolvedPublishedScenario(
                scenario_id=scenario.id,
                published_job_id=scenario.published_job_id,  # type: ignore[arg-type]
                published_at=scenario.published_at,
            )

    return None


async def _resolve_traditional_fallback(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int | None,
) -> Scenario | None:
    stmt = (
        select(Scenario)
        .join(OfferingBucket, OfferingBucket.scenario_id == Scenario.id)
        .where(
            Scenario.institution_id == institution_id,
            Scenario.academic_term_id == academic_term_id,
            Scenario.published_job_id.isnot(None),
            OfferingBucket.department_id == department_id,
        )
    )
    if study_semester is not None:
        stmt = stmt.join(
            CourseOffering, CourseOffering.bucket_id == OfferingBucket.id
        ).where(CourseOffering.study_semester == study_semester)

    stmt = stmt.order_by(Scenario.published_at.desc().nullslast()).limit(1)
    return await db.scalar(stmt)


def assert_same_institution_guard(
    caller_institution_id: uuid.UUID,
    resource_institution_id: uuid.UUID,
) -> None:
    if caller_institution_id != resource_institution_id:
        raise NotFoundError("Published timetable not found")


async def get_faculty_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> Faculty | None:
    return await db.scalar(select(Faculty).where(Faculty.user_id == user_id))


def _filter_sessions(
    rows: list[dict[str, Any]],
    *,
    department_id: uuid.UUID | None = None,
    study_semester: int | None = None,
    faculty_id: uuid.UUID | None = None,
    day_of_week: str | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    dept_str = str(department_id) if department_id else None
    faculty_str = str(faculty_id) if faculty_id else None
    day_norm = day_of_week.strip().upper() if day_of_week else None

    for row in rows:
        if dept_str is not None:
            row_dept = row.get("department_id")
            fac_dept = row.get("faculty_department_id")
            if (row_dept is None or str(row_dept) != dept_str) and \
               (fac_dept is None or str(fac_dept) != dept_str):
                continue
        if study_semester is not None:
            row_sem = row.get("study_semester")
            if row_sem is not None and int(row_sem) != study_semester:
                continue
        if faculty_str is not None:
            row_fac = row.get("faculty_id")
            if row_fac is None or str(row_fac) != faculty_str:
                continue
        if day_norm is not None:
            row_day = (row.get("day_of_week") or "").strip().upper()
            if row_day != day_norm:
                continue
        filtered.append(row)
    return filtered


async def _resolve_term(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID | None,
) -> AcademicTerm:
    if academic_term_id is not None:
        term = await institution_svc.get_term_by_id(db, academic_term_id)
        if term is None:
            raise NotFoundError(f"AcademicTerm {academic_term_id} not found")
        if term.institution_id != institution_id:
            raise NotFoundError(f"AcademicTerm {academic_term_id} not found")
        return term

    term = await institution_svc.resolve_active_academic_term(db, institution_id)
    if term is None:
        raise NotFoundError("No active academic term found")
    return term


async def _load_published_rows(
    db: AsyncSession,
    *,
    scenario_id: uuid.UUID,
    published_job_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Load published schedule rows, falling back to live sessions when job snapshot is empty."""
    rows = await solver_job_svc.get_result_rows(db, published_job_id)
    if rows:
        return rows
    return await schedule_svc.get_by_scenario(db, scenario_id)


async def get_department_timetable(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int | None = None,
    academic_term_id: uuid.UUID | None = None,
    faculty_id: uuid.UUID | None = None,
    day_of_week: str | None = None,
) -> DepartmentTimetableResponse:
    term = await _resolve_term(db, institution_id, academic_term_id)
    dept = await db.get(Department, department_id)
    if dept is None or dept.institution_id != institution_id:
        raise NotFoundError(f"Department {department_id} not found")

    resolved = await resolve_published_scenario(
        db,
        institution_id=institution_id,
        academic_term_id=term.id,
        department_id=department_id,
        study_semester=study_semester,
    )
    if resolved is None:
        return DepartmentTimetableResponse(
            meta=DepartmentTimetableMeta(
                academic_term_id=term.id,
                academic_term_name=term.name,
                department_id=department_id,
                department_name=dept.name,
                study_semester=study_semester,
                published_at=None,
                session_count=0,
            ),
            sessions=[],
            slot_definitions=None,
        )

    scenario = await db.get(Scenario, resolved.scenario_id)
    if scenario is None:
        raise NotFoundError("Published scenario not found")

    rows = await _load_published_rows(
        db,
        scenario_id=resolved.scenario_id,
        published_job_id=resolved.published_job_id,
    )

    other_scenarios_result = await db.execute(
        select(Scenario).where(
            Scenario.institution_id == institution_id,
            Scenario.academic_term_id == term.id,
            Scenario.published_job_id.isnot(None),
            Scenario.id != resolved.scenario_id
        )
    )
    for other_scenario in other_scenarios_result.scalars().all():
        other_rows = await _load_published_rows(
            db,
            scenario_id=other_scenario.id,
            published_job_id=other_scenario.published_job_id,  # type: ignore[arg-type]
        )
        for row in other_rows:
            if str(row.get("faculty_department_id")) == str(department_id):
                rows.append(row)
    filtered = _filter_sessions(
        rows,
        department_id=department_id,
        study_semester=study_semester,
        faculty_id=faculty_id,
        day_of_week=day_of_week,
    )
    sessions = [ScheduledSessionResponse.model_validate(row) for row in filtered]
    slot_definitions = await resolve_slots_for_scenario(db, scenario)

    return DepartmentTimetableResponse(
        meta=DepartmentTimetableMeta(
            academic_term_id=term.id,
            academic_term_name=term.name,
            department_id=department_id,
            department_name=dept.name,
            study_semester=study_semester,
            published_at=resolved.published_at,
            session_count=len(sessions),
        ),
        sessions=sessions,
        slot_definitions=slot_definitions if isinstance(slot_definitions, dict) else None,
    )


async def get_teacher_timetable(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    academic_term_id: uuid.UUID | None = None,
) -> TeacherTimetableResponse:
    faculty = await get_faculty_for_user(db, user_id)
    if faculty is None:
        raise NotFoundError("No faculty profile linked to this account")

    term = await _resolve_term(db, institution_id, academic_term_id)

    scenarios_result = await db.execute(
        select(Scenario).where(
            Scenario.institution_id == institution_id,
            Scenario.academic_term_id == term.id,
            Scenario.published_job_id.isnot(None),
        )
    )
    scenarios = list(scenarios_result.scalars().all())

    faculty_str = str(faculty.id)
    merged_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    slot_definitions: dict[str, Any] | None = None

    for scenario in scenarios:
        rows = await _load_published_rows(
            db,
            scenario_id=scenario.id,
            published_job_id=scenario.published_job_id,  # type: ignore[arg-type]
        )
        scenario_has_matches = False
        for row in rows:
            if str(row.get("faculty_id") or "") != faculty_str:
                continue
            scenario_has_matches = True
            key = (
                str(row.get("session_id") or ""),
                str(row.get("slot_code") or ""),
                str(row.get("offering_id") or ""),
            )
            merged_rows[key] = row
        if slot_definitions is None and scenario_has_matches:
            slots = await resolve_slots_for_scenario(db, scenario)
            if isinstance(slots, dict):
                slot_definitions = slots

    sessions = [
        ScheduledSessionResponse.model_validate(row)
        for row in sorted(
            merged_rows.values(),
            key=lambda r: (r.get("slot_code", ""), r.get("session_id", "")),
        )
    ]

    return TeacherTimetableResponse(
        meta=TeacherTimetableMeta(
            academic_term_id=term.id,
            academic_term_name=term.name,
            faculty_id=faculty.id,
            faculty_name=faculty.name,
            session_count=len(sessions),
        ),
        sessions=sessions,
        slot_definitions=slot_definitions,
    )
