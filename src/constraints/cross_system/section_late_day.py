"""Section-based late-day cap.

Keep each section's week "mostly done before 3pm": at most ``max_late_days`` days
per section may run into the late window (theory slots 7-8 = 3:10-5:00pm, lab
session L5 = 3:10-4:50pm). The other days must finish by 3pm.

Modes:
* ``hard``  -> a hard cap ``sum(late_days) <= max_late_days`` per section. Works in
  first-solution search, so it constrains both the phase-1 lab placement and the
  phase-2 theory placement of the seeded solve.
* ``soft``  -> penalise each late day beyond the cap. Only bites during optimisation
  (phase 2 theory); phase-1 labs are unaffected.

Disabled by default; enable via config.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    iter_lab_session_variables,
    register_objective_penalty,
    resolve_group_slot_map,
)


def _sanitize(value: object) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value))


class SectionLateDayConstraint(Constraint):
    """Cap the number of after-3pm days per section (hard or soft)."""

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        params = self.params or {}
        late_theory_slots = {int(s) for s in params.get("late_theory_slots", (7, 8))}
        late_lab_sessions = {str(s).strip() for s in params.get("late_lab_sessions", ("L5",))}
        max_late_days = int(params.get("max_late_days", 2))
        # Single-section departments (workshop-dense, one cohort) get a looser cap:
        # their labs often must run late and there is no parallel section to balance.
        single_section_max_late_days = int(
            params.get("single_section_max_late_days", max_late_days + 1)
        )
        mode = str(params.get("mode", "soft")).strip().lower()
        penalty_weight = max(1, int(params.get("soft_penalty_weight", 40)))
        # Optional DIRECT penalty per theory activity placed in a late slot (7-8), on top of
        # the per-late-day cap. Unlike the day cap, this discourages late theory even on days
        # already made late by a lab -> steers theory earlier. 0 disables it (default).
        late_theory_penalty_weight = int(params.get("late_theory_penalty_weight", 0))
        late_theory_vars: List[cp_model.IntVar] = []

        model = context.model
        theory_block = context.variables.theory
        lab_block = context.variables.lab
        group_slot_map = resolve_group_slot_map(context)
        if not group_slot_map:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no theory groups"})

        # A "section" is (department, section_id) — multiple course-groups share it.
        # Map each theory group_id and each lab course_id to its section key so the cap
        # applies to the section's whole day, not to individual courses.
        group_to_section: Dict[str, Tuple[str, object]] = {}
        for _cid, req in getattr(theory_block, "course_requirements", {}).items():
            gid = getattr(req, "group_id", None)
            if gid is not None:
                group_to_section[gid] = (getattr(req, "department", ""), getattr(req, "section_id", None))
        course_to_section: Dict[str, Tuple[str, object]] = {}
        for course_id, req in getattr(lab_block, "requirements", {}).items():
            course_to_section[course_id] = (getattr(req, "department", ""), getattr(req, "section_id", None))

        # Late literals per (section, day).
        late_by_group_day: Dict[Tuple[str, object], Dict[int, List[cp_model.IntVar]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # THEORY: slots 7-8, keyed via the group's section.
        for group_id, day_map in group_slot_map.items():
            section = group_to_section.get(group_id)
            if section is None:
                continue
            for day_idx, slot_map in day_map.items():
                for slot_idx, var in slot_map.items():
                    if slot_idx in late_theory_slots:
                        late_by_group_day[section][day_idx].append(var)
                        late_theory_vars.append(var)

        # LAB: session L5 room vars, keyed via the course's section.
        for _tid, course_id, day_idx, session_name, _room_id, var in iter_lab_session_variables(context):
            if session_name not in late_lab_sessions:
                continue
            section = course_to_section.get(course_id)
            if section is None:
                continue
            late_by_group_day[section][day_idx].append(var)

        if not late_by_group_day:
            return self._result(ConstraintStatus.SKIPPED, {"reason": "no late-window variables"})

        # Count sections per department to pick each section's cap.
        sections_per_dept: Dict[str, set] = defaultdict(set)
        for (dept, section_id) in late_by_group_day:
            sections_per_dept[dept].add(section_id)

        hard_caps = 0
        penalties = 0
        for group_id, day_map in late_by_group_day.items():
            late_days: List[cp_model.IntVar] = []
            for day_idx, literals in day_map.items():
                if not literals:
                    continue
                late_day = model.NewBoolVar(f"lateday_{_sanitize(group_id)}_d{day_idx}")
                # late_day = 1 if ANY late activity occurs that day.
                for lit in literals:
                    model.Add(late_day >= lit)
                model.Add(late_day <= sum(literals))
                late_days.append(late_day)
            if not late_days:
                continue

            dept = group_id[0]
            cap = (
                single_section_max_late_days
                if len(sections_per_dept.get(dept, ())) <= 1
                else max_late_days
            )

            if mode == "hard":
                model.Add(sum(late_days) <= cap)
                hard_caps += 1
            else:
                # Penalise every late day beyond the cap.
                excess = model.NewIntVar(0, len(late_days), f"lateexcess_{_sanitize(group_id)}")
                model.Add(excess >= sum(late_days) - cap)
                register_objective_penalty(
                    context, excess, penalty_weight, tag=f"section_late_day:{group_id}"
                )
                penalties += 1

        # Direct late-theory penalty: charge for every theory activity in a late slot, so the
        # solver pulls theory into earlier slots regardless of the per-day cap.
        if late_theory_penalty_weight > 0 and late_theory_vars:
            late_theory_count = model.NewIntVar(0, len(late_theory_vars), "late_theory_count")
            model.Add(late_theory_count == sum(late_theory_vars))
            register_objective_penalty(
                context, late_theory_count, late_theory_penalty_weight,
                tag="section_late_day:late_theory",
            )

        status = ConstraintStatus.APPLIED if (hard_caps or penalties) else ConstraintStatus.SKIPPED
        return self._result(
            status,
            {
                "mode": mode,
                "max_late_days": max_late_days,
                "sections_capped": hard_caps,
                "sections_penalised": penalties,
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


def build_section_late_day_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> SectionLateDayConstraint:
    return SectionLateDayConstraint(metadata=metadata, params=params)


__all__ = ["SectionLateDayConstraint", "build_section_late_day_constraint"]
