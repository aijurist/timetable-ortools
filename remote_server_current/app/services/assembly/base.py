"""
app/services/assembly/base.py
=============================
AssemblyStrategy Protocol, AssemblyContext, AssemblyResult, and shared helpers.

Lives in app/, NOT in solver_engine/ — imports SQLAlchemy ORM models.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from solver_engine.contracts import GroupData, ParallelGroupData, RoomData, SessionData

# ─── LTPC Component Config ─────────────────────────────────────────────────────
# (structure_key, is_lab) — order determines session key suffix (L, T, P)
_LTPC_COMPONENTS: list[tuple[str, bool]] = [
    ("L", False),   # Lecture  — goes to lecture rooms
    ("T", False),   # Tutorial — goes to lecture rooms (like a small lecture)
    ("P", True),    # Practical — goes to LAB rooms; consecutive pairing applied
]

logger = logging.getLogger("app.assembly")


# ─── Context & Result ─────────────────────────────────────────────────────────

@dataclass
class AssemblyContext:
    """
    Shared read-only context passed to every AssemblyStrategy.assemble() call.
    Built once in assemble_input(); shared across all bucket iterations by reference.
    """
    targets: dict[str, Any]                # {str(target_id): SchedulingTarget ORM row}
    requirements: list[Any]                # all TargetRequirement rows for the scenario
    courses: dict[str, Any]                # {str(course_id): Course ORM row}
    teaching_assignments: dict[str, Any]   # {str(course_id): TeachingAssignment ORM row} — for per-term room overrides
    dept_working_days: dict[str, list[str] | None]  # {str(dept_id): ["MON","TUE",...] | None}
    slots: dict[str, dict]                 # {slot_code: raw slot JSONB dict}
    rooms: list[RoomData]                  # all schedulable rooms — used for auto-batching
    reqs_by_bucket: dict[str, list] = field(default_factory=dict)
    # reqs_by_bucket: {str(bucket_id): [TargetRequirement, ...]} — pre-indexed by assemble_input
    slot_pattern_rules: dict[str, str | None] = field(default_factory=dict)
    # slot_pattern_rules: {str(course_id): pattern_code | None}
    #   pattern_code set  → force all offerings of this course to use that pattern family
    #   pattern_code None → solver auto-assigns a pattern (needs_pattern=True on SessionData)


@dataclass(frozen=True)
class AssemblyResult:
    """Output of one AssemblyStrategy.assemble() call for one OfferingBucket."""
    sessions: list[SessionData]
    groups: list[GroupData]
    parallel_groups: list[ParallelGroupData]


# ─── Strategy Protocol ────────────────────────────────────────────────────────

@runtime_checkable
class AssemblyStrategy(Protocol):
    """
    Protocol (structural ABC) for per-SelectionPolicy assembly strategies.

    Each strategy converts one OfferingBucket + AssemblyContext into
    (sessions, groups, parallel_groups) ready for SchedulerInput.

    Adding a new SelectionPolicy:
      1. Write a new XxxAssembler class implementing this protocol.
      2. Add one line to ASSEMBLY_REGISTRY in registry.py.
      No other file touched.
    """

    def assemble(self, bucket: Any, ctx: AssemblyContext) -> AssemblyResult:
        """
        Convert one OfferingBucket into solver-ready data.

        Args:
            bucket: OfferingBucket ORM object. bucket.offerings must be eager-loaded.
            ctx:    Shared assembly context (targets, courses, dept days, slots).

        Returns:
            AssemblyResult with sessions, groups, parallel_groups for this bucket.
        """
        ...


# ─── Shared Helpers ───────────────────────────────────────────────────────────

def _resolve_scope_key(bucket: Any, ctx: AssemblyContext) -> str:
    """
    Derive GroupData.scope_key from the SchedulingTarget that requires this bucket.

    CORRECT: scope is per-target (per-section). CSE-A scope = "target_<CSE-A-id>",
    CSE-B scope = "target_<CSE-B-id>". Non-overlap is enforced ONLY within one
    section's own bucket set.

    Previous bug: used department_id as scope → CSE-A and CSE-B blocked each other's slots.
    """
    reqs = ctx.reqs_by_bucket.get(str(bucket.id), [])
    if reqs:
        return f"target__{reqs[0].target_id}"
    # Orphan bucket: warn and fall back to department scope
    logger.warning("Bucket has no TargetRequirement rows", extra={"bucket_id": str(bucket.id)})
    return f"dept__{bucket.department_id}__{bucket.academic_term_id}"


def _resolve_target_size(bucket: Any, ctx: AssemblyContext, offering: Any = None) -> int:
    """Resolve student headcount for this offering/bucket.

    Resolution order (first non-zero wins):
      1. CourseOffering.min_capacity  — explicit per-offering override
                                        (lab split, combined lecture, seminar, etc.)
      2. SchedulingTarget.size        — batch-level headcount via TargetRequirement
      3. 0                            — no data; var_builder skips min_capacity check
    """
    # 1. Explicit per-offering override
    if offering is not None:
        oc = getattr(offering, "min_capacity", None)
        if oc:
            return int(oc)

    # 2. SchedulingTarget.size via TargetRequirement relationship
    reqs = ctx.reqs_by_bucket.get(str(bucket.id), [])
    for req in reqs:
        target = getattr(req, "target", None)
        if target:
            size = getattr(target, "size", None)
            if size:
                return int(size)

    return 0  # No headcount data — room_capacity pruning skipped for this bucket


def _resolve_slot_bundle(
    offering: Any,
    course: Any,
    slots: dict[str, dict],
    slot_pattern_rules: dict[str, str | None] | None = None,
) -> tuple[list[str] | None, bool]:
    """
    Resolve the slot token bundle and needs_pattern flag for an offering.

    Priority:
      1. SLOT_PATTERN_LOCK rule for this course_id (mode-agnostic):
           - pattern_code set  → (sorted token list, False)
           - pattern_code None → (None, True)   solver auto-assigns via SLOT_PATTERN_ASSIGN
      2. offering.slot_family (legacy FFCS fallback) → (sorted token list, False)
      3. No pattern → (None, False)

    Requires time_grids.slots JSONB entries to have a "family" key per token.
    Returns (slot_bundle, needs_pattern).
    """
    course_id_str = str(course.id) if hasattr(course, "id") else ""
    course_type = "lab" if getattr(course, "session_type", "") == "LAB" else "theory"

    # 1. SLOT_PATTERN_LOCK rule
    if slot_pattern_rules and course_id_str in slot_pattern_rules:
        pattern_code = slot_pattern_rules[course_id_str]
        if pattern_code is None:
            # Solver picks pattern automatically
            return None, True
        tokens = [
            code
            for code, slot_data in slots.items()
            if isinstance(slot_data, dict)
            and slot_data.get("family") == pattern_code
            and slot_data.get("type", "theory") == course_type
        ]
        return (sorted(tokens) if tokens else None), False

    # 2. Legacy fallback: offering.slot_family
    slot_family = getattr(offering, "slot_family", None)
    if not slot_family:
        return None, False

    tokens = [
        code
        for code, slot_data in slots.items()
        if isinstance(slot_data, dict)
        and slot_data.get("family") == slot_family
        and slot_data.get("type", "theory") == course_type
    ]
    return (sorted(tokens) if tokens else None), False


def _slot_period_index(slots: dict[str, dict]) -> dict[str, tuple[str, int]]:
    """Map slot_code → (day, 1-based period index ordered by start time within day)."""
    day_slots: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for code, data in slots.items():
        if not isinstance(data, dict):
            continue
        day = data.get("day", "MON")
        start = data.get("start", "08:00")
        day_slots[day].append((code, start))

    period_map: dict[str, tuple[str, int]] = {}
    for day, day_slot_list in day_slots.items():
        day_slot_list.sort(key=lambda x: x[1])
        for idx, (code, _) in enumerate(day_slot_list, start=1):
            period_map[code] = (day, idx)
    return period_map


def _order_slot_codes_by_period(
    codes: list[str],
    period_map: dict[str, tuple[str, int]],
) -> list[str]:
    """Chronological order — never use plain ``sorted(codes)`` (P10 sorts before P9)."""
    return sorted(codes, key=lambda c: period_map.get(c, ("", 0))[1])


def _discover_lab_pair_families(slots: dict[str, dict]) -> list[tuple[str, list[str]]]:
    """
    Valid 2-token lab families: same ``family`` label on one day, consecutive periods.

    Returns one ``(family, [token_a, token_b])`` entry per valid day-level pair.
    ``type=lab`` is optional — shared REC grids tag pairs with ``family`` only so
    theory sessions can still use the same physical slots.
    """
    by_family_day: dict[tuple[str, str], list[str]] = defaultdict(list)
    for code, data in slots.items():
        if not isinstance(data, dict):
            continue
        fam = data.get("family")
        if fam:
            day = str(data.get("day", "MON"))
            by_family_day[(fam, day)].append(code)

    period_map = _slot_period_index(slots)
    valid: list[tuple[str, list[str]]] = []
    for (fam, day), codes in sorted(by_family_day.items()):
        if len(codes) != 2:
            if codes:
                logger.warning(
                    "Lab family %s on %s ignored: expected 2 tokens, got %d",
                    fam,
                    day,
                    len(codes),
                )
            continue
        ordered = _order_slot_codes_by_period(codes, period_map)
        t0, t1 = ordered[0], ordered[1]
        d0, p0 = period_map.get(t0, ("", 0))
        d1, p1 = period_map.get(t1, ("", 0))
        if d0 != d1 or p1 != p0 + 1:
            logger.warning(
                "Lab family %s on %s ignored: tokens %s and %s are not consecutive",
                fam,
                day,
                t0,
                t1,
            )
            continue
        valid.append((fam, ordered))
    return valid


def _resolve_lab_pair_bundle(
    offering: Any,
    course: Any,
    slot_pattern_rules: dict[str, str | None] | None,
    lab_pair_families: list[tuple[str, list[str]]],
) -> tuple[list[str] | None, bool]:
    """
    Resolve a 2-token lab slot bundle for LTPC P pair sessions.

    Returns (slot_bundle, needs_pattern). When needs_pattern=True the solver picks
    among lab_pair_families via SLOT_PATTERN_ASSIGN (lab 2-token patterns only).
    """
    family_map = {fam: tokens for fam, tokens in lab_pair_families}
    course_id_str = str(course.id) if hasattr(course, "id") else ""

    if slot_pattern_rules and course_id_str in slot_pattern_rules:
        pattern_code = slot_pattern_rules[course_id_str]
        if pattern_code is None:
            return (None, True) if lab_pair_families else (None, False)
        if pattern_code in family_map:
            return family_map[pattern_code], False
        logger.warning(
            "SLOT_PATTERN_LOCK pattern %s is not a valid 2-token lab family",
            pattern_code,
        )

    slot_family = getattr(offering, "slot_family", None)
    if slot_family:
        matches = [tokens for fam, tokens in lab_pair_families if fam == slot_family]
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            return None, True

    if lab_pair_families:
        return None, True

    return None, False


def _resolve_fixed_slot(fixed_slot_id: int, slots: dict[str, dict]) -> str | None:
    """
    Resolve a pre-assigned slot code from offering.fixed_slot_id (1-based INT index).

    fixed_slot_id is a 1-based positional index into the time grid's sorted slot codes.
    Used for CHOOSE_COURSE electives where the admin pre-locks an offering to a slot.

    Returns the slot code, or None if the index is out of range.
    """
    sorted_codes = sorted(slots.keys())
    idx = fixed_slot_id - 1  # 1-based → 0-based
    if 0 <= idx < len(sorted_codes):
        return sorted_codes[idx]
    logger.warning(
        "fixed_slot_id out of range",
        extra={"fixed_slot_id": fixed_slot_id, "total_slots": len(sorted_codes)},
    )
    return None


def _is_merged(ta: Any) -> bool:
    """True when all sections share one combined room (is_merged_session=True, section_count > 1).

    When True, the assembler emits ONE SessionData with
    min_capacity = section_count × students_per_section instead of N separate small sessions.
    """
    return bool(getattr(ta, "is_merged_session", False)) and getattr(ta, "section_count", 1) > 1


def _has_multiple_components(course: Any) -> bool:
    """
    True if course.structure defines two or more active component types (L/T/P).

    Used to decide whether to use component-aware assembly (one group per
    component type) vs. flat assembly (single group, single session_type).

    A course with structure {"L": 3} only has one component → flat.
    A course with structure {"L": 3, "P": 2} has two → component-aware.
    """
    structure = getattr(course, "structure", None)
    if not structure or not isinstance(structure, dict):
        return False
    active = sum(1 for key in ("L", "T", "P") if int(structure.get(key, 0)) > 0)
    return active >= 2


def _component_room_assignment_soft(comp_key: str, course: Any, ta: Any | None) -> bool:
    """Per LTPC component: P uses lab pin softness; L/T use lecture pin softness."""
    if comp_key == "P":
        if ta and getattr(ta, "override_lab_room_ids", None):
            return bool(getattr(ta, "override_lab_room_ids_soft", True))
        return bool(getattr(course, "lab_preferred_room_ids_soft", True))
    if ta and getattr(ta, "override_room_ids", None):
        return bool(getattr(ta, "override_room_ids_soft", True))
    return bool(getattr(course, "preferred_room_ids_soft", True))


def _component_room_tags_soft(comp_key: str, course: Any) -> bool:
    if comp_key == "P":
        return bool(getattr(course, "lab_room_tags_soft", True))
    return bool(getattr(course, "room_tags_soft", False))


def _make_component_sessions(
    offering: Any,
    course: Any,
    group_id_prefix: str,
    target_size: int,
    dept_days: list[str] | None,
    department_id: str = "",
    room_tags: list[str] | None = None,
    target_room_ids: list[str] | None = None,       # lecture/theory pins (L, T components)
    target_lab_room_ids: list[str] | None = None,   # practical/lab pins (P component)
    target_room_tags: list[str] | None = None,       # tag fallback for L/T (when no pins)
    target_lab_room_tags: list[str] | None = None,   # tag fallback for P (when no pins)
    *,
    rooms: list[RoomData],
    ta: Any | None = None,
    is_merged: bool = False,
    study_semester: int = 0,
    max_room_capacity: int = 0,
    slots: dict[str, dict] | None = None,
    slot_pattern_rules: dict[str, str | None] | None = None,
) -> tuple[list[SessionData], dict[str, list[str]]]:
    """
    Expand course.structure {"L":3,"T":1,"P":2} into per-component sessions.

    Room pin priority:
      1. target_room_ids / target_lab_room_ids  (direct room pins)
      2. target_room_tags / target_lab_room_tags (tag fallback)

    Auto-batching mirrors flat lab assembly: when cohort size exceeds the largest
    eligible room (pinned pool when pins exist), emit __b1/__b2 session keys with
    min_capacity = batch_capacity.

    Session keys:  "<offering_id>__P1" or "<offering_id>__b1__P1", ...
    Group IDs:     "<group_id_prefix>__L", "<group_id_prefix>__T", "<group_id_prefix>__P"

    When the time grid defines valid 2-token lab families, P pairs collapse to one
    bundled session per pair (slot_bundle / needs_pattern) and REQUIRE_CONSECUTIVE is
    not used. Grids without lab families keep the legacy P1+P2 consecutive path.
    """
    structure = getattr(course, "structure", None) or {}
    faculty_id_str = str(offering.faculty_id) if offering.faculty_id else ""
    grid_slots = slots or {}
    lab_pair_families = _discover_lab_pair_families(grid_slots) if grid_slots else []

    sessions: list[SessionData] = []
    component_members: dict[str, list[str]] = {}

    for comp_key, is_lab in _LTPC_COMPONENTS:
        count = int(structure.get(comp_key, 0))
        if count <= 0:
            continue

        # Route the correct pin to the correct component type
        if is_lab:
            comp_allowed_room_ids = list(target_lab_room_ids) if target_lab_room_ids else None
            comp_required_tags = list(target_lab_room_tags) if target_lab_room_tags else list(room_tags or [])
        else:
            comp_allowed_room_ids = list(target_room_ids) if target_room_ids else None
            comp_required_tags = list(target_room_tags) if target_room_tags else list(room_tags or [])

        group_id = f"{group_id_prefix}__{comp_key}"
        member_keys: list[str] = []

        if is_merged:
            n_batches, batch_capacity = 1, target_size
        else:
            n_batches, batch_capacity = _resolve_auto_batch(
                target_size,
                is_lab,
                comp_required_tags,
                rooms,
                allowed_room_ids=comp_allowed_room_ids,
            )

        comp_room_tags_soft = _component_room_tags_soft(comp_key, course)
        comp_room_assignment_soft = _component_room_assignment_soft(comp_key, course, ta)
        use_lab_bundles = is_lab and comp_key == "P" and bool(lab_pair_families)
        pair_bundle: list[str] | None = None
        pair_needs_pattern = False
        if use_lab_bundles:
            pair_bundle, pair_needs_pattern = _resolve_lab_pair_bundle(
                offering,
                course,
                slot_pattern_rules,
                lab_pair_families,
            )

        for batch in range(1, n_batches + 1):
            b_sfx = f"__b{batch}" if n_batches > 1 else ""

            if use_lab_bundles:
                i = 1
                while i <= count:
                    key = f"{offering.id}{b_sfx}__{comp_key}{i}"
                    member_keys.append(key)

                    if i + 1 <= count and i % 2 == 1:
                        sessions.append(SessionData(
                            session_key=key,
                            offering_id=str(offering.id),
                            course_id=str(offering.course_id),
                            faculty_id=faculty_id_str,
                            department_id=department_id,
                            study_semester=study_semester,
                            is_lab=True,
                            session_type="LAB",
                            session_count=1,
                            group_ids=[group_id],
                            min_capacity=batch_capacity,
                            max_capacity=max_room_capacity,
                            consecutive_peer_key=None,
                            allowed_days=dept_days,
                            allowed_room_ids=comp_allowed_room_ids,
                            required_tags=list(comp_required_tags or []),
                            room_tags_soft=comp_room_tags_soft,
                            room_assignment_soft=comp_room_assignment_soft,
                            slot_bundle=pair_bundle,
                            needs_pattern=pair_needs_pattern,
                        ))
                        i += 2
                    else:
                        peer: str | None = None
                        if count > 1 and i + 1 <= count:
                            peer = f"{offering.id}{b_sfx}__{comp_key}{i + 1}"
                        sessions.append(SessionData(
                            session_key=key,
                            offering_id=str(offering.id),
                            course_id=str(offering.course_id),
                            faculty_id=faculty_id_str,
                            department_id=department_id,
                            study_semester=study_semester,
                            is_lab=True,
                            session_type="LAB",
                            session_count=count,
                            group_ids=[group_id],
                            min_capacity=batch_capacity,
                            max_capacity=max_room_capacity,
                            consecutive_peer_key=peer,
                            allowed_days=dept_days,
                            allowed_room_ids=comp_allowed_room_ids,
                            required_tags=list(comp_required_tags or []),
                            room_tags_soft=comp_room_tags_soft,
                            room_assignment_soft=comp_room_assignment_soft,
                        ))
                        i += 1
                continue

            for i in range(1, count + 1):
                key = f"{offering.id}{b_sfx}__{comp_key}{i}"
                member_keys.append(key)

                peer: str | None = None
                if is_lab and count > 1:
                    peer_idx = i + 1 if i % 2 == 1 else i - 1
                    peer = f"{offering.id}{b_sfx}__{comp_key}{peer_idx}"

                sessions.append(SessionData(
                    session_key=key,
                    offering_id=str(offering.id),
                    course_id=str(offering.course_id),
                    faculty_id=faculty_id_str,
                    department_id=department_id,
                    study_semester=study_semester,
                    is_lab=is_lab,
                    session_type="LAB" if is_lab else "THEORY",
                    session_count=count,
                    group_ids=[group_id],
                    min_capacity=batch_capacity,
                    max_capacity=max_room_capacity,
                    consecutive_peer_key=peer,
                    allowed_days=dept_days,
                    allowed_room_ids=comp_allowed_room_ids,
                    required_tags=list(comp_required_tags or []),
                    room_tags_soft=comp_room_tags_soft,
                    room_assignment_soft=comp_room_assignment_soft,
                ))

        component_members[comp_key] = member_keys

    return sessions, component_members


def _resolve_auto_batch(
    target_size: int,
    is_lab: bool,
    required_tags: list[str],
    rooms: list[RoomData],
    allowed_room_ids: list[str] | None = None,
) -> tuple[int, int]:
    """
    Auto-determine (n_batches, batch_capacity) from the eligible room pool.

    Filters rooms the same way var_builder Layer 1 does (type + required tags).
    When *allowed_room_ids* is set (direct room pins), only those rooms are
    considered for max capacity — so batching respects pinned lab lists.

    Same teacher takes all batches — TeacherNoDoubleBook naturally spreads them
    across different slots. No ParallelGroupData needed.

    Returns (1, target_size) when no batching is needed or no eligible rooms exist.
    """
    if target_size <= 0:
        return 1, target_size

    pin_set = set(allowed_room_ids) if allowed_room_ids else None
    if pin_set is not None:
        # Pinned rooms define the batch pool — tag matching may be soft at solve time.
        eligible = [
            r for r in rooms
            if r.room_id in pin_set
            and (r.room_type == "LAB" if is_lab else r.room_type != "LAB")
        ]
    else:
        eligible = [
            r for r in rooms
            if (r.room_type == "LAB" if is_lab else r.room_type != "LAB")
            and all(t in set(r.tags) for t in required_tags)
        ]

    if not eligible:
        return 1, target_size  # no eligible rooms — var_builder will report infeasible

    max_capacity = max(r.capacity for r in eligible)
    if max_capacity <= 0 or target_size <= max_capacity:
        return 1, target_size  # fits in the largest room, no batching needed

    return math.ceil(target_size / max_capacity), max_capacity


def _lab_peer_key(offering: Any, session_index: int) -> str | None:
    """
    Generate consecutive_peer_key for lab session pairing.

    Lab sessions come in pairs that must be in adjacent slots (require_consecutive).
    Odd sessions are paired with their even successor.
      s1 ↔ s2, s3 ↔ s4, etc.
    """
    if session_index % 2 == 1:
        return f"{offering.id}__s{session_index + 1}"
    return f"{offering.id}__s{session_index - 1}"
