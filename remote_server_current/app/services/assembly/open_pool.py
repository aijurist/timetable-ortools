"""
app/services/assembly/open_pool.py
====================================
OpenPoolAssembler — SelectionPolicy.OPEN_POOL (FFCS mode).

One OfferingBucket = a curriculum cluster with many CourseOffering rows.
Students self-register from the pool after the timetable is set.

Key differences:
  - session_count = 1   (atomic bundle — one assignment per offering)
  - group_ids = []      (no GroupData — no overlap constraints at solve time)
  - slot_bundle         (resolved from offering.slot_family + time grid family keys)
"""

from __future__ import annotations

from typing import Any

from solver_engine.contracts import SessionData

from app.services.assembly.base import (
    AssemblyContext,
    AssemblyResult,
    _is_merged,
    _resolve_auto_batch,
    _resolve_slot_bundle,
    _resolve_target_size,
)


class OpenPoolAssembler:
    """FFCS mode: atomic bundles, no groups, student-side clash detection."""

    def assemble(self, bucket: Any, ctx: AssemblyContext) -> AssemblyResult:
        if not bucket.offerings:
            return AssemblyResult(sessions=[], groups=[], parallel_groups=[])

        dept_days: list[str] | None = ctx.dept_working_days.get(str(bucket.department_id))
        sessions: list[SessionData] = []

        for offering in bucket.offerings:
            course = ctx.courses.get(str(offering.course_id))
            if course is None:
                continue

            is_lab = getattr(course, "session_type", "THEORY") == "LAB"
            # Headcount: offering.min_capacity > SchedulingTarget.size > max_seats fallback
            target_size = _resolve_target_size(bucket, ctx, offering) or getattr(offering, "max_seats", None) or 0
            bundle, needs_pattern = _resolve_slot_bundle(
                offering, course, ctx.slots, ctx.slot_pattern_rules
            )

            # ── Room data — priority: TA override > Course default ────────────
            ta = ctx.teaching_assignments.get(str(offering.course_id))
            # Merged session: all sections combine into one room — recompute capacity
            if _is_merged(ta):
                per_section = _resolve_target_size(bucket, ctx)
                if per_section > 0:
                    target_size = ta.section_count * per_section
            target_room_ids = (
                list(ta.override_room_ids) if ta and getattr(ta, "override_room_ids", None)
                else list(course.preferred_room_ids) if getattr(course, "preferred_room_ids", None) else None
            )
            target_lab_room_ids = (
                list(ta.override_lab_room_ids) if ta and getattr(ta, "override_lab_room_ids", None)
                else list(course.lab_preferred_room_ids) if getattr(course, "lab_preferred_room_ids", None) else None
            )
            target_room_tags     = list(offering.target_room_tags) if getattr(offering, "target_room_tags", None) else None
            target_lab_room_tags = list(offering.target_lab_room_tags) if getattr(offering, "target_lab_room_tags", None) else None
            if is_lab:
                flat_allowed_room_ids = target_lab_room_ids or target_room_ids
                flat_required_tags = target_lab_room_tags or list(course.room_tags or [])
            else:
                flat_allowed_room_ids = target_room_ids
                flat_required_tags = target_room_tags or list(course.room_tags or [])
            course_room_tags_soft = bool(
                (is_lab and getattr(course, "lab_room_tags_soft", False))
                or (not is_lab and getattr(course, "room_tags_soft", False))
            )
            _ta_lab_ovr = ta and getattr(ta, "override_lab_room_ids", None)
            _ta_ovr     = ta and getattr(ta, "override_room_ids", None)
            if is_lab and _ta_lab_ovr:
                course_room_assignment_soft = bool(getattr(ta, "override_lab_room_ids_soft", True))
            elif _ta_ovr:
                course_room_assignment_soft = bool(getattr(ta, "override_room_ids_soft", True))
            else:
                course_room_assignment_soft = bool(
                    (is_lab and getattr(course, "lab_preferred_room_ids_soft", True))
                    or (not is_lab and getattr(course, "preferred_room_ids_soft", True))
                )
            if _is_merged(ta):
                n_batches, batch_capacity = 1, target_size
            else:
                n_batches, batch_capacity = _resolve_auto_batch(
                    target_size, is_lab, flat_required_tags, ctx.rooms,
                    allowed_room_ids=flat_allowed_room_ids,
                )

            for batch in range(1, n_batches + 1):
                b_sfx = f"__b{batch}" if n_batches > 1 else ""
                sessions.append(SessionData(
                    session_key=f"{offering.id}{b_sfx}__s1",
                    offering_id=str(offering.id),
                    course_id=str(offering.course_id),
                    faculty_id=str(offering.faculty_id) if offering.faculty_id else "",
                    department_id=str(bucket.department_id),
                    study_semester=getattr(offering, "study_semester", None) or 0,
                    is_lab=is_lab,
                    session_type="LAB" if is_lab else "THEORY",
                    session_count=1,
                    group_ids=[],
                    min_capacity=batch_capacity,
                    max_capacity=getattr(offering, "max_room_capacity", None) or 0,
                    slot_bundle=bundle,
                    needs_pattern=needs_pattern,
                    allowed_days=dept_days,
                    allowed_room_ids=flat_allowed_room_ids,
                    required_tags=flat_required_tags,
                    room_tags_soft=course_room_tags_soft,
                    room_assignment_soft=course_room_assignment_soft,
                ))

        # No GroupData, no ParallelGroupData in FFCS
        return AssemblyResult(sessions=sessions, groups=[], parallel_groups=[])
