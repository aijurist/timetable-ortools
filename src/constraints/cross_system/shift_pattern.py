"""Cross-system shift pattern alignment for lab and theory schedules."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    iter_course_timeslot_variables,
    iter_lab_session_variables,
    register_objective_penalty,
    resolve_day_pattern,
)

ShiftCounts = Tuple[int, ...]


def _slug(text: str) -> str:
    cleaned = [ch.lower() if ch.isalnum() else "_" for ch in text]
    result = "".join(cleaned).strip("_")
    return result or "dept"


def _skip(metadata: ConstraintMetadata, reason: str) -> ConstraintApplicationResult:
    return ConstraintApplicationResult(
        name=metadata.name,
        domain=metadata.category,
        priority=metadata.priority,
        enabled=True,
        status=ConstraintStatus.SKIPPED,
        details={"reason": reason},
    )


@dataclass(frozen=True)
class ShiftPatternSettings:
    shift_ids: Tuple[str, ...]
    allowed_patterns: Tuple[ShiftCounts, ...]
    lab_session_map: Mapping[str, Tuple[str, ...]]
    theory_slot_map: Mapping[int, Tuple[str, ...]]
    strict_ratios: bool = False

    @staticmethod
    def from_context(context: ConstraintContext, params: Optional[Mapping[str, object]]) -> "ShiftPatternSettings":
        departments = getattr(context.data.raw, "departments", None)
        shift_defs = getattr(departments, "shift_definitions", {}) if departments else {}
        requested = tuple(str(token).strip() for token in (params or {}).get("shift_templates", ()))
        shift_ids: list[str] = []
        session_map: MutableMapping[str, set[str]] = defaultdict(set)
        slot_map: MutableMapping[int, set[str]] = defaultdict(set)
        def _resolve(identifier: str):
            if identifier in shift_defs:
                return shift_defs[identifier]
            lowered = identifier.lower()
            return shift_defs.get(lowered)
        tokens = requested or tuple(shift_defs.keys())
        for token in tokens:
            definition = _resolve(token)
            if not definition:
                continue
            shift_id = definition.identifier
            if shift_id in shift_ids:
                continue
            shift_ids.append(shift_id)
            for session_name in definition.lab_sessions:
                session_map[session_name].add(shift_id)
            for slot_index in definition.theory_slots:
                slot_map[int(slot_index)].add(shift_id)
        pattern_source: Iterable[Sequence[int]] = (params or {}).get("allowed_patterns", ())
        if not tuple(pattern_source) and departments is not None:
            pattern_source = getattr(departments, "valid_shift_patterns", ())
        allowed_patterns: list[ShiftCounts] = []
        for entry in pattern_source:
            try:
                counts = tuple(int(value) for value in entry)
            except (TypeError, ValueError):
                continue
            if not counts:
                continue
            if len(counts) < len(shift_ids):
                continue
            allowed_patterns.append(counts)
        if not allowed_patterns and departments is not None:
            payload = getattr(departments, "valid_shift_patterns", ()) or ()
            for entry in payload:
                counts = tuple(int(value) for value in entry)
                if counts and len(counts) >= len(shift_ids):
                    allowed_patterns.append(counts)
        
        strict_ratios = bool((params or {}).get("strict_ratios", False))
        
        return ShiftPatternSettings(
            shift_ids=tuple(shift_ids),
            allowed_patterns=tuple(allowed_patterns),
            lab_session_map={name: tuple(sorted(ids)) for name, ids in session_map.items()},
            theory_slot_map={slot: tuple(sorted(ids)) for slot, ids in slot_map.items()},
            strict_ratios=strict_ratios,
        )


class ShiftPatternConstraint(Constraint):
    """Encourage departments to follow configured shift ratios across lab and theory."""

    def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
        super().__init__(metadata, params=params)
        base_weight = max(1, int(round(max(self.metadata.weight, 0.1) * 10)))
        override = None if not params else params.get("penalty_weight")
        if override is not None:
            try:
                base_weight = max(1, int(override))
            except (TypeError, ValueError):
                base_weight = max(1, base_weight)
        self._penalty_weight = base_weight
        
        self._ratio_penalty_weight = base_weight
        if params:
            ratio_override = params.get("ratio_penalty_weight")
            if ratio_override is not None:
                try:
                    self._ratio_penalty_weight = max(1, int(ratio_override))
                except (TypeError, ValueError):
                    pass

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        settings = ShiftPatternSettings.from_context(context, self.params)
        if len(settings.shift_ids) < 2:
            return _skip(self.metadata, "at least two shift templates are required")
        activity_departments = _collect_departments(context)
        if not activity_departments:
            return _skip(self.metadata, "no departmental activity discovered")
        dept_day_matrix = _initialise_department_days(context, activity_departments, settings.shift_ids)
        if not dept_day_matrix:
            return _skip(self.metadata, "failed to build day matrices for departments")
        soft_link_penalties = 0
        soft_link_penalties += self._link_lab_assignments(context, dept_day_matrix, settings)
        soft_link_penalties += self._link_theory_assignments(context, dept_day_matrix, settings)
        penalty_terms = self._register_ratio_penalties(context, dept_day_matrix, settings)
        status = ConstraintStatus.APPLIED if (soft_link_penalties or penalty_terms) else ConstraintStatus.SKIPPED
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details={
                "departments": len(dept_day_matrix),
                "shift_ids": settings.shift_ids,
                "soft_link_penalties": soft_link_penalties,
                "penalty_terms": penalty_terms,
            },
        )

    def _link_lab_assignments(
        self,
        context: ConstraintContext,
        dept_matrix: Mapping[str, Tuple[Mapping[str, cp_model.IntVar], ...]],
        settings: ShiftPatternSettings,
    ) -> int:
        lab_block = context.variables.lab
        requirement_map = getattr(lab_block, "requirements", {}) or {}
        penalties = 0
        for _, course_id, day_idx, session_name, _room_id, var in iter_lab_session_variables(context):
            requirement = requirement_map.get(course_id)
            if not requirement:
                continue
            dept = requirement.department
            day_lits = dept_matrix.get(dept)
            if not day_lits:
                continue
            if day_idx >= len(day_lits):
                continue
            allowed_shifts = settings.lab_session_map.get(session_name)
            if not allowed_shifts:
                continue
            disallowed = [shift_id for shift_id in settings.shift_ids if shift_id not in allowed_shifts]
            for shift_id in disallowed:
                literal = day_lits[day_idx].get(shift_id)
                if literal is None:
                    continue
                violation = context.model.NewBoolVar(
                    f"shift_pattern_lab_violation_{_slug(dept)}_d{day_idx}_{_slug(session_name)}_{_slug(shift_id)}"
                )
                context.model.Add(violation <= var)
                context.model.Add(violation <= literal)
                context.model.Add(var + literal - violation <= 1)
                register_objective_penalty(context, violation, self._penalty_weight, tag=f"shift_pattern:{dept}")
                penalties += 1
        return penalties

    def _link_theory_assignments(
        self,
        context: ConstraintContext,
        dept_matrix: Mapping[str, Tuple[Mapping[str, cp_model.IntVar], ...]],
        settings: ShiftPatternSettings,
    ) -> int:
        theory_block = context.variables.theory
        requirements = getattr(theory_block, "course_requirements", {}) or {}
        penalties = 0
        for _, course_id, day_idx, slot_idx, var in iter_course_timeslot_variables(context):
            requirement = requirements.get(course_id)
            if not requirement:
                continue
            dept = requirement.department
            day_lits = dept_matrix.get(dept)
            if not day_lits:
                continue
            if day_idx >= len(day_lits):
                continue
            allowed_shifts = settings.theory_slot_map.get(slot_idx)
            if not allowed_shifts:
                continue
            disallowed = [shift_id for shift_id in settings.shift_ids if shift_id not in allowed_shifts]
            for shift_id in disallowed:
                literal = day_lits[day_idx].get(shift_id)
                if literal is None:
                    continue
                violation = context.model.NewBoolVar(
                    f"shift_pattern_theory_violation_{_slug(dept)}_d{day_idx}_s{slot_idx}_{_slug(shift_id)}"
                )
                context.model.Add(violation <= var)
                context.model.Add(violation <= literal)
                context.model.Add(var + literal - violation <= 1)
                register_objective_penalty(context, violation, self._penalty_weight, tag=f"shift_pattern:{dept}")
                penalties += 1
        return penalties

    def _register_ratio_penalties(
        self,
        context: ConstraintContext,
        dept_matrix: Mapping[str, Tuple[Mapping[str, cp_model.IntVar], ...]],
        settings: ShiftPatternSettings,
    ) -> int:
        if not settings.allowed_patterns:
            return 0
        penalties = 0
        model = context.model
        shift_ids = settings.shift_ids
        pattern_length = len(shift_ids)
        valid_patterns: Tuple[ShiftCounts, ...] = tuple(
            pattern[:pattern_length]
            for pattern in settings.allowed_patterns
            if len(pattern) >= pattern_length
        )
        if not valid_patterns:
            return 0
        for dept, day_entries in dept_matrix.items():
            day_count = len(day_entries)
            if day_count == 0:
                continue
            shift_totals: Dict[str, cp_model.IntVar] = {}
            for shift_id in shift_ids:
                if any(shift_id not in day_map for day_map in day_entries):
                    shift_totals.clear()
                    break
                total_var = model.NewIntVar(
                    0,
                    day_count,
                    f"shift_pattern_{_slug(dept)}_{_slug(shift_id)}_days",
                )
                model.Add(total_var == sum(day_map[shift_id] for day_map in day_entries))
                shift_totals[shift_id] = total_var
            if len(shift_totals) != len(shift_ids):
                continue

            pattern_distances: list[cp_model.IntVar] = []
            max_distance = day_count * pattern_length
            for pattern_index, pattern in enumerate(valid_patterns):
                diffs: list[cp_model.IntVar] = []
                for shift_pos, shift_id in enumerate(shift_ids):
                    target = int(pattern[shift_pos])
                    diff = model.NewIntVar(
                        0,
                        day_count,
                        f"shift_pattern_{_slug(dept)}_pattern{pattern_index}_diff_{_slug(shift_id)}",
                    )
                    model.AddAbsEquality(diff, shift_totals[shift_id] - target)
                    diffs.append(diff)
                distance = model.NewIntVar(
                    0,
                    max_distance,
                    f"shift_pattern_{_slug(dept)}_pattern{pattern_index}_distance",
                )
                model.Add(distance == sum(diffs))
                pattern_distances.append(distance)
            if not pattern_distances:
                continue

            violation = model.NewIntVar(0, max_distance, f"shift_pattern_{_slug(dept)}_violation")
            model.AddMinEquality(violation, pattern_distances)
            
            if settings.strict_ratios:
                model.Add(violation == 0)
            else:
                register_objective_penalty(
                    context,
                    violation,
                    self._ratio_penalty_weight,
                    tag=f"shift_pattern:{dept}",
                )
            penalties += 1
        return penalties


def _collect_departments(context: ConstraintContext) -> Tuple[str, ...]:
    lab_req = getattr(context.variables.lab, "requirements", {}) or {}
    theory_req = getattr(context.variables.theory, "course_requirements", {}) or {}
    departments = set()
    for requirement in lab_req.values():
        dept = getattr(requirement, "department", None)
        if dept:
            departments.add(dept)
    for requirement in theory_req.values():
        dept = getattr(requirement, "department", None)
        if dept:
            departments.add(dept)
    return tuple(sorted(departments))


def _initialise_department_days(
    context: ConstraintContext,
    departments: Sequence[str],
    shift_ids: Sequence[str],
) -> Mapping[str, Tuple[Mapping[str, cp_model.IntVar], ...]]:
    model = context.model
    result: Dict[str, Tuple[Mapping[str, cp_model.IntVar], ...]] = {}
    for dept in departments:
        pattern = resolve_day_pattern(context, dept)
        if not pattern:
            continue
        day_entries: list[Dict[str, cp_model.IntVar]] = []
        for day_idx in range(len(pattern)):
            shift_map: Dict[str, cp_model.IntVar] = {}
            literals = []
            for shift_id in shift_ids:
                literal = model.NewBoolVar(f"dept_shift_{_slug(dept)}_d{day_idx}_{_slug(shift_id)}")
                shift_map[shift_id] = literal
                literals.append(literal)
            if literals:
                model.Add(sum(literals) == 1)
                day_entries.append(shift_map)
        if day_entries:
            result[dept] = tuple(day_entries)
    return result


def build_shift_pattern_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> ShiftPatternConstraint:
    return ShiftPatternConstraint(metadata=metadata, params=params)


__all__ = ["ShiftPatternConstraint", "build_shift_pattern_constraint"]
