from __future__ import annotations

from typing import Mapping, Optional

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    iter_lab_session_variables,
    iter_theory_room_variables,
    register_objective_penalty,
)


class EngineeringGraphicsPreferenceConstraint(Constraint):
    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        preferred_rooms = set(self.params.get("preferred_rooms", ["C401", "B310"]))
        preferred_rooms = {r.strip() for r in preferred_rooms}
        target_courses = set(self.params.get("course_codes", ["GE23111"]))
        penalty_weight = float(self.params.get("penalty_weight", 50.0))

        penalized_count = 0

        for teacher_id, course_id, day_idx, slot_idx, room_id, var in iter_theory_room_variables(context):
            req = context.variables.theory.course_requirements.get(course_id)
            if not req:
                continue

            if req.course_code in target_courses:
                if room_id not in preferred_rooms:
                    register_objective_penalty(
                        context,
                        var,
                        weight=penalty_weight,
                        tag="engineering_graphics_preference:theory"
                    )
                    penalized_count += 1

        for tid, cid, day, session, room_id, var in iter_lab_session_variables(context):
            req = context.variables.lab.requirements.get(cid)
            if not req:
                continue

            if req.course_code in target_courses:
                if room_id not in preferred_rooms:
                    register_objective_penalty(
                        context,
                        var,
                        weight=penalty_weight,
                        tag="engineering_graphics_preference:lab"
                    )
                    penalized_count += 1

        if penalized_count == 0:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no_non_preferred_assignments_found"})

        return self._result(
            ConstraintStatus.APPLIED,
            {
                "penalized_assignments_potential": penalized_count,
                "preferred_rooms": list(preferred_rooms),
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


def build_engineering_graphics_preference_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> EngineeringGraphicsPreferenceConstraint:
    return EngineeringGraphicsPreferenceConstraint(metadata=metadata, params=params or {})
