"""Lab room single-assignment exclusivity constraints.

This module also contains the co-scheduling rules for very large "core lab" rooms
(e.g. 300+ capacity DSA classrooms) and an optional bundle-locking rule that
keeps any co-scheduled set of instances together across all required sessions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import math
from typing import Any, DefaultDict, Dict, List, Mapping, Optional, Sequence, Tuple

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_lab_session_variables, register_objective_penalty
from ...utils.time_utils import DayNormalizer
from .core_lab import CoreLabMappingConstraint


@dataclass
class RoomAssignmentStats:
    room_slot_constraints: int = 0
    course_slot_constraints: int = 0
    unique_room_slots: int = 0
    unique_course_slots: int = 0
    conflicting_room_slots: int = 0
    conflicting_course_slots: int = 0
    room_conflict_examples: List[Tuple[str, str, str]] = field(default_factory=list)
    course_conflict_examples: List[Tuple[str, str, str]] = field(default_factory=list)

    def to_details(self) -> Mapping[str, object]:
        return {
            "room_constraints": self.room_slot_constraints,
            "course_constraints": self.course_slot_constraints,
            "room_slots": self.unique_room_slots,
            "course_slots": self.unique_course_slots,
            "room_conflicts": self.conflicting_room_slots,
            "course_conflicts": self.conflicting_course_slots,
            "room_conflict_examples": tuple(self.room_conflict_examples),
            "course_conflict_examples": tuple(self.course_conflict_examples),
        }


class LabRoomSingleAssignmentConstraint(Constraint):
    """Prevent double-booking lab rooms and multi-room sessions per course."""

    MAX_EXAMPLE_SLOTS = 5

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        logger = context.child_logger("room_single_assignment")
        stats = RoomAssignmentStats()

        underfill_penalty_weight = int(self.params.get("medium_underfill_penalty_weight", 25))
        mixed_medium_penalty_weight = int(self.params.get("medium_mixing_penalty_weight", 10))

        lab_block = context.variables.lab
        if not lab_block.assignments:
            logger.info("No lab assignments available; skipping room single-assignment constraint")
            return self._build_result(stats, ConstraintStatus.SKIPPED)

        # Apply stable co-scheduling bundles for 300+ capacity core-lab rooms.
        # This is especially relevant for DSA classrooms (355 capacity) where we
        # want flexible packing (e.g. 5x70, 2x140+70, 3x70+140) *and* ensure that
        # any co-scheduled set remains together for all 8 hours (4 sessions).
        self._apply_core_large_room_bundle_lock(context)

        room_slot_buckets: DefaultDict[Tuple[str, str, str], List[Any]] = defaultdict(list)
        course_slot_buckets: DefaultDict[Tuple[str, str, str], List[Any]] = defaultdict(list)
        # Store course_id for each variable to check co-scheduling rules
        room_slot_details: DefaultDict[Tuple[str, str, str], List[Tuple[str, Any]]] = defaultdict(list)

        registry = getattr(getattr(context.data, "raw", None), "room_registry", {}) or {}
        dsa_mix_codes = {"CS23231", "CB23231"}
        dsa_mixing_room_ids = self._resolve_dsa_mixing_room_ids(context, dsa_mix_codes)

        for _teacher_id, course_id, day_index, session_name, room_id, variable in iter_lab_session_variables(context):
            day_label = self._resolve_day_label(context, lab_block.day_patterns, course_id, day_index)
            room_slot_key = (day_label, session_name, room_id)
            course_slot_key = (course_id, day_label, session_name)
            room_slot_buckets[room_slot_key].append(variable)
            room_slot_details[room_slot_key].append((course_id, variable))
            course_slot_buckets[course_slot_key].append(variable)

        stats.unique_room_slots = len(room_slot_buckets)
        stats.unique_course_slots = len(course_slot_buckets)

        for key, variables in room_slot_buckets.items():
            if len(variables) <= 1:
                continue
            
            # Check room capacity to determine limit
            room_id = key[2]
            room_info = registry.get(str(room_id), {})
            capacity = self._extract_capacity(room_info)
            
            # Unknown / small rooms: strict single assignment
            if not capacity or capacity < 140:
                context.model.Add(sum(variables) <= 1)
                stats.room_slot_constraints += 1
                stats.conflicting_room_slots += 1
                if len(stats.room_conflict_examples) < self.MAX_EXAMPLE_SLOTS:
                    stats.room_conflict_examples.append(key)
                continue

            # Very large rooms (300+ capacity, e.g. DSA 355): allow packing by capacity.
            # - Allow up to 5 concurrent instances (global)
            # - Enforce a weighted capacity guard (global): sum(student_count * var) <= capacity
            # - Disallow mixing different course codes within the same room+slot,
            #   EXCEPT that CS23231 and CB23231 may co-schedule together.
            if capacity >= 300:
                details = room_slot_details[key]
                course_vars: DefaultDict[str, List[Tuple[str, Any, int]]] = defaultdict(list)
                course_codes = set()
                for course_id, var in details:
                    req = lab_block.requirements.get(course_id)
                    if req:
                        code = (req.course_code or "").strip().upper()
                        if not code:
                            continue
                        course_vars[code].append((course_id, var, int(req.student_count or 0)))
                        course_codes.add(code)

                # If we cannot resolve codes, fall back to strict behaviour.
                if not course_codes:
                    context.model.Add(sum(variables) <= 1)
                    stats.room_slot_constraints += 1
                    stats.conflicting_room_slots += 1
                    if len(stats.room_conflict_examples) < self.MAX_EXAMPLE_SLOTS:
                        stats.room_conflict_examples.append(key)
                    continue

                # Control course-code mixing in the slot.
                code_active_vars = []
                for code in sorted(course_codes):
                    is_active = context.model.NewBoolVar(f"active_{key}_{code}")
                    code_active_vars.append(is_active)
                    all_vars_for_code = [v for _, v, _ in course_vars[code]]
                    context.model.Add(sum(all_vars_for_code) <= 5 * is_active)
                    context.model.Add(sum(all_vars_for_code) >= is_active)

                if len(code_active_vars) > 1:
                    # Only CS23231+CB23231 are allowed to mix. Any other set of
                    # course codes must remain exclusive.
                    allow_dsa_mix_here = str(room_id) in dsa_mixing_room_ids
                    if allow_dsa_mix_here and course_codes.issubset(dsa_mix_codes):
                        context.model.Add(sum(code_active_vars) <= 2)
                    else:
                        context.model.Add(sum(code_active_vars) <= 1)

                # Global count + capacity guards across all concurrent instances in the slot.
                all_vars: List[Any] = []
                all_counts: List[int] = []
                for items in course_vars.values():
                    for _, var, cnt in items:
                        all_vars.append(var)
                        safe_cnt = int(cnt) if int(cnt) > 0 else 70
                        all_counts.append(safe_cnt)

                context.model.Add(sum(all_vars) <= 5)
                context.model.Add(sum(w * v for w, v in zip(all_counts, all_vars)) <= capacity)

                stats.room_slot_constraints += 1
                stats.conflicting_room_slots += 1
                if len(stats.room_conflict_examples) < self.MAX_EXAMPLE_SLOTS:
                    stats.room_conflict_examples.append(key)
                continue

            # Large rooms (140+ capacity): Allow co-scheduling with strict rules
            # Rule 1: If a 140-student course is present, it must be the ONLY course
            # Rule 2: If 70-student courses are present, they must be the SAME course code (max 2)
            
            details = room_slot_details[key]
            course_vars = defaultdict(list)
            course_codes = set()
            
            for course_id, var in details:
                req = lab_block.requirements.get(course_id)
                if req:
                    course_code = req.course_code
                    course_vars[course_code].append((course_id, var, req.student_count or 0))
                    course_codes.add(course_code)
            
            # Always create activity selectors per course code to (a) enforce mutual exclusion
            # across codes, and (b) support utilization rules.
            code_active_vars = []
            for code in sorted(course_codes):
                is_active = context.model.NewBoolVar(f"active_{key}_{code}")
                code_active_vars.append(is_active)

                all_vars_for_code = [v for _, v, _ in course_vars[code]]
                context.model.Add(sum(all_vars_for_code) <= 2 * is_active)
                context.model.Add(sum(all_vars_for_code) >= is_active)

            if len(code_active_vars) > 1:
                context.model.Add(sum(code_active_vars) <= 1)

            # Apply capacity/utilization rules per course code.
            # - Large batches (>=100) must be alone in the 140 room.
            # - Medium batches (60-75) must be co-scheduled as a pair (exactly 2)
            #   to avoid under-utilisation of 140-capacity rooms.
            for code, items in course_vars.items():
                all_vars_for_code = [v for _, v, _ in items]
                large_vars = [v for _, v, count in items if (count or 0) >= 100]
                medium_vars = [v for _, v, count in items if 60 <= (count or 0) <= 75]
                other_vars = [v for _, v, count in items if v not in set(large_vars) and v not in set(medium_vars)]

                all_sum = sum(all_vars_for_code)
                large_sum = sum(large_vars) if large_vars else 0
                medium_sum = sum(medium_vars) if medium_vars else 0
                other_sum = sum(other_vars) if other_vars else 0

                if large_vars:
                    has_large = context.model.NewBoolVar(f"has_large_{key}_{code}")
                    context.model.Add(large_sum >= has_large)
                    context.model.Add(large_sum <= len(large_vars) * has_large)
                    # If a large batch is used, it must be the only one in the room slot.
                    context.model.Add(all_sum <= 2 - has_large)
                else:
                    context.model.Add(all_sum <= 2)

                if medium_vars:
                    has_medium = context.model.NewBoolVar(f"has_medium_{key}_{code}")
                    context.model.Add(medium_sum >= has_medium)
                    context.model.Add(medium_sum <= len(medium_vars) * has_medium)

                    # Soft preference: if medium is used in a 140 room, prefer co-scheduling as a pair.
                    # We model a shortfall term: shortfall = (2 - medium_sum) when has_medium else 0.
                    if underfill_penalty_weight > 0:
                        medium_sum_var = context.model.NewIntVar(
                            0,
                            min(2, len(medium_vars)),
                            f"medium_sum_{key}_{code}",
                        )
                        context.model.Add(medium_sum_var == medium_sum)

                        medium_shortfall = context.model.NewIntVar(0, 2, f"medium_shortfall_{key}_{code}")
                        context.model.Add(medium_shortfall <= 2 * has_medium)
                        # Big-M linearisation around has_medium (M=2)
                        context.model.Add(medium_shortfall >= 2 - medium_sum_var - 2 * (1 - has_medium))
                        context.model.Add(medium_shortfall <= 2 - medium_sum_var + 2 * (1 - has_medium))

                        register_objective_penalty(
                            context,
                            medium_shortfall,
                            underfill_penalty_weight,
                            tag=f"lab_room_utilization:medium_underfill:{code}",
                        )

                    # Soft preference: avoid mixing medium batches with other batch sizes for the same
                    # course code in a 140 room slot.
                    if mixed_medium_penalty_weight > 0 and other_vars:
                        other_sum_var = context.model.NewIntVar(0, 2, f"other_sum_{key}_{code}")
                        context.model.Add(other_sum_var == other_sum)

                        medium_mix = context.model.NewIntVar(0, 2, f"medium_mix_{key}_{code}")
                        context.model.Add(medium_mix <= 2 * has_medium)
                        context.model.Add(medium_mix >= other_sum_var - 2 * (1 - has_medium))
                        context.model.Add(medium_mix <= other_sum_var + 2 * (1 - has_medium))

                        register_objective_penalty(
                            context,
                            medium_mix,
                            mixed_medium_penalty_weight,
                            tag=f"lab_room_utilization:medium_mixing:{code}",
                        )

        for key, variables in course_slot_buckets.items():
            if len(variables) <= 1:
                continue
            context.model.Add(sum(variables) <= 1)
            stats.course_slot_constraints += 1
            stats.conflicting_course_slots += 1
            if len(stats.course_conflict_examples) < self.MAX_EXAMPLE_SLOTS:
                stats.course_conflict_examples.append(key)

        total_constraints = stats.room_slot_constraints + stats.course_slot_constraints
        status = ConstraintStatus.APPLIED if total_constraints else ConstraintStatus.SKIPPED

        logger.info(
            "Lab room single-assignment scanned %d room slots (%d conflicts) and %d course slots (%d conflicts)",
            stats.unique_room_slots,
            stats.conflicting_room_slots,
            stats.unique_course_slots,
            stats.conflicting_course_slots,
        )
        if stats.room_conflict_examples:
            logger.debug("Room conflict samples: %s", stats.room_conflict_examples)
        if stats.course_conflict_examples:
            logger.debug("Course conflict samples: %s", stats.course_conflict_examples)

        return self._build_result(stats, status)

    def _apply_core_large_room_bundle_lock(self, context: ConstraintContext) -> None:
        """Lock co-scheduled sets together across all sessions for 300+ core-lab rooms.

        For core lab courses mapped to very large rooms (>=300), we allow multiple
        instances to share a room+slot based on capacity. When they do, the user
        expects them to behave like a stable "bundle": if instances A/B/C/D/E run
        together in one lab slot, they must run together for all required sessions
        (e.g. 8 hours => 4 lab sessions).

        Implementation strategy:
        - Detect course codes in `core_lab_mapping_df` whose mapped room IDs include
          300+ capacity rooms.
        - For each (course_code, day_pattern, required_sessions) cohort, create a
          small number of bundles (ceil(n/5)) and force each instance to choose
          exactly one bundle.
        - Bundle schedule variables decide the (day, session, room) slots.
        - Each instance's assignment variables are forced to match its bundle
          schedule, ensuring stable grouping.
        """

        lab_block = context.variables.lab
        registry = getattr(getattr(context.data, "raw", None), "room_registry", {}) or {}

        # Identify large rooms (capacity >= 300)
        large_room_ids = set()
        for rid, info in registry.items():
            cap = self._extract_capacity(info or {})
            if cap is not None and cap >= 300:
                large_room_ids.add(str(rid))

        if not large_room_ids:
            return

        core_df = getattr(context.data.raw, "core_lab_mapping_df", None)
        rooms_df = getattr(context.data.raw, "rooms_df", None)
        if core_df is None or getattr(core_df, "empty", True) or rooms_df is None:
            return

        # Build a mapping: course_code -> allowed_large_room_ids (subset of mapped rooms).
        lookup = CoreLabMappingConstraint._build_room_lookup(rooms_df)
        mapped_large_rooms: Dict[str, Tuple[str, ...]] = {}
        extractor = CoreLabMappingConstraint(
            metadata=ConstraintMetadata(
                id="_tmp_core_room_bundle_lock",
                name="_tmp_core_room_bundle_lock",
                category="lab",
                priority=0,
            )
        )

        for _, row in core_df.iterrows():
            raw_code = row.get("course_code")
            course_code = str(raw_code or "").strip().upper()
            if not course_code:
                continue
            resolved_room_ids = extractor._extract_room_ids(row, lookup)
            allowed = tuple(sorted(set(resolved_room_ids) & large_room_ids))
            if allowed:
                mapped_large_rooms[course_code] = allowed

        if not mapped_large_rooms:
            return

        def _bundle_family_code(course_code: str) -> str:
            code = str(course_code or "").strip().upper()
            if code in {"CS23231", "CB23231"}:
                return "CS23231_CB23231"
            return code

        # Group instances by (bundle_code, required_sessions, allowed_rooms).
        # NOTE: We intentionally do NOT split by department day-pattern.
        # Different departments have different local day-index orders, but they can
        # still co-schedule on the same normalized day label (e.g., "thur").
        # To enforce stable co-scheduled sets globally, we create bundle schedules
        # over normalized day labels and map each instance's local day_index to
        # those labels.
        grouped: Dict[Tuple[str, int, Tuple[str, ...]], List[str]] = defaultdict(list)
        for course_id, req in lab_block.requirements.items():
            code = str(getattr(req, "course_code", "") or "").strip().upper()
            if not code or code not in mapped_large_rooms:
                continue
            bundle_code = _bundle_family_code(code)
            practical_hours = int(getattr(req, "practical_hours", 0) or 0)
            if practical_hours < 8:
                continue
            required_sessions = int(getattr(req, "required_sessions", 0) or 0)
            if required_sessions <= 0:
                continue
            allowed_rooms = mapped_large_rooms[code]
            grouped[(bundle_code, required_sessions, allowed_rooms)].append(course_id)

    def _resolve_dsa_mixing_room_ids(self, context: ConstraintContext, dsa_codes: set[str]) -> set[str]:
        """Return room_ids where CS23231/CB23231 mixing is permitted.

        We intentionally keep this allowlist narrow: only rooms that appear in the
        core-lab mapping for the DSA codes.
        """

        core_df = getattr(context.data.raw, "core_lab_mapping_df", None)
        rooms_df = getattr(context.data.raw, "rooms_df", None)
        if core_df is None or getattr(core_df, "empty", True) or rooms_df is None:
            return set()

        lookup = CoreLabMappingConstraint._build_room_lookup(rooms_df)
        extractor = CoreLabMappingConstraint(
            metadata=ConstraintMetadata(
                id="_tmp_dsa_mixing_rooms",
                name="_tmp_dsa_mixing_rooms",
                category="lab",
                priority=0,
            )
        )

        allowed: set[str] = set()
        for _, row in core_df.iterrows():
            raw_code = row.get("course_code")
            course_code = str(raw_code or "").strip().upper()
            if course_code not in dsa_codes:
                continue
            resolved_room_ids = extractor._extract_room_ids(row, lookup)
            for rid in resolved_room_ids:
                allowed.add(str(rid))
        return allowed

        model = context.model
        session_names = tuple(lab_block.lab_session_names)

        for (code, required_sessions, allowed_rooms), instance_ids in grouped.items():
            if len(instance_ids) <= 1:
                continue

            # Allow many potential bundles so the solver can choose how many stable
            # groups it needs (based on teacher availability and other constraints),
            # while capacity/count constraints ensure no bundle can grow beyond what
            # the room can support.
            bundle_count = len(instance_ids)

            # membership[i][k]
            membership: Dict[Tuple[str, int], Any] = {}
            for instance_id in instance_ids:
                for k in range(bundle_count):
                    membership[(instance_id, k)] = model.NewBoolVar(f"bundle_{code}_{instance_id}_{k}")
                model.Add(sum(membership[(instance_id, k)] for k in range(bundle_count)) == 1)

            # bundle_used[k]
            bundle_used: Dict[int, Any] = {}
            for k in range(bundle_count):
                used = model.NewBoolVar(f"bundle_used_{code}_{k}")
                bundle_used[k] = used
                model.Add(sum(membership[(iid, k)] for iid in instance_ids) >= used)
                model.Add(sum(membership[(iid, k)] for iid in instance_ids) <= len(instance_ids) * used)

            # Compute the union of normalized day labels available across all instances.
            # We'll schedule bundles using these labels, and map each instance's local
            # day_index to the corresponding label.
            instance_day_index: Dict[str, Dict[str, int]] = {}
            all_day_labels: set[str] = set()
            for instance_id in instance_ids:
                raw_pattern = tuple(lab_block.day_patterns.get(instance_id, ()))
                mapping_day: Dict[str, int] = {}
                for idx, raw_label in enumerate(raw_pattern):
                    label = DayNormalizer.normalize_day_name(raw_label)
                    if not label:
                        continue
                    mapping_day[label] = idx
                    all_day_labels.add(label)
                instance_day_index[instance_id] = mapping_day

            day_labels = tuple(sorted(all_day_labels))
            if not day_labels:
                continue

            # bundle_schedule[k, day_label, session, room]
            bundle_schedule: Dict[Tuple[int, str, str, str], Any] = {}
            for k in range(bundle_count):
                for day_label in day_labels:
                    for session_name in session_names:
                        for room_id in allowed_rooms:
                            bundle_schedule[(k, day_label, session_name, room_id)] = model.NewBoolVar(
                                f"bundle_sched_{code}_{k}_{day_label}_{session_name}_{room_id}"
                            )

            # Prevent multiple bundles sharing the exact same room+slot.
            for day_label in day_labels:
                for session_name in session_names:
                    for room_id in allowed_rooms:
                        model.Add(
                            sum(bundle_schedule[(k, day_label, session_name, room_id)] for k in range(bundle_count)) <= 1
                        )

            # Each used bundle must schedule exactly `required_sessions` sessions per week.
            for k in range(bundle_count):
                schedule_vars = [
                    bundle_schedule[(k, day_label, session_name, room_id)]
                    for day_label in day_labels
                    for session_name in session_names
                    for room_id in allowed_rooms
                ]
                model.Add(sum(schedule_vars) == required_sessions * bundle_used[k])

            # Link instance assignment vars to its chosen bundle schedule.
            # For each instance and each (day, session, room), assignment var equals the schedule
            # variable of its selected bundle.
            for instance_id in instance_ids:
                teacher_id = getattr(lab_block.requirements.get(instance_id), "teacher_id", None)
                if teacher_id is None:
                    continue
                # NOTE: keys inside `lab_block.assignments` and nested maps are not
                # guaranteed to be strings (some datasets use ints). Do not coerce
                # types here; instead, try common representations.
                teacher_map = None
                for tid_key in (teacher_id, str(teacher_id)):
                    teacher_map = lab_block.assignments.get(tid_key)
                    if teacher_map is not None:
                        break

                if not teacher_map:
                    continue

                day_map = None
                for cid_key in (instance_id, str(instance_id)):
                    day_map = teacher_map.get(cid_key)
                    if day_map is not None:
                        break
                if not day_map:
                    continue

                mapping_day = instance_day_index.get(instance_id, {})

                # If this instance joins a bundle, the bundle schedule must only
                # use day labels present in the instance's day pattern.
                for k in range(bundle_count):
                    m = membership[(instance_id, k)]
                    for day_label in day_labels:
                        if day_label in mapping_day:
                            continue
                        for session_name in session_names:
                            for room_id in allowed_rooms:
                                y = bundle_schedule[(k, day_label, session_name, room_id)]
                                model.Add(y <= 1 - m)

                for day_label in day_labels:
                    day_idx = mapping_day.get(day_label)
                    if day_idx is None:
                        continue

                    session_map = day_map.get(day_idx)
                    if not session_map:
                        continue
                    for session_name in session_names:
                        room_map = session_map.get(session_name)
                        if not room_map:
                            continue
                        for room_id in allowed_rooms:
                            x = room_map.get(str(room_id))
                            if x is None:
                                continue
                            z_vars = []
                            for k in range(bundle_count):
                                z = model.NewBoolVar(
                                    f"z_{code}_{instance_id}_{k}_{day_label}_{session_name}_{room_id}"
                                )
                                m = membership[(instance_id, k)]
                                y = bundle_schedule[(k, day_label, session_name, room_id)]
                                model.Add(z <= m)
                                model.Add(z <= y)
                                model.Add(z >= m + y - 1)
                                z_vars.append(z)
                            model.Add(x == sum(z_vars))

    def _resolve_day_label(
        self,
        context: ConstraintContext,
        day_patterns: Mapping[str, Sequence[str]],
        course_id: str,
        day_index: int,
    ) -> str:
        pattern = day_patterns.get(course_id)
        label: Optional[str] = None
        if pattern and 0 <= day_index < len(pattern):
            label = pattern[day_index]
        else:
            working_days = getattr(context.data.raw.time, "working_days", ())
            if 0 <= day_index < len(working_days):
                label = working_days[day_index]
        normalized = DayNormalizer.normalize_day_name(label or "")
        if normalized:
            return normalized
        context.logger.warning(
            "Unable to normalize day label '%s' for course %s (day_index=%d)",
            label,
            course_id,
            day_index,
        )
        return f"day_{day_index}"

    def _build_result(
        self,
        stats: RoomAssignmentStats,
        status: str,
    ) -> ConstraintApplicationResult:
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details=stats.to_details(),
        )

    @staticmethod
    def _extract_capacity(room_info: Mapping[str, object]) -> Optional[int]:
        for key in ("room_max_cap", "room_capacity", "capacity", "max_cap"):
            value = room_info.get(key)
            if value in (None, ""):
                continue
            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue
        return None


def build_lab_room_single_assignment_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> LabRoomSingleAssignmentConstraint:
    return LabRoomSingleAssignmentConstraint(metadata=metadata, params=params)


__all__ = [
    "LabRoomSingleAssignmentConstraint",
    "build_lab_room_single_assignment_constraint",
]
