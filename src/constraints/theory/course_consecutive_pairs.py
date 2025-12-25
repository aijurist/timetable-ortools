"""Theory constraint enforcing consecutive slot pairs for selected courses."""

from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Mapping, Optional, Sequence

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_course_timeslot_variables


class TheoryCourseConsecutivePairsConstraint(Constraint):
	"""Force a course instance to schedule its theory hours as consecutive pairs.

	Typical use-case: 4 theory hours must be scheduled as 2 consecutive slots twice (2+2).

	Params:
	- course_codes: list[str] course codes to target
	- required_slots: int (default: 4) only apply to instances with exactly this many slots
	- pair_length: int (default: 2) length of each consecutive block
	"""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		settings = params or {}
		course_codes = settings.get("course_codes", ())
		if isinstance(course_codes, str):
			course_codes = (course_codes,)
		self._course_codes = tuple(str(code).strip() for code in (course_codes or ()) if str(code).strip())
		try:
			self._required_slots = int(settings.get("required_slots", 4))
		except (TypeError, ValueError):
			self._required_slots = 4
		try:
			self._pair_length = max(2, int(settings.get("pair_length", 2)))
		except (TypeError, ValueError):
			self._pair_length = 2

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		theory_block = context.variables.theory

		if not self._course_codes:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no course_codes configured"},
			)

		if self._required_slots <= 0 or self._pair_length <= 0:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "invalid required_slots/pair_length"},
			)

		if self._required_slots % self._pair_length != 0:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={
					"reason": "required_slots not divisible by pair_length",
					"required_slots": self._required_slots,
					"pair_length": self._pair_length,
				},
			)

		pair_count = self._required_slots // self._pair_length
		num_slots = len(theory_block.theory_slot_labels)

		constraints_added = 0
		courses_affected = 0

		for course_id, requirement in theory_block.course_requirements.items():
			if requirement.course_code not in self._course_codes:
				continue
			if requirement.required_slots != self._required_slots:
				continue

			# day_idx -> slot_idx -> var
			day_slot_vars: DefaultDict[int, dict[int, cp_model.IntVar]] = defaultdict(dict)
			for _tid, cid, day_idx, slot_idx, var in iter_course_timeslot_variables(
				context,
				course_instance_id=course_id,
			):
				day_slot_vars[day_idx][slot_idx] = var

			if not day_slot_vars:
				continue

			# Create start literals for each consecutive pair.
			pair_start_map: DefaultDict[int, dict[int, cp_model.IntVar]] = defaultdict(dict)
			pair_starts: list[cp_model.IntVar] = []

			for day_idx, slot_map in day_slot_vars.items():
				for start_slot in range(0, max(0, num_slots - (self._pair_length - 1))):
					segment = [slot_map.get(start_slot + offset) for offset in range(self._pair_length)]
					if any(var is None for var in segment):
						continue
					pair_var = model.NewBoolVar(
						f"theory_pair_{course_id}_d{day_idx}_s{start_slot}_len{self._pair_length}"
					)
					# pair_var == AND(segment)
					for var in segment:
						model.Add(pair_var <= var)
						constraints_added += 1
					model.Add(pair_var >= sum(segment) - (self._pair_length - 1))
					constraints_added += 1
					pair_start_map[day_idx][start_slot] = pair_var
					pair_starts.append(pair_var)

			if not pair_starts:
				continue

			# Exactly N consecutive blocks.
			model.Add(sum(pair_starts) == pair_count)
			constraints_added += 1

			# Every scheduled slot must be covered by one of the pair blocks.
			for day_idx, slot_map in day_slot_vars.items():
				for slot_idx, var in slot_map.items():
					cover_terms = []
					for start_slot, pair_var in pair_start_map[day_idx].items():
						if start_slot <= slot_idx < start_slot + self._pair_length:
							cover_terms.append(pair_var)
					if cover_terms:
						model.Add(var <= sum(cover_terms))
						constraints_added += 1
					else:
						# Defensive: if we can't build coverage literals, block this slot.
						model.Add(var == 0)
						constraints_added += 1

			courses_affected += 1

		status = ConstraintStatus.APPLIED if constraints_added else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"courses": courses_affected,
				"constraints": constraints_added,
				"course_codes": self._course_codes,
				"required_slots": self._required_slots,
				"pair_length": self._pair_length,
				"pair_count": pair_count,
			},
		)


def build_theory_course_consecutive_pairs_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TheoryCourseConsecutivePairsConstraint:
	return TheoryCourseConsecutivePairsConstraint(metadata=metadata, params=params)


__all__ = [
	"TheoryCourseConsecutivePairsConstraint",
	"build_theory_course_consecutive_pairs_constraint",
]
