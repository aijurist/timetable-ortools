"""
app/services/assembly/choice.py
================================
ChoiceAssembler — handles both CHOOSE_FACULTY and CHOOSE_COURSE policies.

These two policies share identical solver logic. The only runtime distinction
is the force_parallel_slots flag on the bucket:

    force_parallel_slots=False (default):
        All offerings in the bucket share the SAME bucket-level GroupData in the
        target scope. GroupNoDoubleBook prevents this bucket from overlapping with
        other buckets in the same scope, while same-bucket offerings can still run
        in parallel. TeacherNoDoubleBook prevents the same teacher from double-booking.

  force_parallel_slots=True:
    Same as above, plus ParallelGroupData is emitted.
    parallel_session_lock forces all offerings to the same time slot —
    students pick a subject (or teacher) with no time choice.

CHOOSE_FACULTY: same course, different teachers → teacher diversity
CHOOSE_COURSE:  different courses, same slot role → subject diversity
Both assembled identically — the policy label is purely semantic.

LTPC-aware: multi-component courses expand per component with per-offering
group isolation. force_parallel_slots with LTPC is skipped with a warning.
"""

from __future__ import annotations

import logging
from typing import Any

from solver_engine.contracts import GroupData, ParallelGroupData, SessionData

from app.services.assembly.base import (
    AssemblyContext,
    AssemblyResult,
    _has_multiple_components,
    _is_merged,
    _make_component_sessions,
    _resolve_auto_batch,
    _resolve_fixed_slot,
    _resolve_scope_key,
    _resolve_slot_bundle,
    _resolve_target_size,
)

logger = logging.getLogger("app.assembly.choice")


