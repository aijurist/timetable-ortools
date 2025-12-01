"""Theory course-level daily slot limit constraint."""

from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Mapping, Optional

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_course_timeslot_variables


class TheoryCourseDailyLimitConstraint(Constraint):
	"""Limit how many theory slots a single course instance may occupy per day."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		settings = params or {}
		limit = settings.get("max_daily_slots", 2)
		try:
			self._max_daily_slots = max(1, int(limit))
		except (TypeError, ValueError):
			self._max_daily_slots = 2

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		assignments: DefaultDict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)

		for _teacher_id, course_id, day_idx, _slot_idx, literal in iter_course_timeslot_variables(context):
			assignments[(course_id, day_idx)].append(literal)

		if not assignments:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no theory assignments"},
			)

		constraints_added = 0
		courses_impacted: set[str] = set()

		for (course_id, day_idx), literals in assignments.items():
			if not literals:
				continue
			model.Add(sum(literals) <= self._max_daily_slots)
			constraints_added += 1
			courses_impacted.add(course_id)

		status = ConstraintStatus.APPLIED if constraints_added else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"courses": len(courses_impacted),
				"constraints": constraints_added,
				"max_daily_slots": self._max_daily_slots,
			},
		)


def build_theory_course_daily_limit_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TheoryCourseDailyLimitConstraint:
	return TheoryCourseDailyLimitConstraint(metadata=metadata, params=params)


__all__ = [
	"TheoryCourseDailyLimitConstraint",
	"build_theory_course_daily_limit_constraint",
]
