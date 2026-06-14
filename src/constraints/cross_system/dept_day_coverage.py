"""Ensure department-semester timetables use their configured teaching days."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Mapping, MutableMapping, Optional, Set, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    build_presence_literal,
    iter_course_timeslot_variables,
    iter_lab_session_variables,
    register_objective_penalty,
    resolve_day_pattern,
)


DeptSemesterKey = Tuple[str, int]


class DepartmentDayCoverageConstraint(Constraint):
    """Require each department-semester timetable to cover all configured days."""

    DEFAULT_TARGET_DAYS = 5
    DEFAULT_SOFT_PENALTY_WEIGHT = 500

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        mode = str(self.params.get("mode", "hard")).strip().lower()
        if mode not in {"hard", "soft"}:
            mode = "hard"

        raw_target_days = self.params.get("target_days", self.DEFAULT_TARGET_DAYS)
        target_days = None if str(raw_target_days).strip().lower() in {"all", "pattern"} else int(raw_target_days)
        min_total_activities = max(1, int(self.params.get("min_total_activities", 2)))
        soft_penalty_weight = int(
            self.params.get("soft_penalty_weight", self.DEFAULT_SOFT_PENALTY_WEIGHT)
        )
        target_semesters = self._parse_semesters(self.params.get("target_semesters"))
        excluded_keys = self._parse_department_tokens(self.params.get("excluded_departments"))

        lab_requirements = getattr(context.variables.lab, "requirements", {}) or {}
        theory_requirements = getattr(context.variables.theory, "course_requirements", {}) or {}
        day_buckets: MutableMapping[DeptSemesterKey, MutableMapping[int, list[cp_model.IntVar]]] = defaultdict(
            lambda: defaultdict(list)
        )
        required_activity_count: MutableMapping[DeptSemesterKey, int] = defaultdict(int)
        available_day_indices: MutableMapping[DeptSemesterKey, Set[int]] = defaultdict(set)

        for requirement in lab_requirements.values():
            key = self._requirement_key(requirement)
            if key is None or not self._is_target(key, target_semesters, excluded_keys):
                continue
            required_activity_count[key] += max(0, int(getattr(requirement, "required_sessions", 0) or 0))

        for requirement in theory_requirements.values():
            key = self._requirement_key(requirement)
            if key is None or not self._is_target(key, target_semesters, excluded_keys):
                continue
            required_activity_count[key] += max(0, int(getattr(requirement, "required_slots", 0) or 0))

        for _teacher_id, course_id, day_idx, _session_name, _room_id, var in iter_lab_session_variables(context):
            requirement = lab_requirements.get(course_id)
            key = self._requirement_key(requirement)
            if key is None or not self._is_target(key, target_semesters, excluded_keys):
                continue
            day_buckets[key][day_idx].append(var)
            available_day_indices[key].add(day_idx)

        for _teacher_id, course_id, day_idx, _slot_idx, var in iter_course_timeslot_variables(context):
            requirement = theory_requirements.get(course_id)
            key = self._requirement_key(requirement)
            if key is None or not self._is_target(key, target_semesters, excluded_keys):
                continue
            day_buckets[key][day_idx].append(var)
            available_day_indices[key].add(day_idx)

        hard_constraints = 0
        soft_penalties = 0
        constrained_departments: list[str] = []
        target_days_by_department: Dict[str, int] = {}
        skipped_light_load = 0
        skipped_insufficient_days = 0

        for key, day_map in sorted(day_buckets.items()):
            dept, semester = key
            total_required = required_activity_count.get(key, 0)
            if total_required < min_total_activities:
                skipped_light_load += 1
                continue

            configured_days = resolve_day_pattern(context, dept)
            configured_day_count = len(configured_days) if configured_days else 0
            possible_day_count = len(available_day_indices.get(key, set(day_map)))
            requested_days = configured_day_count if target_days is None else target_days
            required_days = min(requested_days, configured_day_count or requested_days, possible_day_count, total_required)
            if required_days <= 1:
                skipped_insufficient_days += 1
                continue

            day_literals: list[cp_model.IntVar] = []
            for day_idx in sorted(day_map):
                literal = build_presence_literal(
                    context.model,
                    day_map[day_idx],
                    name=f"dept_day_used_{self._sanitize(dept)}_s{semester}_{day_idx}",
                )
                if literal is not None:
                    day_literals.append(literal)

            if len(day_literals) < required_days:
                skipped_insufficient_days += 1
                continue

            label = f"{dept}_S{semester}"
            if mode == "soft":
                deficit = context.model.NewIntVar(
                    0,
                    required_days,
                    f"dept_day_coverage_deficit_{self._sanitize(dept)}_s{semester}",
                )
                context.model.Add(sum(day_literals) + deficit >= required_days)
                register_objective_penalty(
                    context,
                    deficit,
                    weight=soft_penalty_weight,
                    tag=f"dept_day_coverage:{dept}:S{semester}",
                )
                soft_penalties += 1
            else:
                context.model.Add(sum(day_literals) >= required_days)
                hard_constraints += 1

            constrained_departments.append(label)
            target_days_by_department[label] = required_days

        constraints_added = hard_constraints + soft_penalties
        status = ConstraintStatus.APPLIED if constraints_added else ConstraintStatus.SKIPPED
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details={
                "mode": mode,
                "target_days": raw_target_days,
                "min_total_activities": min_total_activities,
                "hard_constraints": hard_constraints,
                "soft_penalties": soft_penalties,
                "constrained_departments": tuple(constrained_departments),
                "target_days_by_department": target_days_by_department,
                "skipped_light_load": skipped_light_load,
                "skipped_insufficient_days": skipped_insufficient_days,
            },
        )

    @staticmethod
    def _requirement_key(requirement: object) -> Optional[DeptSemesterKey]:
        if requirement is None:
            return None
        dept = str(getattr(requirement, "department", "") or "").strip()
        semester = getattr(requirement, "semester", None)
        if not dept or semester is None:
            return None
        return dept, int(semester)

    @staticmethod
    def _parse_semesters(value: object) -> Optional[Set[int]]:
        if value in (None, "", ()):
            return None
        if isinstance(value, str):
            return {int(value)}
        try:
            return {int(item) for item in value}  # type: ignore[arg-type]
        except TypeError:
            return {int(value)}

    @classmethod
    def _parse_department_tokens(cls, value: object) -> Set[Tuple[str, Optional[int]]]:
        if value in (None, "", ()):
            return set()
        tokens = value if isinstance(value, (list, tuple, set)) else (value,)
        parsed: Set[Tuple[str, Optional[int]]] = set()
        for token in tokens:
            text = str(token or "").strip()
            if not text:
                continue
            dept, semester = cls._split_department_token(text)
            parsed.add((dept, semester))
        return parsed

    @staticmethod
    def _split_department_token(token: str) -> Tuple[str, Optional[int]]:
        if "_S" not in token:
            return token, None
        dept, _, suffix = token.rpartition("_S")
        try:
            return dept.strip(), int(suffix)
        except ValueError:
            return token, None

    @staticmethod
    def _is_target(
        key: DeptSemesterKey,
        target_semesters: Optional[Set[int]],
        excluded_keys: Set[Tuple[str, Optional[int]]],
    ) -> bool:
        dept, semester = key
        if target_semesters is not None and semester not in target_semesters:
            return False
        if (dept, None) in excluded_keys or (dept, semester) in excluded_keys:
            return False
        return True

    @staticmethod
    def _sanitize(value: object) -> str:
        text = str(value or "").strip()
        return re.sub(r"[^A-Za-z0-9_]+", "_", text) or "value"


def build_department_day_coverage_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> DepartmentDayCoverageConstraint:
    return DepartmentDayCoverageConstraint(metadata=metadata, params=params or {})


__all__ = ["DepartmentDayCoverageConstraint", "build_department_day_coverage_constraint"]
