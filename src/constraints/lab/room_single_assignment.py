"""Lab room single-assignment exclusivity constraints."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, DefaultDict, List, Mapping, Optional, Sequence, Tuple

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_lab_session_variables, register_objective_penalty
from ...utils.time_utils import DayNormalizer


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

        room_slot_buckets: DefaultDict[Tuple[str, str, str], List[Any]] = defaultdict(list)
        course_slot_buckets: DefaultDict[Tuple[str, str, str], List[Any]] = defaultdict(list)
        # Store course_id for each variable to check co-scheduling rules
        room_slot_details: DefaultDict[Tuple[str, str, str], List[Tuple[str, Any]]] = defaultdict(list)

        registry = getattr(getattr(context.data, "raw", None), "room_registry", {}) or {}

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
                context.model.AddAtMostOne(variables)
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
                context.model.AddAtMostOne(code_active_vars)

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
                    # Optimization: skip helper bool when only one large var
                    if len(large_vars) == 1:
                        has_large = large_vars[0]
                    else:
                        has_large = context.model.NewBoolVar(f"has_large_{key}_{code}")
                        context.model.Add(large_sum >= has_large)
                        context.model.Add(large_sum <= len(large_vars) * has_large)
                    # If a large batch is used, it must be the only one in the room slot.
                    context.model.Add(all_sum <= 2 - has_large)

                else:
                    context.model.Add(all_sum <= 2)

                if medium_vars:
                    # Optimization: skip helper bool when only one medium var
                    if len(medium_vars) == 1:
                        has_medium = medium_vars[0]
                    else:
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
            context.model.AddAtMostOne(variables)
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