class ChoiceAssembler:
    """
    Unified assembler for CHOOSE_FACULTY and CHOOSE_COURSE.

    Group semantics follow the solver contract: one GroupData per OfferingBucket
    (or per bucket component for LTPC). ParallelGroupData is emitted only when
    force_parallel_slots=True.
    """

    def assemble(self, bucket: Any, ctx: AssemblyContext) -> AssemblyResult:
        if not bucket.offerings:
            return AssemblyResult(sessions=[], groups=[], parallel_groups=[])

        scope_key = _resolve_scope_key(bucket, ctx)
        dept_days: list[str] | None = ctx.dept_working_days.get(str(bucket.department_id))
        force_parallel: bool = getattr(bucket, "force_parallel_slots", False)

        all_sessions: list[SessionData] = []
        all_groups: list[GroupData] = []
        all_parallel_keys: list[str] = []   # collected for ParallelGroupData
        bucket_member_keys: list[str] = []
        component_members: dict[str, list[str]] = {}

        for offering in bucket.offerings:
            course = ctx.courses.get(str(offering.course_id))
            if course is None:
                continue

            # Headcount: offering.min_capacity > SchedulingTarget.size > max_seats fallback
            target_size = _resolve_target_size(bucket, ctx, offering) or getattr(offering, "max_seats", None) or 0

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
            allowed_room_ids     = target_room_ids
            room_tags           = list(course.room_tags or [])
            is_lab_session = getattr(course, "session_type", "THEORY") == "LAB"
            course_room_tags_soft = bool(
                (is_lab_session and getattr(course, "lab_room_tags_soft", False))
                or (not is_lab_session and getattr(course, "room_tags_soft", False))
            )
            _ta_lab_ovr = ta and getattr(ta, "override_lab_room_ids", None)
            _ta_ovr     = ta and getattr(ta, "override_room_ids", None)
            if is_lab_session and _ta_lab_ovr:
                course_room_assignment_soft = bool(getattr(ta, "override_lab_room_ids_soft", True))
            elif _ta_ovr:
                course_room_assignment_soft = bool(getattr(ta, "override_room_ids_soft", True))
            else:
                course_room_assignment_soft = bool(
                    (is_lab_session and getattr(course, "lab_preferred_room_ids_soft", True))
                    or (not is_lab_session and getattr(course, "preferred_room_ids_soft", True))
                )

            # ── Pre-locked slot (CHOOSE_COURSE elective pre-assignment) ───────
            allowed_slot_codes: list[str] | None = None
            fixed_slot_id = getattr(offering, "fixed_slot_id", None)
            if fixed_slot_id is not None:
                slot = _resolve_fixed_slot(fixed_slot_id, ctx.slots)
                allowed_slot_codes = [slot] if slot else None

            # ── LTPC component path ───────────────────────────────────────────
            if _has_multiple_components(course):
                if force_parallel:
                    logger.warning(
                        "LTPC course in force_parallel bucket — "
                        "component expansion skipped, treating as flat",
                        extra={"offering_id": str(offering.id), "bucket_id": str(bucket.id)},
                    )
                    # fall through to flat path
                else:
                    new_sessions, comp_members = _make_component_sessions(
                        offering=offering,
                        course=course,
                        group_id_prefix=str(offering.id),
                        target_size=target_size,
                        dept_days=dept_days,
                        department_id=str(bucket.department_id),
                        room_tags=room_tags,
                        target_room_ids=target_room_ids,
                        target_lab_room_ids=target_lab_room_ids,
                        target_room_tags=target_room_tags,
                        target_lab_room_tags=target_lab_room_tags,
                        rooms=ctx.rooms,
                        ta=ta,
                        is_merged=_is_merged(ta),
                        study_semester=getattr(offering, "study_semester", None) or 0,
                        max_room_capacity=getattr(offering, "max_room_capacity", None) or 0,
                        slots=ctx.slots,
                        slot_pattern_rules=ctx.slot_pattern_rules,
                    )
                    all_sessions.extend(new_sessions)
                    for comp, keys in comp_members.items():
                        component_members.setdefault(comp, []).extend(keys)
                    continue  # skip flat path for this offering

            # ── Flat path ─────────────────────────────────────────────────────
            weekly_hours = getattr(course, "weekly_hours", 3)
            is_lab = getattr(course, "session_type", "THEORY") == "LAB"
            if is_lab:
                flat_allowed_room_ids = target_lab_room_ids or allowed_room_ids
                flat_required_tags = target_lab_room_tags or room_tags
            else:
                flat_allowed_room_ids = allowed_room_ids
                flat_required_tags = target_room_tags or room_tags
            if _is_merged(ta):
                n_batches, batch_capacity = 1, target_size
            else:
                n_batches, batch_capacity = _resolve_auto_batch(
                    target_size, is_lab, flat_required_tags, ctx.rooms,
                    allowed_room_ids=flat_allowed_room_ids,
                )
            slot_bundle, needs_pattern = _resolve_slot_bundle(
                offering, course, ctx.slots, ctx.slot_pattern_rules
            )

            # Same-bucket offerings share one bucket-level group so they can
            # run in parallel while still conflicting with other buckets.
            bucket_group_id = str(bucket.id)

            for batch in range(1, n_batches + 1):
                b_sfx = f"__b{batch}" if n_batches > 1 else ""
                for i in range(1, weekly_hours + 1):
                    key = f"{offering.id}{b_sfx}__s{i}"
                    bucket_member_keys.append(key)
                    all_parallel_keys.append(key)

                    peer: str | None = None
                    if is_lab and weekly_hours > 1:
                        peer_i = i + 1 if i % 2 == 1 else i - 1
                        peer = f"{offering.id}{b_sfx}__s{peer_i}"

                    all_sessions.append(SessionData(
                        session_key=key,
                        offering_id=str(offering.id),
                        course_id=str(offering.course_id),
                        faculty_id=str(offering.faculty_id) if offering.faculty_id else "",
                        department_id=str(bucket.department_id),
                        study_semester=getattr(offering, "study_semester", None) or 0,
                        is_lab=is_lab,
                        session_type="LAB" if is_lab else "THEORY",
                        session_count=weekly_hours,
                        group_ids=[bucket_group_id],
                        min_capacity=batch_capacity,
                        max_capacity=getattr(offering, "max_room_capacity", None) or 0,
                        consecutive_peer_key=peer,
                        allowed_days=dept_days,
                        allowed_room_ids=flat_allowed_room_ids,
                        allowed_slot_codes=allowed_slot_codes,
                        required_tags=flat_required_tags,
                        room_tags_soft=course_room_tags_soft,
                        room_assignment_soft=course_room_assignment_soft,
                        slot_bundle=slot_bundle,
                        needs_pattern=needs_pattern,
                    ))

        if not all_sessions:
            return AssemblyResult(sessions=[], groups=[], parallel_groups=[])

        if component_members:
            all_groups.extend(
                GroupData(
                    group_id=f"{bucket.id}__{comp}",
                    member_session_keys=keys,
                    scope_key=scope_key,
                )
                for comp, keys in component_members.items()
            )
        elif bucket_member_keys:
            all_groups.append(GroupData(
                group_id=str(bucket.id),
                member_session_keys=bucket_member_keys,
                scope_key=scope_key,
            ))

        # Emit ParallelGroupData only when force_parallel_slots=True
        parallel_groups: list[ParallelGroupData] = []
        if force_parallel and all_parallel_keys:
            parallel_groups.append(ParallelGroupData(
                parallel_key=f"{bucket.id}__choice_parallel",
                member_session_keys=all_parallel_keys,
            ))

        return AssemblyResult(
            sessions=all_sessions,
            groups=all_groups,
            parallel_groups=parallel_groups,
        )
