"""Stable same-course pairing for DBMS/OOPS combined lab blocks."""

from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Mapping, Optional, Tuple

from ortools.sat.python import cp_model

from ...utils.time_utils import DayNormalizer
from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import register_objective_penalty


def _slug(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_") or "item"


class CombinedLabConstraint(Constraint):
    """Keep a solver-selected section pair together for every lab block.

    Two instances of the same configured course may share one large ANEW room.
    If they share any room/session, they must use identical day/session/room cells
    for all four blocks.  Pairing is maximized softly, while solo scheduling
    remains possible when fixed staff or room occupancy makes a pair infeasible.
    """

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        model = context.model
        lab_block = context.variables.lab
        cfg = getattr(getattr(context.config, "model", None), "combined_lab_courses", {}) or {}
        codes = frozenset(
            str(code).strip().upper() for code in cfg.get("course_codes", ()) if str(code).strip()
        )
        if not codes:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no combined-lab courses configured"})
        if not getattr(lab_block, "assignments", None):
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no lab assignments"})

        same_department_only = bool(self.params.get("same_department_only", False))
        enforce_pairing = bool(self.params.get("enforce_stable_pairing", True))
        solo_weight = max(0, int(self.params.get("solo_penalty_weight", 1000) or 0))
        max_pair_pool = max(0, int(self.params.get("max_pair_pool", 8) or 0))

        requirements = getattr(lab_block, "requirements", {}) or {}
        instance_cells: Dict[str, Dict[Tuple[str, str, str], cp_model.IntVar]] = {}
        instance_codes: Dict[str, str] = {}
        instance_departments: Dict[str, str] = {}
        instance_teachers: Dict[str, str] = {}

        for teacher_id, course_map in lab_block.assignments.items():
            for instance_id, day_map in course_map.items():
                requirement = requirements.get(instance_id)
                code = str(getattr(requirement, "course_code", "")).strip().upper()
                if requirement is None or code not in codes:
                    continue
                pattern = tuple(lab_block.day_patterns.get(instance_id, ()))
                cells: Dict[Tuple[str, str, str], cp_model.IntVar] = {}
                for day_index, session_map in day_map.items():
                    raw_day = pattern[day_index] if 0 <= day_index < len(pattern) else f"day_{day_index}"
                    day = DayNormalizer.normalize_day_name(raw_day) or str(raw_day).strip().lower()
                    for session_name, room_map in session_map.items():
                        for room_id, variable in room_map.items():
                            cells[(day, str(session_name), str(room_id))] = variable
                if not cells:
                    continue
                instance_cells[instance_id] = cells
                instance_codes[instance_id] = code
                instance_departments[instance_id] = str(getattr(requirement, "department", ""))
                instance_teachers[instance_id] = str(teacher_id)

        if not instance_cells:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no configured combined-lab instances"})

        allocations = tuple(
            getattr(getattr(context.data, "preprocessing", None), "combined_lab_allocations", ()) or ()
        )
        if allocations:
            locked_variables = 0
            locked_allocations = 0
            for allocation in allocations:
                if str(allocation.course_code).strip().upper() not in codes:
                    continue
                expected_cells = {
                    (
                        DayNormalizer.normalize_day_name(cell.day) or str(cell.day).strip().lower(),
                        str(cell.session_name),
                        str(cell.room_id),
                    )
                    for cell in allocation.cells
                }
                for instance_id in allocation.instance_ids:
                    cells = instance_cells.get(str(instance_id), {})
                    missing = expected_cells - cells.keys()
                    if missing:
                        raise ValueError(
                            f"Preallocated combined-lab cells are missing variables for {instance_id}: "
                            f"{sorted(missing)}"
                        )
                    for cell in expected_cells:
                        model.Add(cells[cell] == 1)
                        locked_variables += 1
                locked_allocations += 1
            return self._result(
                ConstraintStatus.APPLIED,
                {
                    "mode": "preallocated",
                    "instances": len(instance_cells),
                    "allocations": locked_allocations,
                    "locked_variables": locked_variables,
                    "candidate_pairs": 0,
                },
            )
        if not enforce_pairing:
            return self._result(
                ConstraintStatus.SKIPPED,
                {"reason": "stable pairing disabled", "instances": len(instance_cells)},
            )

        pools: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
        for instance_id in instance_cells:
            pool_key = (instance_codes[instance_id],)
            if same_department_only:
                pool_key = (instance_codes[instance_id], instance_departments[instance_id])
            pools[pool_key].append(instance_id)

        def bucketize(instances: List[str]) -> List[List[str]]:
            if not max_pair_pool or len(instances) <= max_pair_pool:
                return [sorted(instances)]
            by_department: Dict[str, List[str]] = defaultdict(list)
            for instance_id in sorted(instances):
                by_department[instance_departments[instance_id]].append(instance_id)
            interleaved: List[str] = []
            queues = list(by_department.values())
            while any(queues):
                for queue in queues:
                    if queue:
                        interleaved.append(queue.pop(0))
            return [interleaved[index:index + max_pair_pool] for index in range(0, len(interleaved), max_pair_pool)]

        partner_literals: Dict[str, List[cp_model.IntVar]] = defaultdict(list)
        candidate_pairs = 0
        identity_constraints = 0
        for instances in (bucket for pool in pools.values() for bucket in bucketize(pool)):
            for first_id, second_id in combinations(instances, 2):
                if instance_teachers[first_id] == instance_teachers[second_id]:
                    continue
                first_cells = instance_cells[first_id]
                second_cells = instance_cells[second_id]
                shared_cells = first_cells.keys() & second_cells.keys()
                if not shared_cells:
                    continue
                together = model.NewBoolVar(f"combined_pair_{_slug(first_id)}__{_slug(second_id)}")
                partner_literals[first_id].append(together)
                partner_literals[second_id].append(together)
                candidate_pairs += 1

                for cell in shared_cells:
                    first_var = first_cells[cell]
                    second_var = second_cells[cell]
                    # Sharing any cell selects this permanent partnership.
                    model.Add(first_var + second_var - 1 <= together)
                    model.Add(first_var == second_var).OnlyEnforceIf(together)
                    identity_constraints += 1
                for cell in first_cells.keys() - second_cells.keys():
                    model.Add(first_cells[cell] == 0).OnlyEnforceIf(together)
                for cell in second_cells.keys() - first_cells.keys():
                    model.Add(second_cells[cell] == 0).OnlyEnforceIf(together)

        solo_terms = 0
        for instance_id, literals in partner_literals.items():
            model.Add(sum(literals) <= 1)
            if solo_weight:
                solo = model.NewBoolVar(f"combined_solo_{_slug(instance_id)}")
                model.Add(sum(literals) + solo == 1)
                register_objective_penalty(context, solo, solo_weight, tag="combined_lab:solo")
                solo_terms += 1

        status = ConstraintStatus.APPLIED if candidate_pairs else ConstraintStatus.SKIPPED
        return self._result(
            status,
            {
                "instances": len(instance_cells),
                "candidate_pairs": candidate_pairs,
                "identity_constraints": identity_constraints,
                "solo_penalty_terms": solo_terms,
                "same_department_only": same_department_only,
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


def build_combined_lab_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> CombinedLabConstraint:
    return CombinedLabConstraint(metadata=metadata, params=params)


__all__ = ["CombinedLabConstraint", "build_combined_lab_constraint"]
