"""Limit the active days for specific department-semester pairs.

This constraint caps how many distinct days a department/semester can use across
both theory and lab activities. It is intended to pack schedules into fewer
days when departments have fixed day patterns. Example: restrict 4th-year (8th
semester) departments to two days of activity, while exempting specific
departments like Computer Science & Business Systems.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    build_presence_literal,
    ensure_extra_bucket,
    iter_lab_session_variables,
    resolve_day_pattern,
    resolve_group_slot_map,
)


class DepartmentDaySpanConstraint(Constraint):
    """Cap the number of active days for targeted dept/semester pairs."""

    def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
        super().__init__(metadata, params=params)
        params = params or {}
        self._day_limit = int(params.get("day_limit", 2))
        raw_semesters = params.get("target_semesters", (8,))
        self._target_semesters = tuple(int(s) for s in (raw_semesters or ()))
        raw_excluded = params.get("excluded_departments", ("Computer Science & Business Systems",))
        self._excluded_departments = frozenset(str(dept) for dept in (raw_excluded or ()))
        raw_allowed = params.get("allowed_days_by_department", {}) or {}
        self._allowed_days_by_dept: Dict[str, Tuple[str, ...]] = {
            str(dept): tuple(self._normalise_day(day) for day in (days or []) if day)
            for dept, days in raw_allowed.items()
        }
        raw_default_allowed = params.get("default_allowed_days") or ()
        self._default_allowed_days: Tuple[str, ...] = tuple(
            self._normalise_day(day) for day in raw_default_allowed if day
        )

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:  # type: ignore[override]
        if not self._target_semesters or self._day_limit <= 0:
            return ConstraintApplicationResult(
                name=self.metadata.name,
                domain=self.metadata.category,
                priority=self.metadata.priority,
                enabled=True,
                status=ConstraintStatus.SKIPPED,
                details={"constraints": 0, "departments": 0},
            )

        model = context.model
        working_days = tuple(getattr(context.data.raw.time, "working_days", tuple())) or ("day_0",)
        theory_block = context.variables.theory
        lab_block = context.variables.lab

        group_slot_map = resolve_group_slot_map(context)
        theory_requirements = getattr(theory_block, "requirements", {}) or {}
        lab_requirements = getattr(lab_block, "requirements", {}) or {}

        # dept_sem -> list indexed by day -> list of variables scheduled on that day
        buckets: Dict[Tuple[str, int], Dict[int, list[cp_model.IntVar]]] = {}
        day_counts: Dict[Tuple[str, int], int] = {}
        allowed_day_indices: Dict[Tuple[str, int], Optional[set[int]]] = {}

        def _bucket(key: Tuple[str, int], day_count: int) -> Dict[int, list[cp_model.IntVar]]:
            if key not in buckets:
                buckets[key] = {}
                day_counts[key] = day_count
            return buckets[key]

        # Collect theory usage per day
        for group_id, requirement in theory_requirements.items():
            dept = requirement.department
            semester = int(requirement.semester) if requirement.semester is not None else None
            if semester is None or not self._is_target(dept, semester):
                continue
            day_pattern = resolve_day_pattern(context, dept)
            day_names = day_pattern if day_pattern else working_days
            day_count = len(day_names)
            bucket = _bucket((dept, semester), day_count)
            if (dept, semester) not in allowed_day_indices:
                allowed_day_indices[(dept, semester)] = self._allowed_day_indices_for(dept, day_names)
            day_map = group_slot_map.get(group_id, {})
            for day_idx, slot_map in day_map.items():
                vars_for_day = bucket.setdefault(day_idx, [])
                for var in slot_map.values():
                    vars_for_day.append(var)

        # Collect lab usage per day
        course_lookup = {cid: req for cid, req in lab_requirements.items()}
        for _tid, course_id, day_idx, _session, _room, var in iter_lab_session_variables(context):
            requirement = course_lookup.get(course_id)
            if requirement is None:
                continue
            dept = requirement.department
            semester = int(requirement.semester) if requirement.semester is not None else None
            if semester is None or not self._is_target(dept, semester):
                continue
            day_pattern = resolve_day_pattern(context, dept)
            day_names = day_pattern if day_pattern else working_days
            day_count = len(day_names)
            bucket = _bucket((dept, semester), day_count)
            if (dept, semester) not in allowed_day_indices:
                allowed_day_indices[(dept, semester)] = self._allowed_day_indices_for(dept, day_names)
            vars_for_day = bucket.setdefault(day_idx, [])
            vars_for_day.append(var)

        constraints_added = 0
        departments_constrained = 0
        for key, day_map in buckets.items():
            dept, semester = key
            day_count = day_counts.get(key, len(working_days)) or len(working_days)
            allowed_indices = allowed_day_indices.get(key)
            day_literal_map: Dict[int, cp_model.IntVar] = {}
            for day_idx in range(day_count):
                vars_for_day = day_map.get(day_idx, [])
                if allowed_indices is not None and day_idx not in allowed_indices:
                    for var in vars_for_day:
                        model.Add(var == 0)
                    continue
                literal = build_presence_literal(
                    model,
                    vars_for_day,
                    name=f"day_used_{self._sanitize(dept)}_{semester}_{day_idx}",
                )
                if literal is not None:
                    day_literal_map[day_idx] = literal

            if not day_literal_map:
                continue

            day_literals = list(day_literal_map.values())
            limit = self._day_limit if self._day_limit > 0 else len(day_literals)
            if allowed_indices is not None and day_literals:
                limit = min(limit, len(day_literals))

            total_days = sum(day_literals)
            model.Add(total_days <= limit)

            # Enforce continuity when the limit is 2: if two days are used, they must be consecutive
            if limit == 2 and len(day_literals) >= 2:
                consecutive_literals: list[cp_model.IntVar] = []
                sorted_days = sorted(day_literal_map.keys())
                for idx, start_day in enumerate(sorted_days[:-1]):
                    next_day = sorted_days[idx + 1]
                    if next_day - start_day != 1:
                        continue
                    consec = model.NewBoolVar(
                        f"day_consec_{self._sanitize(dept)}_{semester}_{start_day}_{next_day}"
                    )
                    model.Add(day_literal_map[start_day] + day_literal_map[next_day] == 2).OnlyEnforceIf(consec)
                    model.Add(day_literal_map[start_day] + day_literal_map[next_day] <= 1).OnlyEnforceIf(
                        consec.Not()
                    )
                    consecutive_literals.append(consec)

                two_days_used = model.NewBoolVar(f"two_days_used_{self._sanitize(dept)}_{semester}")
                model.Add(total_days == 2).OnlyEnforceIf(two_days_used)
                model.Add(total_days <= 1).OnlyEnforceIf(two_days_used.Not())
                if consecutive_literals:
                    model.AddBoolOr(consecutive_literals).OnlyEnforceIf(two_days_used)

            constraints_added += 1
            departments_constrained += 1

        # Record for debugging/inspection
        if constraints_added:
            extra = ensure_extra_bucket(context, "dept_day_span")
            extra.setdefault("constraints_added", 0)
            extra["constraints_added"] += constraints_added

        status = ConstraintStatus.APPLIED if constraints_added else ConstraintStatus.SKIPPED
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details={
                "constraints": constraints_added,
                "departments": departments_constrained,
                "day_limit": self._day_limit,
            },
        )

    def _is_target(self, dept: str, semester: int) -> bool:
        if dept in self._excluded_departments:
            return False
        return semester in self._target_semesters

    @staticmethod
    def _sanitize(text: str) -> str:
        return text.replace(" ", "_").replace("/", "_")

    @staticmethod
    def _normalise_day(day: str) -> str:
        return str(day).strip().lower()

    def _allowed_day_indices_for(self, department: str, day_names: Sequence[str]) -> Optional[set[int]]:
        allowed_days = self._allowed_days_by_dept.get(department) or self._default_allowed_days
        if not allowed_days:
            return None
        lookup = {self._normalise_day(name): idx for idx, name in enumerate(day_names)}
        indices = {idx for name, idx in lookup.items() if name in allowed_days}
        return indices


def build_department_day_span_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> DepartmentDaySpanConstraint:
    return DepartmentDaySpanConstraint(metadata=metadata, params=params)


__all__ = ["build_department_day_span_constraint", "DepartmentDaySpanConstraint"]