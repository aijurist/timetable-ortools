"""Batch-interleave: half-cohort lab scheduling.

Each section's students form two fixed halves — Half-A (Batch 1) and Half-B
(Batch 2) — consistent across every lab course. The rule enforced here is that at
any lab (day, session) cell each half may attend at most one course. Consequences:

* Batch 1 of course A and Batch 1 of course B cannot share a cell (same students).
* Batch 2 of A and Batch 2 of B cannot share a cell (same students).
* Batch 1 of A and Batch 2 of B CAN share a cell (disjoint halves, different rooms).

This lets two different courses interleave their opposite batches in one slot, so a
section finishes both courses' labs in fewer slots without any student being double
booked. Non-batched courses (whole section) occupy both halves at once.

The constraint owns lab conflicts for the sections it manages; ``group_non_overlap``
must therefore skip lab sessions for those sections (it handles theory only there).
Disabled by default; enable via config. A course is treated as batched when its
student_count exceeds ``batch_threshold`` (default 35).
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal, iter_lab_session_variables, resolve_group_slot_map

Cell = Tuple[int, str]  # (day_idx, session_name)
Section = Tuple[str, object]  # (department, section_id)


def _sanitize(value: object) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value))


class BatchInterleaveConstraint(Constraint):
    """Half-cohort no-overlap for section labs (allows opposite-batch sharing)."""

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        params = self.params or {}
        batch_threshold = int(params.get("batch_threshold", 35))

        lab_block = context.variables.lab
        assignments = getattr(lab_block, "assignments", None)
        if not assignments:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no lab assignments"})
        model = context.model
        requirements = getattr(lab_block, "requirements", {}) or {}
        lab_session_to_theory = dict(getattr(getattr(context.data.raw, "time", None), "lab_session_to_theory", {}) or {})

        # room vars per (section, course_id, cell)
        cell_vars: Dict[Section, Dict[str, Dict[Cell, List[cp_model.IntVar]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        for _tid, course_id, day_idx, session_name, _room_id, var in iter_lab_session_variables(context):
            req = requirements.get(course_id)
            if req is None:
                continue
            section = (getattr(req, "department", ""), getattr(req, "section_id", None))
            cell_vars[section][course_id][(day_idx, session_name)].append(var)

        if not cell_vars:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no lab cells"})

        # Theory presence per (section, day_idx, slot): whole-section, so it blocks a
        # lab in EITHER half at any lab session that overlaps that theory slot.
        theory_block = context.variables.theory
        group_slot_map = resolve_group_slot_map(context)
        group_to_section: Dict[str, Section] = {}
        for _cid, req in getattr(theory_block, "course_requirements", {}).items():
            gid = getattr(req, "group_id", None)
            if gid is not None:
                group_to_section[gid] = (getattr(req, "department", ""), getattr(req, "section_id", None))
        theory_slot_vars: Dict[Section, Dict[Tuple[int, int], List[cp_model.IntVar]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for group_id, day_map in group_slot_map.items():
            section = group_to_section.get(group_id)
            if section is None:
                continue
            for day_idx, slot_map in day_map.items():
                for slot_idx, var in slot_map.items():
                    theory_slot_vars[section][(day_idx, slot_idx)].append(var)

        sections_done = 0
        interleave_pairs = 0
        for section, courses in cell_vars.items():
            # Per (course, cell): presence + half assignment.
            halfA_by_cell: Dict[Cell, List[cp_model.IntVar]] = defaultdict(list)
            halfB_by_cell: Dict[Cell, List[cp_model.IntVar]] = defaultdict(list)
            managed = False
            for course_id, cells in courses.items():
                req = requirements.get(course_id)
                if req is None:
                    continue
                students = int(getattr(req, "student_count", 0) or 0)
                base = max(1, int(getattr(req, "required_sessions", 0) or 0))
                is_batched = students > batch_threshold

                halfA_terms: List[cp_model.IntVar] = []
                halfB_terms: List[cp_model.IntVar] = []
                for cell, vars_list in cells.items():
                    room_sum = sum(vars_list)
                    tag = f"{_sanitize(course_id)}_{cell[0]}_{cell[1]}"
                    if is_batched:
                        # One room per cell (no same-course parallel); pick a half.
                        present = model.NewBoolVar(f"bi_present_{tag}")
                        model.Add(room_sum == present)
                        hA = model.NewBoolVar(f"bi_A_{tag}")
                        hB = model.NewBoolVar(f"bi_B_{tag}")
                        model.Add(hA + hB == present)
                        halfA_terms.append(hA)
                        halfB_terms.append(hB)
                        halfA_by_cell[cell].append(hA)
                        halfB_by_cell[cell].append(hB)
                        managed = True
                    else:
                        # Whole section occupies BOTH halves at its cells.
                        present = model.NewBoolVar(f"bi_present_{tag}")
                        model.Add(room_sum >= present)
                        model.Add(room_sum <= len(vars_list) * present)
                        halfA_by_cell[cell].append(present)
                        halfB_by_cell[cell].append(present)
                # Batched course: each half attends it exactly base times.
                if is_batched and halfA_terms:
                    model.Add(sum(halfA_terms) == base)
                    model.Add(sum(halfB_terms) == base)

            if not managed:
                continue
            # Fold THEORY into each lab cell: if the section has theory during any theory
            # slot the lab session spans, both halves are busy -> add that presence to both.
            sect_theory = theory_slot_vars.get(section, {})
            for cell in list(set(halfA_by_cell) | set(halfB_by_cell)):
                day_idx, session_name = cell
                spanned = lab_session_to_theory.get(session_name, ())
                theory_vars = []
                for slot_idx in spanned:
                    theory_vars.extend(sect_theory.get((day_idx, slot_idx), []))
                if theory_vars:
                    lit = build_presence_literal(
                        model, theory_vars, f"bi_theory_{_sanitize(section)}_{day_idx}_{session_name}"
                    )
                    if lit is not None:
                        halfA_by_cell[cell].append(lit)
                        halfB_by_cell[cell].append(lit)
            # Half no-overlap: each half attends <=1 course per cell.
            for cell in set(halfA_by_cell) | set(halfB_by_cell):
                a = halfA_by_cell.get(cell, [])
                b = halfB_by_cell.get(cell, [])
                if len(a) > 1:
                    model.Add(sum(a) <= 1)
                    interleave_pairs += 1
                if len(b) > 1:
                    model.Add(sum(b) <= 1)
            sections_done += 1

        status = ConstraintStatus.APPLIED if sections_done else ConstraintStatus.SKIPPED
        return self._result(
            status,
            {"sections_managed": sections_done, "cell_conflict_clauses": interleave_pairs},
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


def build_batch_interleave_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> BatchInterleaveConstraint:
    return BatchInterleaveConstraint(metadata=metadata, params=params)


__all__ = ["BatchInterleaveConstraint", "build_batch_interleave_constraint"]
