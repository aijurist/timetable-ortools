"""Soft constraint to prefer morning theory and afternoon labs."""

from __future__ import annotations

from typing import Mapping, Optional

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    iter_course_timeslot_variables,
    iter_lab_session_variables,
    register_objective_penalty,
)


class MorningTheoryAfternoonLabConstraint(Constraint):
    """Encourage theory in morning slots and labs in afternoon slots."""

    DEFAULT_PENALTY_WEIGHT = 1

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        penalty_weight = int(self.params.get("penalty_weight", self.DEFAULT_PENALTY_WEIGHT))
        if penalty_weight <= 0:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "weight_zero"})

        theory_penalties = 0
        lab_penalties = 0
        for teacher_id, course_id, day_idx, slot_index, var in iter_course_timeslot_variables(context):
            if slot_index >= 7:
                register_objective_penalty(
                    context,
                    var,
                    weight=penalty_weight,
                    tag=f"pref_morning_theory:{teacher_id}:{course_id}:d{day_idx}:s{slot_index}",
                )
                theory_penalties += 1

        for teacher_id, course_id, day_idx, session_name, room_id, var in iter_lab_session_variables(context):
            if session_name == "L1":
                register_objective_penalty(
                    context,
                    var,
                    weight=penalty_weight,
                    tag=f"pref_afternoon_lab:{teacher_id}:{course_id}:d{day_idx}:{session_name}",
                )
                lab_penalties += 1

        if theory_penalties == 0 and lab_penalties == 0:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no_variables_matched"})

        return self._result(
            ConstraintStatus.APPLIED,
            {
                "theory_penalties_applied": theory_penalties,
                "lab_penalties_applied": lab_penalties,
                "weight": penalty_weight,
            },
        )

    def _result(self, status: str, details: Mapping[str, object]) -> ConstraintApplicationResult:
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details=dict(details),
        )


def build_morning_theory_lab_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> MorningTheoryAfternoonLabConstraint:
    return MorningTheoryAfternoonLabConstraint(metadata=metadata, params=params or {})
