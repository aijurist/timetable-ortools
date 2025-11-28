"""Theory requirement constraints sharing coverage and daily cap logic."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
	build_presence_literal,
	iter_course_timeslot_variables,
	iter_group_timeslot_variables,
	parse_department_token,
)


@dataclass
class CoverageStats:
	courses_with_constraints: int = 0
	constraints_added: int = 0


class TheorySlotCoverageConstraint(Constraint):
	"""Ensure every theory course instance receives exactly its required number of slots."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		theory_block = context.variables.theory
		stats = CoverageStats()

		for course_id, requirement in theory_block.course_requirements.items():
			required_slots = max(0, requirement.required_slots)
			if required_slots <= 0:
				continue

			slot_variables = [
				var
				for _tid, _cid, _day, _slot, var in iter_course_timeslot_variables(
					context,
					course_instance_id=course_id,
				)
			]
			if not slot_variables:
				continue

			model.Add(sum(slot_variables) == required_slots)
			stats.courses_with_constraints += 1
			stats.constraints_added += 1

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
			},
		)


@dataclass(frozen=True)
class SlotCapConfig:
	default_limit: int = 5
	core_limit: int = 6
	core_departments: Tuple[str, ...] = (
		"Aeronautical Engineering",
		"Automobile Engineering",
		"Biomedical Engineering",
		"Biotechnology",
		"Chemical Engineering",
		"Civil Engineering",
		"Electrical & Electronics Engineering",
		"Electronics & Communication Engineering",
		"Food Technology",
		"Mechanical Engineering",
		"Mechatronics Engineering",
	)
	exemptions: Tuple[Tuple[str, Optional[int]], ...] = tuple()

	@staticmethod
	def from_params(params: Mapping[str, object]) -> "SlotCapConfig":
		default_limit = int(params.get("default_limit", 5))
		core_limit = int(params.get("core_limit", 6))
		core_departments = tuple(params.get("core_departments", SlotCapConfig.core_departments) or SlotCapConfig.core_departments)
		exempt_tokens: Sequence[str] = tuple(params.get("exemptions", ()))
		exemptions = tuple(parse_department_token(token) for token in exempt_tokens)
		return SlotCapConfig(
			default_limit=default_limit,
			core_limit=core_limit,
			core_departments=core_departments,
			exemptions=exemptions,
		)


class TheoryDailySlotCapConstraint(Constraint):
	"""Limit how many distinct theory slots a department can use per day."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		self._config = SlotCapConfig.from_params(params or {})

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		theory_block = context.variables.theory
		day_patterns = theory_block.day_patterns
		dept_groups: Dict[Tuple[str, Optional[int]], list[str]] = defaultdict(list)

		for group_id, requirement in theory_block.requirements.items():
			dept_groups[(requirement.department, requirement.semester)].append(group_id)

		constraints_added = 0
		departments_constrained = 0
		num_slots = len(theory_block.theory_slot_labels)

		for key, group_ids in dept_groups.items():
			if self._is_exempt(key):
				continue
			limit = self._config.core_limit if key[0] in self._config.core_departments else self._config.default_limit
			day_count = self._max_day_count(group_ids, day_patterns)
			if day_count == 0:
				continue
			applied = self._apply_cap(
				model,
				theory_block.group_timeslots,
				group_ids,
				day_count,
				num_slots,
				limit,
			)
			if applied:
				departments_constrained += 1
				constraints_added += applied

		status = ConstraintStatus.APPLIED if constraints_added else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"departments": departments_constrained,
				"constraints": constraints_added,
			},
		)

	def _is_exempt(self, key: Tuple[str, Optional[int]]) -> bool:
		dept, semester = key
		return (dept, semester) in self._config.exemptions or (dept, None) in self._config.exemptions

	@staticmethod
	def _max_day_count(group_ids: Sequence[str], day_patterns: Mapping[str, Sequence[str]]) -> int:
		counts = [len(day_patterns.get(group_id, ())) for group_id in group_ids]
		return max(counts) if counts else 0

	def _apply_cap(
		self,
		model: cp_model.CpModel,
		group_timeslots: Mapping[str, Mapping[int, Mapping[int, cp_model.IntVar]]],
		group_ids: Sequence[str],
		day_count: int,
		num_slots: int,
		limit: int,
	) -> int:
		"""Apply per-day cap and return how many constraints were added."""

		constraints = 0
		for day_idx in range(day_count):
			slot_usage_literals = []
			for slot_idx in range(num_slots):
				variables = []
				for group_id in group_ids:
					day_map = group_timeslots.get(group_id, {})
					slot_map = day_map.get(day_idx, {}) if isinstance(day_map, Mapping) else {}
					var = slot_map.get(slot_idx) if isinstance(slot_map, Mapping) else None
					if var is not None:
						variables.append(var)
				literal = build_presence_literal(
					model,
					variables,
					f"slot_used_{self._sanitize_group_id(group_ids[0])}_{day_idx}_{slot_idx}",
				)
				if literal is not None:
					slot_usage_literals.append(literal)
			if slot_usage_literals:
				model.Add(sum(slot_usage_literals) <= limit)
				constraints += 1
		return constraints

	@staticmethod
	def _sanitize_group_id(group_id: str) -> str:
		return group_id.replace(" ", "_")


def build_theory_slot_coverage_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TheorySlotCoverageConstraint:
	return TheorySlotCoverageConstraint(metadata=metadata, params=params)


def build_theory_daily_slot_cap_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TheoryDailySlotCapConstraint:
	return TheoryDailySlotCapConstraint(metadata=metadata, params=params)


__all__ = [
	"build_theory_slot_coverage_constraint",
	"build_theory_daily_slot_cap_constraint",
	"TheorySlotCoverageConstraint",
	"TheoryDailySlotCapConstraint",
]
