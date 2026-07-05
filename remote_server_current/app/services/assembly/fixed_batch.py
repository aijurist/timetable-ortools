"""
app/services/assembly/fixed_batch.py
=====================================
FixedBatchAssembler — SelectionPolicy.FIXED_BATCH (TRADITIONAL mode).

One OfferingBucket = one course for one section (e.g. bucket-DSA-CSEA).
Exactly 1 CourseOffering per bucket (one teacher, one assigned group).

LTPC-aware:
  - If course.structure defines multiple component types (L/T/P), each component
    gets its own group_id = "<bucket_id>__<L|T|P>" sharing the same scope_key.
    GroupNoDoubleBook then prevents lecture, tutorial, and practical sessions from
    the same section from overlapping with each other or with other courses.
  - Simple courses (single session_type) fall back to the flat group model.

scope_key is per-target (per-section), NOT per-department.
"""

from __future__ import annotations

from typing import Any

from solver_engine.contracts import GroupData, SessionData

from app.services.assembly.base import (
    AssemblyContext,
    AssemblyResult,
    _has_multiple_components,
    _is_merged,
    _make_component_sessions,
    _resolve_auto_batch,
    _resolve_scope_key,
    _resolve_slot_bundle,
    _resolve_target_size,
)


class FixedBatchAssembler:
    """TRADITIONAL mode: 1 offering per bucket, sessions share component groups (or one flat group)."""

    def assemble(self, bucket: Any, ctx: AssemblyContext) -> AssemblyResult:
        if not bucket.offerings:
            return AssemblyResult(sessions=[], groups=[], parallel_groups=[])

        offering = bucket.offerings[0]   # FIXED_BATCH: always exactly 1
        course = ctx.courses.get(str(offering.course_id))
        if course is None:
            return AssemblyResult(sessions=[], groups=[], parallel_groups=[])

        dept_days: list[str] | None = ctx.dept_working_days.get(str(bucket.department_id))
        scope_key = _resolve_scope_key(bucket, ctx)
        target_size = _resolve_target_size(bucket, ctx, offering)
        # ── Room data — priority: TA override > Course default ────────────────
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
        # Per-course soft flags: override global ROOM_TAGS / ROOM_ASSIGNMENT is_hard setting
        is_lab_session = getattr(course, "session_type", "THEORY") == "LAB"
        course_room_tags_soft = bool(
            (is_lab_session and getattr(course, "lab_room_tags_soft", False))
            or (not is_lab_session and getattr(course, "room_tags_soft", False))
        )
        # Softness source depends on WHERE the room ids came from.
        # TA-level override → use TA's soft flag; course preference → use course's soft flag.
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
        # ── LTPC component-aware path ─────────────────────────────────────────
        if _has_multiple_components(course):
            ltpc_sessions, comp_members = _make_component_sessions(
                offering=offering,
                course=course,
                group_id_prefix=str(bucket.id),
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
            groups = [
                GroupData(
                    group_id=f"{bucket.id}__{comp}",
                    member_session_keys=keys,
                    scope_key=scope_key,
                )
                for comp, keys in comp_members.items()
            ]
            return AssemblyResult(sessions=ltpc_sessions, groups=groups, parallel_groups=[])

        # ── Flat / simple course path (single session_type) ───────────────────
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

        sessions: list[SessionData] = []
        all_keys: list[str] = []

        for batch in range(1, n_batches + 1):
            b_sfx = f"__b{batch}" if n_batches > 1 else ""
            for i in range(1, weekly_hours + 1):
                key = f"{offering.id}{b_sfx}__s{i}"
                all_keys.append(key)
                # Lab peer pairing within each batch
                peer: str | None = None
                if is_lab and weekly_hours > 1:
                    peer_i = i + 1 if i % 2 == 1 else i - 1
                    peer = f"{offering.id}{b_sfx}__s{peer_i}"
                sessions.append(SessionData(
                    session_key=key,
                    offering_id=str(offering.id),
                    course_id=str(offering.course_id),
                    faculty_id=str(offering.faculty_id) if offering.faculty_id else "",
                    department_id=str(bucket.department_id),
                    study_semester=getattr(offering, "study_semester", None) or 0,
                    is_lab=is_lab,
                    session_type="LAB" if is_lab else "THEORY",
                    session_count=weekly_hours,
                    group_ids=[str(bucket.id)],
                    min_capacity=batch_capacity,
                    max_capacity=getattr(offering, "max_room_capacity", None) or 0,
                    consecutive_peer_key=peer,
                    allowed_days=dept_days,
                    allowed_room_ids=flat_allowed_room_ids,
                    required_tags=flat_required_tags,
                    room_tags_soft=course_room_tags_soft,
                    room_assignment_soft=course_room_assignment_soft,
                    slot_bundle=slot_bundle,
                    needs_pattern=needs_pattern,
                ))

        groups = [GroupData(
            group_id=str(bucket.id),
            member_session_keys=all_keys,
            scope_key=scope_key,
        )]

        return AssemblyResult(sessions=sessions, groups=groups, parallel_groups=[])
