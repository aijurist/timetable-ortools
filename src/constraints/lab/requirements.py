"""Lab session coverage constraints.

This module enforces that every lab course receives the exact number of
sessions required for the week. The constraint is intentionally conservative:
it sums every boolean assignment variable exposed by the variable creator and
pins the total to ``required_sessions`` computed during preprocessing. Any
missing variable sets are logged for quick diagnostics, allowing data issues to
surface early in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Optional

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_lab_session_variables


@dataclass
class CoverageStats:
	courses_with_constraints: int = 0
	constraints_added: int = 0
	missing_courses: List[str] = None  # type: ignore[assignment]

	def __post_init__(self) -> None:
		if self.missing_courses is None:
			self.missing_courses = []


class LabSessionCoverageConstraint(Constraint):
	"""Ensure each lab course is scheduled for its required weekly sessions."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("coverage")
		stats = CoverageStats()
		lab_block = context.variables.lab

		for course_id, requirement in lab_block.requirements.items():
			if requirement.required_sessions <= 0:
				continue

			assignment_vars = [
				var
				for *_prefix, var in iter_lab_session_variables(context, course_instance_id=course_id)
			]

			if not assignment_vars:
				stats.missing_courses.append(course_id)
				logger.warning("No lab assignment variables available for %s", course_id)
				continue

			context.model.Add(sum(assignment_vars) == requirement.required_sessions)
			stats.courses_with_constraints += 1
			stats.constraints_added += 1

		if stats.missing_courses:
			logger.warning(
				"Lab coverage skipped %d course(s) due to missing variables: %s",
				len(stats.missing_courses),
				stats.missing_courses[:5],
			)

		status = ConstraintStatus.APPLIED if stats.constraints_added else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"courses": stats.courses_with_constraints,
				"constraints": stats.constraints_added,
				"missing_courses": tuple(stats.missing_courses),
			},
		)


def build_lab_session_coverage_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> LabSessionCoverageConstraint:
	"""Factory helper used by the registry."""

	return LabSessionCoverageConstraint(metadata=metadata, params=params)


__all__ = [
	"LabSessionCoverageConstraint",
	"build_lab_session_coverage_constraint",
]
