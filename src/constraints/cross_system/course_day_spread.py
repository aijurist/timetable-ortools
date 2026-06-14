"""Spread a course's lab and theory activity across multiple days."""

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
)


CourseKey = Tuple[str, str]


class CourseDaySpreadConstraint(Constraint):
    """Prevent mixed lab/theory courses from being completed on a single day."""

    DEFAULT_MIN_DISTINCT_DAYS = 2
    DEFAULT_SOFT_PENALTY_WEIGHT = 300

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        mode = str(self.params.get("mode", "hard")).strip().lower()
        if mode not in {"hard", "soft"}:
            mode = "hard"
        min_distinct_days = max(
            1,
            int(self.params.get("min_distinct_days", self.DEFAULT_MIN_DISTINCT_DAYS)),
        )
        min_total_activities = max(1, int(self.params.get("min_total_activities", 2)))
        include_single_domain_courses = bool(self.params.get("include_single_domain_courses", False))
        soft_penalty_weight = int(
            self.params.get("soft_penalty_weight", self.DEFAULT_SOFT_PENALTY_WEIGHT)
        )

        if min_distinct_days <= 1:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "min_distinct_days_le_one"})

        model = context.model
        lab_requirements = getattr(context.variables.lab, "requirements", {}) or {}
        theory_requirements = getattr(context.variables.theory, "course_requirements", {}) or {}

        day_buckets: MutableMapping[CourseKey, MutableMapping[int, list[cp_model.IntVar]]] = defaultdict(
            lambda: defaultdict(list)
        )
        domains_by_key: MutableMapping[CourseKey, Set[str]] = defaultdict(set)
        required_activity_count: MutableMapping[CourseKey, int] = defaultdict(int)
        display_by_key: Dict[CourseKey, Tuple[str, str]] = {}

        for course_id, requirement in lab_requirements.items():
            key = self._course_key(requirement.group_id, requirement.course_code)
            if key is None:
                continue
            domains_by_key[key].add("lab")
            required_activity_count[key] += max(0, int(getattr(requirement, "required_sessions", 0) or 0))
            display_by_key.setdefault(key, (requirement.group_id, requirement.course_code))

        for course_id, requirement in theory_requirements.items():
            key = self._course_key(requirement.group_id, requirement.course_code)
            if key is None:
                continue
            domains_by_key[key].add("theory")
            required_activity_count[key] += max(0, int(getattr(requirement, "required_slots", 0) or 0))
            display_by_key.setdefault(key, (requirement.group_id, requirement.course_code))

        for _teacher_id, course_id, day_idx, _session_name, _room_id, var in iter_lab_session_variables(context):
            requirement = lab_requirements.get(course_id)
            if requirement is None:
                continue
            key = self._course_key(requirement.group_id, requirement.course_code)
            if key is None:
                continue
            day_buckets[key][day_idx].append(var)

        for _teacher_id, course_id, day_idx, _slot_idx, var in iter_course_timeslot_variables(context):
            requirement = theory_requirements.get(course_id)
            if requirement is None:
                continue
            key = self._course_key(requirement.group_id, requirement.course_code)
            if key is None:
                continue
            day_buckets[key][day_idx].append(var)

        hard_constraints = 0
        soft_penalties = 0
        constrained_courses: list[str] = []
        skipped_single_domain = 0
        skipped_single_activity = 0
        skipped_insufficient_days = 0

        for key, day_map in sorted(day_buckets.items()):
            domains = domains_by_key.get(key, set())
            if not include_single_domain_courses and not {"lab", "theory"}.issubset(domains):
                skipped_single_domain += 1
                continue
            if required_activity_count.get(key, 0) < min_total_activities:
                skipped_single_activity += 1
                continue

            group_id, course_code = display_by_key.get(key, key)
            day_literals: list[cp_model.IntVar] = []
            for day_idx in sorted(day_map):
                literal = build_presence_literal(
                    model,
                    day_map[day_idx],
                    name=f"course_day_used_{self._sanitize(group_id)}_{self._sanitize(course_code)}_{day_idx}",
                )
                if literal is not None:
                    day_literals.append(literal)

            target_days = min(min_distinct_days, len(day_literals))
            if target_days <= 1:
                skipped_insufficient_days += 1
                continue

            label = f"{group_id}:{course_code}"
            if mode == "soft":
                deficit = model.NewIntVar(
                    0,
                    target_days,
                    f"course_day_spread_deficit_{self._sanitize(group_id)}_{self._sanitize(course_code)}",
                )
                model.Add(sum(day_literals) + deficit >= target_days)
                register_objective_penalty(
                    context,
                    deficit,
                    weight=soft_penalty_weight,
                    tag=f"course_day_spread:{group_id}:{course_code}",
                )
                soft_penalties += 1
            else:
                model.Add(sum(day_literals) >= target_days)
                hard_constraints += 1
            constrained_courses.append(label)

        constraints_added = hard_constraints + soft_penalties
        status = ConstraintStatus.APPLIED if constraints_added else ConstraintStatus.SKIPPED
        return self._result(
            status,
            {
                "mode": mode,
                "min_distinct_days": min_distinct_days,
                "min_total_activities": min_total_activities,
                "include_single_domain_courses": include_single_domain_courses,
                "hard_constraints": hard_constraints,
                "soft_penalties": soft_penalties,
                "constrained_courses": tuple(constrained_courses),
                "skipped_single_domain": skipped_single_domain,
                "skipped_single_activity": skipped_single_activity,
                "skipped_insufficient_days": skipped_insufficient_days,
            },
        )

    @staticmethod
    def _course_key(group_id: Optional[str], course_code: Optional[str]) -> Optional[CourseKey]:
        group = str(group_id or "").strip()
        code = str(course_code or "").strip().upper()
        if not group or not code:
            return None
        return group, code

    @staticmethod
    def _sanitize(value: object) -> str:
        text = str(value or "").strip()
        return re.sub(r"[^A-Za-z0-9_]+", "_", text) or "value"

    def _result(self, status: str, details: Mapping[str, object]) -> ConstraintApplicationResult:
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details=dict(details),
        )


def build_course_day_spread_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> CourseDaySpreadConstraint:
    return CourseDaySpreadConstraint(metadata=metadata, params=params or {})


__all__ = ["CourseDaySpreadConstraint", "build_course_day_spread_constraint"]
