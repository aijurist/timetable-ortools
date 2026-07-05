"""
app/services/feasibility_checker.py
=====================================
Pre-solve feasibility checker.

Pure analysis — reads DB state and returns a FeasibilityReport with
FeasibilityIssue items. No DB writes.

Run via GET /scenarios/{id}/feasibility or automatically before solve.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("feasibility_checker")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FeasibilityIssue:
    severity: Literal["ERROR", "WARNING"]
    code: str
    message: str
    entity: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class FeasibilityReport:
    feasible: bool
    issues: list[FeasibilityIssue]
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main checker
# ---------------------------------------------------------------------------


async def run_feasibility_check(
    db: AsyncSession,
    scenario: Any,
) -> FeasibilityReport:
    """
    Run all feasibility checks for a scenario.
    Returns FeasibilityReport. feasible=False if any ERROR-severity issue found.
    """
    issues: list[FeasibilityIssue] = []

    try:
        # Load scenario context
        ctx = await _load_context(db, scenario)

        # Category E — completeness checks first (fail-fast)
        issues.extend(_check_completeness(ctx))
        if any(i.severity == "ERROR" and i.code in ("NO_TIME_GRID", "NO_SCHEDULING_TARGETS") for i in issues):
            # Can't do other checks without time grid and targets
            return _build_report(issues, ctx)

        # Category A — scheduling target / group slot checks
        issues.extend(_check_group_slots(ctx))

        # Category B — faculty load checks
        issues.extend(_check_faculty_load(ctx))

        # Category C — room adequacy checks
        issues.extend(_check_room_adequacy(ctx))

        # Category D — constraint-aware checks
        issues.extend(_check_constraints(ctx))

    except Exception as exc:
        logger.exception("Feasibility check failed with exception: %s", exc)
        issues.append(FeasibilityIssue(
            severity="WARNING",
            code="CHECKER_ERROR",
            message=f"Feasibility checker encountered an error: {exc}",
            entity=None,
        ))

    return _build_report(issues, {})


def _build_report(issues: list[FeasibilityIssue], ctx: dict) -> FeasibilityReport:
    has_errors = any(i.severity == "ERROR" for i in issues)
    summary = ctx.get("summary", {})
    return FeasibilityReport(
        feasible=not has_errors,
        issues=issues,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Context loader
# ---------------------------------------------------------------------------


async def _load_context(db: AsyncSession, scenario: Any) -> dict:
    """
    Load all data needed for feasibility checks in one pass.
    Returns a context dict.
    """
    from app.models.curriculum import (
        CourseOffering, OfferingBucket, SchedulingTarget, TargetRequirement,
    )
    from app.models.time_grid import TimeGrid
    from app.models.room import Room
    from app.models.faculty import Faculty
    from app.models.course import Course
    from app.models.constraint import ScenarioRule

    institution_id = scenario.institution_id
    academic_term_id = scenario.academic_term_id
    scenario_id = scenario.id

    # Time grid
    time_grid = None
    if scenario.selected_time_grid_id:
        tg_result = await db.execute(
            select(TimeGrid).where(TimeGrid.id == scenario.selected_time_grid_id)
        )
        time_grid = tg_result.scalar_one_or_none()

    # Scheduling targets
    targets_result = await db.execute(
        select(SchedulingTarget).where(
            SchedulingTarget.institution_id == institution_id,
            SchedulingTarget.academic_term_id == academic_term_id,
            SchedulingTarget.scenario_id == scenario_id,
            SchedulingTarget.is_active == True,  # noqa: E712
        )
    )
    targets = list(targets_result.scalars().all())

    # Rooms in venue pool (for now: all active rooms for institution)
    rooms_result = await db.execute(
        select(Room).where(
            Room.institution_id == institution_id,
            Room.is_active == True,  # noqa: E712
        )
    )
    rooms = list(rooms_result.scalars().all())

    # Offering buckets + offerings
    buckets_result = await db.execute(
        select(OfferingBucket).where(
            OfferingBucket.institution_id == institution_id,
            OfferingBucket.academic_term_id == academic_term_id,
            OfferingBucket.scenario_id == scenario_id,
            OfferingBucket.is_active == True,  # noqa: E712
        )
    )
    buckets = list(buckets_result.scalars().all())
    bucket_ids = [b.id for b in buckets]

    offerings: list[CourseOffering] = []
    if bucket_ids:
        off_result = await db.execute(
            select(CourseOffering).where(CourseOffering.bucket_id.in_(bucket_ids))
        )
        offerings = list(off_result.scalars().all())

    # Courses referenced in offerings
    course_ids = list({o.course_id for o in offerings})
    courses: dict[str, Any] = {}
    if course_ids:
        c_result = await db.execute(select(Course).where(Course.id.in_(course_ids)))
        for c in c_result.scalars().all():
            courses[str(c.id)] = c

    # Faculty referenced in offerings
    faculty_ids_in_offerings = list({o.faculty_id for o in offerings if o.faculty_id})
    faculty: dict[str, Any] = {}
    if faculty_ids_in_offerings:
        f_result = await db.execute(
            select(Faculty).where(Faculty.id.in_(faculty_ids_in_offerings))
        )
        for f in f_result.scalars().all():
            faculty[str(f.id)] = f

    # Scenario rules (enabled constraints)
    rules_result = await db.execute(
        select(ScenarioRule).where(
            ScenarioRule.scenario_id == scenario_id,
            ScenarioRule.is_enabled == True,  # noqa: E712
        )
    )
    scenario_rules = list(rules_result.scalars().all())

    # Compute break slot codes from MANDATORY_BREAK rule
    break_slot_codes: set[str] = set()
    for rule in scenario_rules:
        if rule.definition_code == "MANDATORY_BREAK":
            slot_codes = rule.params.get("slot_codes", []) if rule.params else []
            break_slot_codes.update(slot_codes)

    # Available slots from time grid
    all_slot_codes: list[str] = []
    slots_by_code: dict[str, dict] = {}
    if time_grid and time_grid.slots:
        if isinstance(time_grid.slots, dict):
            slots_by_code = time_grid.slots
            all_slot_codes = list(time_grid.slots.keys())
        elif isinstance(time_grid.slots, list):
            for s in time_grid.slots:
                if isinstance(s, dict) and "code" in s:
                    slots_by_code[s["code"]] = s
                    all_slot_codes.append(s["code"])

    available_slot_codes = [c for c in all_slot_codes if c not in break_slot_codes]

    # Target requirements (target → bucket mapping)
    target_req_result = await db.execute(
        select(TargetRequirement).where(
            TargetRequirement.target_id.in_([t.id for t in targets])
        )
    )
    target_requirements = list(target_req_result.scalars().all())

    # Build target → buckets mapping
    target_bucket_map: dict[str, list[str]] = {}
    for tr in target_requirements:
        target_bucket_map.setdefault(str(tr.target_id), []).append(str(tr.bucket_id))

    # Build bucket → offerings mapping
    bucket_offerings_map: dict[str, list[CourseOffering]] = {}
    for o in offerings:
        bucket_offerings_map.setdefault(str(o.bucket_id), []).append(o)

    summary = {
        "total_session_demand": sum(
            (courses[str(o.course_id)].weekly_hours if str(o.course_id) in courses else 1)
            for o in offerings
        ),
        "total_slots": len(all_slot_codes),
        "available_slots": len(available_slot_codes),
        "faculty_count": len(faculty),
        "room_count": len(rooms),
    }

    return {
        "scenario": scenario,
        "time_grid": time_grid,
        "targets": targets,
        "rooms": rooms,
        "buckets": buckets,
        "offerings": offerings,
        "courses": courses,
        "faculty": faculty,
        "scenario_rules": scenario_rules,
        "break_slot_codes": break_slot_codes,
        "all_slot_codes": all_slot_codes,
        "slots_by_code": slots_by_code,
        "available_slot_codes": available_slot_codes,
        "target_bucket_map": target_bucket_map,
        "bucket_offerings_map": bucket_offerings_map,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Category E — Completeness checks
# ---------------------------------------------------------------------------


def _check_completeness(ctx: dict) -> list[FeasibilityIssue]:
    issues: list[FeasibilityIssue] = []

    if ctx["time_grid"] is None:
        issues.append(FeasibilityIssue(
            severity="ERROR",
            code="NO_TIME_GRID",
            message="No time grid selected for this scenario. Select a time grid before solving.",
            entity=None,
        ))

    if not ctx["targets"]:
        issues.append(FeasibilityIssue(
            severity="ERROR",
            code="NO_SCHEDULING_TARGETS",
            message="No scheduling targets found for this scenario. Create batches or cohorts first.",
            entity=None,
        ))

    if not ctx["rooms"]:
        issues.append(FeasibilityIssue(
            severity="ERROR",
            code="NO_ROOMS",
            message="No rooms found in the venue pool. Add rooms to the institution first.",
            entity=None,
        ))

    if not ctx["buckets"]:
        issues.append(FeasibilityIssue(
            severity="WARNING",
            code="NO_OFFERING_BUCKETS",
            message="No offering buckets found. Run allocation or manually create offerings.",
            entity=None,
        ))
        return issues

    # Check for empty buckets
    for bucket in ctx["buckets"]:
        bucket_id_str = str(bucket.id)
        if not ctx["bucket_offerings_map"].get(bucket_id_str):
            issues.append(FeasibilityIssue(
                severity="ERROR",
                code="EMPTY_OFFERING_BUCKET",
                message=f"Offering bucket '{bucket.name}' has no course offerings.",
                entity=str(bucket.id),
                detail={"bucket_id": str(bucket.id), "bucket_name": bucket.name},
            ))

    # Check for unassigned offerings (no faculty)
    unassigned = [o for o in ctx["offerings"] if o.faculty_id is None]
    if unassigned:
        scenario = ctx["scenario"]
        assignment_mode = getattr(scenario, "assignment_mode", "MANUAL")
        if assignment_mode == "MANUAL":
            issues.append(FeasibilityIssue(
                severity="WARNING",
                code="UNASSIGNED_COURSES",
                message=f"{len(unassigned)} offering(s) have no faculty assigned and solver-fill is OFF.",
                entity=None,
                detail={"count": len(unassigned)},
            ))

    return issues


# ---------------------------------------------------------------------------
# Category A — Group slot checks
# ---------------------------------------------------------------------------


def _check_group_slots(ctx: dict) -> list[FeasibilityIssue]:
    issues: list[FeasibilityIssue] = []

    if not ctx["time_grid"] or not ctx["available_slot_codes"]:
        return issues

    available_count = len(ctx["available_slot_codes"])
    courses = ctx["courses"]

    for target in ctx["targets"]:
        target_id_str = str(target.id)
        bucket_ids_for_target = ctx["target_bucket_map"].get(target_id_str, [])

        if not bucket_ids_for_target:
            continue

        # Count total weekly session demand for this target
        total_demand = 0
        for bid in bucket_ids_for_target:
            for offering in ctx["bucket_offerings_map"].get(bid, []):
                course = courses.get(str(offering.course_id))
                if course:
                    total_demand += getattr(course, "weekly_hours", 1) or 1
                else:
                    total_demand += 1

        if total_demand == 0:
            continue

        if total_demand > available_count:
            issues.append(FeasibilityIssue(
                severity="ERROR",
                code="GROUP_SLOTS_INSUFFICIENT",
                message=(
                    f"{target.name}: needs {total_demand} slots/week, "
                    f"only {available_count} available after breaks"
                ),
                entity=target_id_str,
                detail={
                    "target_name": target.name,
                    "demand": total_demand,
                    "available": available_count,
                    "deficit": total_demand - available_count,
                    "total_grid_slots": len(ctx["all_slot_codes"]),
                    "break_slots": len(ctx["break_slot_codes"]),
                },
            ))
        elif available_count > 0 and total_demand > available_count / 1.25:
            headroom_pct = round((available_count - total_demand) / available_count * 100, 1)
            issues.append(FeasibilityIssue(
                severity="WARNING",
                code="GROUP_SLOTS_TIGHT",
                message=(
                    f"{target.name}: only {headroom_pct}% slot headroom "
                    f"({total_demand} demand / {available_count} available)"
                ),
                entity=target_id_str,
                detail={
                    "target_name": target.name,
                    "demand": total_demand,
                    "available": available_count,
                    "headroom_pct": headroom_pct,
                },
            ))

    return issues


# ---------------------------------------------------------------------------
# Category B — Faculty load checks
# ---------------------------------------------------------------------------


def _check_faculty_load(ctx: dict) -> list[FeasibilityIssue]:
    issues: list[FeasibilityIssue] = []
    faculty = ctx["faculty"]
    courses = ctx["courses"]
    available_count = len(ctx["available_slot_codes"])
    break_slot_codes = ctx["break_slot_codes"]

    # Compute per-faculty confirmed session load
    faculty_load: dict[str, int] = {}
    for offering in ctx["offerings"]:
        if offering.faculty_id is None:
            continue
        fid = str(offering.faculty_id)
        course = courses.get(str(offering.course_id))
        hours = getattr(course, "weekly_hours", 1) or 1 if course else 1
        faculty_load[fid] = faculty_load.get(fid, 0) + hours

    for fid, load in faculty_load.items():
        fac = faculty.get(fid)
        if fac is None:
            continue

        max_hours = getattr(fac, "max_weekly_hours", 0) or 0

        if max_hours > 0:
            if load > max_hours:
                fac_name = getattr(fac, "name", fid)
                issues.append(FeasibilityIssue(
                    severity="ERROR",
                    code="FACULTY_OVERLOADED",
                    message=(
                        f"{fac_name}: assigned {load} sessions/week, "
                        f"limit is {max_hours}"
                    ),
                    entity=fid,
                    detail={"load": load, "limit": max_hours, "faculty_name": fac_name},
                ))
            elif load >= max_hours * 0.85:
                fac_name = getattr(fac, "name", fid)
                pct = round(load / max_hours * 100)
                issues.append(FeasibilityIssue(
                    severity="WARNING",
                    code="FACULTY_NEAR_CAPACITY",
                    message=f"{fac_name}: near capacity ({load}/{max_hours} hrs, {pct}%)",
                    entity=fid,
                    detail={"load": load, "limit": max_hours, "pct": pct, "faculty_name": fac_name},
                ))

        # Blacklist check
        blacklist = getattr(fac, "availability_blacklist", None) or []
        if blacklist and available_count > 0:
            effective_slots = available_count - len(
                [c for c in blacklist if c not in break_slot_codes]
            )
            if load > effective_slots:
                fac_name = getattr(fac, "name", fid)
                issues.append(FeasibilityIssue(
                    severity="ERROR",
                    code="FACULTY_BLACKLIST_CONFLICT",
                    message=(
                        f"{fac_name}: availability blacklist leaves only {effective_slots} "
                        f"eligible slots, but needs {load} sessions"
                    ),
                    entity=fid,
                    detail={
                        "load": load,
                        "effective_slots": effective_slots,
                        "blacklisted": len(blacklist),
                        "faculty_name": fac_name,
                    },
                ))

    return issues


# ---------------------------------------------------------------------------
# Category C — Room adequacy checks
# ---------------------------------------------------------------------------


def _check_room_adequacy(ctx: dict) -> list[FeasibilityIssue]:
    issues: list[FeasibilityIssue] = []
    rooms = ctx["rooms"]
    courses = ctx["courses"]
    offerings = ctx["offerings"]
    slots_by_code = ctx["slots_by_code"]
    break_slot_codes = ctx["break_slot_codes"]

    if not rooms:
        return issues  # already caught by NO_ROOMS

    # Check for lab rooms when lab courses exist
    has_lab_courses = any(
        str(o.course_id) in courses
        and _course_requires_lab(courses[str(o.course_id)])
        for o in offerings
    )
    lab_rooms = [r for r in rooms if _get_room_type(r) == "LAB"]
    theory_rooms = [r for r in rooms if _get_room_type(r) in ("LECTURE", "SEMINAR", "LECTURE_HALL", "THEORY")]

    if has_lab_courses and not lab_rooms:
        issues.append(FeasibilityIssue(
            severity="ERROR",
            code="NO_LAB_ROOMS",
            message="Scenario has lab courses but no lab rooms in the venue pool.",
            entity=None,
        ))

    # Room capacity check: check if any room can fit the largest group
    if ctx["targets"]:
        max_group_size = max((getattr(t, "size", 0) or 0) for t in ctx["targets"])
        max_room_capacity = max((getattr(r, "capacity", 0) or 0) for r in rooms) if rooms else 0
        if max_group_size > 0 and max_room_capacity > 0 and max_room_capacity < max_group_size:
            issues.append(FeasibilityIssue(
                severity="ERROR",
                code="ROOM_CAPACITY_INSUFFICIENT",
                message=(
                    f"Largest room capacity ({max_room_capacity}) is smaller than "
                    f"largest group size ({max_group_size})."
                ),
                entity=None,
                detail={"max_room_capacity": max_room_capacity, "max_group_size": max_group_size},
            ))

    # Room-type capacity exhaustion check
    for room_type_key in ["LAB", "LECTURE"]:
        if room_type_key == "LAB":
            type_rooms = lab_rooms
            slot_type = "lab"
        else:
            type_rooms = theory_rooms
            slot_type = "theory"

        n_rooms = len(type_rooms)
        if n_rooms == 0:
            continue

        # Count available slots for this type
        type_slots = [
            code for code, slot_data in slots_by_code.items()
            if code not in break_slot_codes
            and (
                slot_data.get("slot_type", "theory") == slot_type
                if isinstance(slot_data, dict) else True
            )
        ]
        if not type_slots:
            # Fallback: use all available slots
            type_slots = ctx["available_slot_codes"]

        n_slots = len(type_slots)
        total_capacity = n_rooms * n_slots

        # Total demand for this room type
        total_demand = 0
        for offering in offerings:
            course = courses.get(str(offering.course_id))
            if course is None:
                continue
            if room_type_key == "LAB" and _course_requires_lab(course):
                total_demand += getattr(course, "weekly_hours", 1) or 1
            elif room_type_key == "LECTURE" and not _course_requires_lab(course):
                total_demand += getattr(course, "weekly_hours", 1) or 1

        if total_demand == 0 or total_capacity == 0:
            continue

        utilisation_pct = round(total_demand / total_capacity * 100, 1)

        if total_demand > total_capacity:
            issues.append(FeasibilityIssue(
                severity="ERROR",
                code="ROOM_TYPE_CAPACITY_EXHAUSTED",
                message=(
                    f"{room_type_key} rooms: {n_rooms} rooms × {n_slots} slots = {total_capacity} capacity, "
                    f"but {total_demand} sessions needed. Deficit: {total_demand - total_capacity}."
                ),
                entity=None,
                detail={
                    "room_type": room_type_key,
                    "rooms": n_rooms,
                    "slots_per_week": n_slots,
                    "capacity": total_capacity,
                    "demand": total_demand,
                    "utilisation_pct": utilisation_pct,
                },
            ))
        elif utilisation_pct > 80:
            issues.append(FeasibilityIssue(
                severity="WARNING",
                code="ROOM_TYPE_CAPACITY_TIGHT",
                message=(
                    f"{room_type_key} rooms at {utilisation_pct}% utilisation "
                    f"({total_demand}/{total_capacity} room-slot units)."
                ),
                entity=None,
                detail={
                    "room_type": room_type_key,
                    "rooms": n_rooms,
                    "slots_per_week": n_slots,
                    "capacity": total_capacity,
                    "demand": total_demand,
                    "utilisation_pct": utilisation_pct,
                },
            ))

    # Pinned room checks
    room_ids = {r.id for r in rooms}
    for offering in offerings:
        pinned_ids: list[str] = []
        if getattr(offering, "target_room_ids", None):
            pinned_ids.extend(offering.target_room_ids)
        if getattr(offering, "target_lab_room_ids", None):
            pinned_ids.extend(offering.target_lab_room_ids)
        for rid in pinned_ids:
            if rid not in room_ids:
                issues.append(FeasibilityIssue(
                    severity="ERROR",
                    code="PINNED_ROOM_UNAVAILABLE",
                    message=(
                        f"Offering {offering.id}: pinned room {rid} "
                        f"is not in the venue pool."
                    ),
                    entity=str(offering.id),
                    detail={
                        "offering_id": str(offering.id),
                        "target_room_id": rid,
                        "is_soft": getattr(offering, "target_room_ids_soft", False),
                    },
                ))

    return issues


# ---------------------------------------------------------------------------
# Category D — Constraint-aware checks
# ---------------------------------------------------------------------------


def _check_constraints(ctx: dict) -> list[FeasibilityIssue]:
    issues: list[FeasibilityIssue] = []
    scenario_rules = ctx["scenario_rules"]
    slots_by_code = ctx["slots_by_code"]
    break_slot_codes = ctx["break_slot_codes"]
    available_slot_codes = ctx["available_slot_codes"]

    if not slots_by_code:
        return issues

    for rule in scenario_rules:
        code = rule.definition_code
        params = rule.params or {}

        if code == "ALLOWED_DAYS":
            allowed_days = set(params.get("allowed_days", []))
            if allowed_days:
                available_on_allowed = [
                    c for c in available_slot_codes
                    if isinstance(slots_by_code.get(c), dict)
                    and slots_by_code[c].get("day") in allowed_days
                ]
                if not available_on_allowed:
                    issues.append(FeasibilityIssue(
                        severity="ERROR",
                        code="ALLOWED_DAYS_NO_SLOTS",
                        message=(
                            f"ALLOWED_DAYS rule restricts to days {allowed_days}, "
                            f"but no non-break slots exist on those days."
                        ),
                        entity=str(rule.id) if hasattr(rule, "id") else None,
                        detail={"allowed_days": list(allowed_days)},
                    ))

        elif code == "MANDATORY_BREAK":
            # Check if a full day is wiped out by breaks
            days_with_slots: set[str] = set()
            days_all_broken: set[str] = set()
            for c, slot_data in slots_by_code.items():
                if isinstance(slot_data, dict):
                    day = slot_data.get("day", "")
                    if day:
                        if c not in break_slot_codes:
                            days_with_slots.add(day)
                        else:
                            days_all_broken.add(day)

            fully_broken = days_all_broken - days_with_slots
            if fully_broken:
                issues.append(FeasibilityIssue(
                    severity="WARNING",
                    code="MANDATORY_BREAK_WIPES_DAY",
                    message=(
                        f"MANDATORY_BREAK rule removes all slots on: {', '.join(sorted(fully_broken))}."
                    ),
                    entity=None,
                    detail={"affected_days": sorted(fully_broken)},
                ))

    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _course_requires_lab(course: Any) -> bool:
    session_type = getattr(course, "session_type", None)
    if session_type is None:
        return False
    st = str(session_type).upper()
    return st in ("LAB", "BOTH")


def _get_room_type(room: Any) -> str:
    room_type = getattr(room, "room_type", None)
    if room_type is None:
        return "LECTURE"
    return str(room_type).upper()
