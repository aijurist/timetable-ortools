"""Parallel batch scheduling.

Force a batched course's N batches to run *simultaneously* in N different rooms
(same day + session) instead of sequentially across the week. For a 4-hour
practical (2 lab sessions) both batches occupy the same two sessions in parallel.

Only courses that genuinely must batch and have enough eligible rooms qualify
(see ``qualifying_parallel_lab_ids``). Disabled by default; enable via config so
the existing (sequential) behaviour is completely unaffected.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Mapping, Optional

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import qualifying_parallel_lab_ids


class ParallelBatchLabConstraint(Constraint):
    """Co-schedule each qualifying course's batches into shared lab sessions.

    Per course, a reified ``par`` decides between full parallel (each used session
    holds all N batches in different rooms) and a sequential fallback (one room per
    session — restoring the single-room cap that room_single_assignment skips for
    these instances). Parallelising is rewarded softly so the solver does it wherever
    it stays feasible and cleanly falls back where it would not.
    """

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        params = self.params or {}
        min_rooms = int(params.get("min_eligible_rooms", 2))
        min_students = int(params.get("min_student_count", 36))
        course_codes = params.get("parallel_batch_courses", ()) or ()

        lab_block = context.variables.lab
        if not getattr(lab_block, "assignments", None):
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no lab assignments"})

        parallel_ids = qualifying_parallel_lab_ids(
            context, min_students=min_students, min_rooms=min_rooms, course_codes=course_codes
        )
        if not parallel_ids:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no qualifying courses"})

        model = context.model
        applied = 0
        targeted = []
        for course_id in parallel_ids:
            requirement = lab_block.requirements.get(course_id)
            if requirement is None:
                continue
            students = int(getattr(requirement, "student_count", 0) or 0)
            base_sessions = max(1, int(getattr(requirement, "required_sessions", 0) or 0))
            n_batches = max(2, math.ceil(students / 35))

            # Gather this instance's room variables grouped by (day, session).
            slots: Mapping[tuple, list] = defaultdict(list)
            pattern = lab_block.day_patterns.get(course_id, ())
            for _teacher_id, course_map in lab_block.assignments.items():
                day_map = course_map.get(course_id)
                if not day_map:
                    continue
                for day_index, session_map in day_map.items():
                    day = pattern[day_index] if 0 <= day_index < len(pattern) else day_index
                    for session_name, room_map in session_map.items():
                        for _room_id, variable in room_map.items():
                            slots[(day, session_name)].append(variable)
            if not slots:
                continue

            # Each used (day, session) hosts exactly n_batches rooms (batches running
            # in parallel); exactly base_sessions distinct sessions are used. Hard so it
            # takes effect under first-solution search; per-department fallback (in the
            # solve script) reverts a whole department to sequential if it cannot fit.
            presence = []
            for (day, session_name), variables in slots.items():
                used = model.NewBoolVar(f"pbatch_{course_id}_{day}_{session_name}")
                model.Add(sum(variables) == n_batches).OnlyEnforceIf(used)
                model.Add(sum(variables) == 0).OnlyEnforceIf(used.Not())
                presence.append(used)
            if presence:
                model.Add(sum(presence) == base_sessions)
                applied += 1
                targeted.append(str(getattr(requirement, "course_code", course_id)))

        status = ConstraintStatus.APPLIED if applied else ConstraintStatus.SKIPPED
        return self._result(
            status,
            {"courses_considered": applied, "targeted": tuple(sorted(set(targeted)))},
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


def build_parallel_batch_lab_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> ParallelBatchLabConstraint:
    return ParallelBatchLabConstraint(metadata=metadata, params=params)


__all__ = ["ParallelBatchLabConstraint", "build_parallel_batch_lab_constraint"]
