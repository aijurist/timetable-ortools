"""Constraints managing adjacency rules for theory slots."""

from __future__ import annotations

from typing import Mapping, Optional

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import resolve_group_slot_map


class NoThreeConsecutiveSlotsConstraint(Constraint):
	"""Prevent any group from occupying three consecutive theory slots in a day."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		slots = params.get("window") if params else None
		if slots:
			self._window = max(3, int(slots))
		else:
			self._window = 3

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		theory_block = context.variables.theory
		group_slot_map = resolve_group_slot_map(context)
		if not group_slot_map:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no theory groups available"},
			)
		num_slots = len(theory_block.theory_slot_labels)
		blocked_sequences = 0

		for group_id, day_map in group_slot_map.items():
			for day_idx, slot_map in day_map.items():
				for start_slot in range(0, max(0, num_slots - (self._window - 1))):
					sequence = [
						slot_map.get(start_slot + offset)
						for offset in range(self._window)
					]
					if any(var is None for var in sequence):
						continue
					model.Add(sum(sequence) <= self._window - 1)
					blocked_sequences += 1

		status = ConstraintStatus.APPLIED if blocked_sequences else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={"blocked_sequences": blocked_sequences},
		)


def build_no_three_consecutive_slots_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> NoThreeConsecutiveSlotsConstraint:
	return NoThreeConsecutiveSlotsConstraint(metadata=metadata, params=params)


__all__ = [
	"NoThreeConsecutiveSlotsConstraint",
	"build_no_three_consecutive_slots_constraint",
]
