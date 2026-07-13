"""Theory course-level daily slot limit constraint."""

from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Mapping, Optional

from ortools.sat.python import cp_model

from ...data.pop_availability import (
	build_pop_availability_from_dataframe,
	normalize_teacher_id,
)
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
		self._exempt_pop_bundles = bool(settings.get("exempt_pop_bundles", True))

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		assignments: DefaultDict[tuple[str, str, int], list[cp_model.IntVar]] = defaultdict(list)

		for teacher_id, course_id, day_idx, _slot_idx, literal in iter_course_timeslot_variables(context):
			assignments[(teacher_id, course_id, day_idx)].append(literal)

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
		pop_exempt_courses, pop_exempt_bundles = self._pop_exemptions(context)

		for (_teacher_id, course_id, day_idx), literals in assignments.items():
			if not literals:
				continue
			if course_id in pop_exempt_courses:
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
				"pop_exempt_courses": len(pop_exempt_courses),
				"pop_exempt_bundles": tuple(sorted(pop_exempt_bundles)),
			},
		)

	def _pop_exemptions(self, context: ConstraintContext) -> tuple[set[str], set[str]]:
		"""Exempt POP offerings and every partner sharing their Kutty bundle."""

		if not self._exempt_pop_bundles:
			return set(), set()
		preferences = getattr(context.data.raw, "teacher_preferences_df", None)
		pop_teacher_ids = set(build_pop_availability_from_dataframe(preferences))
		if not pop_teacher_ids:
			return set(), set()

		requirements = context.variables.theory.course_requirements
		pop_bundle_ids = {
			str(requirement.bundle_id)
			for requirement in requirements.values()
			if requirement.bundle_id
			and normalize_teacher_id(requirement.teacher_id) in pop_teacher_ids
		}
		exempt_course_ids = {
			course_id
			for course_id, requirement in requirements.items()
			if normalize_teacher_id(requirement.teacher_id) in pop_teacher_ids
			or (requirement.bundle_id and str(requirement.bundle_id) in pop_bundle_ids)
		}
		return exempt_course_ids, pop_bundle_ids


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
