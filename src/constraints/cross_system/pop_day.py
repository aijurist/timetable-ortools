"""Apply POP staff availability rules for theory and lab assignments.

Theory assignments are hard-limited to the configured POP day/time windows.
Lab assignments remain schedulable by default, with penalties that prefer the
POP window, then preferred days, then ``alternative_lab_days`` from the CSV.
Rows with ``hard_lab_limit`` set also hard-limit lab assignments to the POP
window.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Mapping, Optional

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    ensure_extra_bucket,
    iter_lab_session_variables,
    iter_course_timeslot_variables,
    register_objective_penalty,
)
from ...data.pop_availability import (
    DEFAULT_POP_END_TIME,
    DEFAULT_POP_START_TIME,
    build_pop_availability,
    normalize_day_label,
    normalize_teacher_id,
)


class PopDayConstraint(Constraint):
    """Hard-limit POP theory slots and optionally hard-limit POP lab availability."""

    def __init__(
        self,
        metadata: ConstraintMetadata,
        params: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(metadata, params=params)
        params = params or {}
        self._pop_csv_path = str(params.get("pop_csv_path", "data/pop.csv"))
        self._default_start_time = params.get("default_start_time", DEFAULT_POP_START_TIME)
        self._default_end_time = params.get("default_end_time", DEFAULT_POP_END_TIME)
        self._lab_preferred_day_penalty = max(0, int(params.get("lab_preferred_day_penalty", 3)))
        self._lab_alternative_day_penalty = max(0, int(params.get("lab_alternative_day_penalty", 5)))
        self._lab_other_day_penalty = max(0, int(params.get("lab_other_day_penalty", 20)))
        self._logger = logging.getLogger(__name__)

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        # Load POP staff data from CSV
        pop_data = self._load_pop_data(context)
        if not pop_data:
            return ConstraintApplicationResult(
                name=self.metadata.name,
                domain=self.metadata.category,
                priority=self.metadata.priority,
                enabled=True,
                status=ConstraintStatus.SKIPPED,
                details={"constraints": 0, "reason": "No POP data loaded or file not found"},
            )

        model = context.model

        teacher_availability = build_pop_availability(
            pop_data,
            default_start_time=self._default_start_time,
            default_end_time=self._default_end_time,
        )
        if not teacher_availability:
            return ConstraintApplicationResult(
                name=self.metadata.name,
                domain=self.metadata.category,
                priority=self.metadata.priority,
                enabled=True,
                status=ConstraintStatus.SKIPPED,
                details={"constraints": 0, "reason": "No valid teacher availability mappings found"},
            )

        # Course variables can use different day patterns (e.g., Tue-Sat). Comparing by raw
        # day-index against a single global working-days list can misclassify "Saturday".
        lab_day_patterns = getattr(context.variables.lab, "day_patterns", {}) or {}
        theory_day_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
        default_working_days = tuple(
            getattr(context.data.raw.time, "working_days", tuple())
        ) or ("monday", "tuesday", "wed", "thur", "fri", "saturday")

        hard_constraints_added = 0
        hard_lab_constraints_added = 0
        lab_penalty_terms = 0
        theory_teachers_constrained = set()
        lab_teachers_hard_constrained = set()
        lab_teachers_penalized = set()
        lab_sessions = getattr(context.data.raw.time, "lab_sessions", {}) or {}

        # Process theory variables. Variable creation already prunes these when
        # pop_day is enabled; this guard keeps the constraint correct for older
        # snapshots/tests that may still contain invalid variables.
        for teacher_id, course_id, day_idx, slot_idx, var in iter_course_timeslot_variables(context):
            normalized_tid = normalize_teacher_id(teacher_id)
            availability = teacher_availability.get(normalized_tid)
            if availability is None:
                continue

            course_day_pattern = theory_day_patterns.get(course_id) or default_working_days
            if day_idx < 0 or day_idx >= len(course_day_pattern):
                continue
            actual_day_name = normalize_day_label(course_day_pattern[day_idx])
            theory_slots = getattr(context.variables.theory, "theory_slot_labels", tuple()) or ()
            slot_label = theory_slots[slot_idx] if slot_idx < len(theory_slots) else ""

            if not availability.allows_theory(actual_day_name, slot_label):
                model.Add(var == 0)
                hard_constraints_added += 1
                theory_teachers_constrained.add(normalized_tid)

        # Process lab variables as soft preferences only. Labs remain schedulable
        # outside the POP theory window, with alternative_lab_days as the first
        # fallback after preferred days.
        for teacher_id, course_id, day_idx, session, room, var in iter_lab_session_variables(context):
            normalized_tid = normalize_teacher_id(teacher_id)
            availability = teacher_availability.get(normalized_tid)
            if availability is None:
                continue

            course_day_pattern = lab_day_patterns.get(course_id) or default_working_days
            if day_idx < 0 or day_idx >= len(course_day_pattern):
                continue
            actual_day_name = normalize_day_label(course_day_pattern[day_idx])
            session_detail = lab_sessions.get(session)
            time_range = getattr(session_detail, "time_range", "")
            tier = availability.lab_preference_tier(actual_day_name, time_range)
            if availability.hard_lab_limit and tier != "preferred_window":
                model.Add(var == 0)
                hard_lab_constraints_added += 1
                lab_teachers_hard_constrained.add(normalized_tid)
                continue

            penalty_weight = self._lab_penalty_weight(tier)
            if penalty_weight <= 0:
                continue

            register_objective_penalty(
                context,
                var,
                weight=penalty_weight,
                tag=f"pop_lab:{tier}",
            )
            lab_penalty_terms += 1
            lab_teachers_penalized.add(normalized_tid)

        # Record for debugging
        if hard_constraints_added or hard_lab_constraints_added or lab_penalty_terms:
            extra = ensure_extra_bucket(context, "pop_day")
            extra["hard_theory_constraints_added"] = hard_constraints_added
            extra["hard_lab_constraints_added"] = hard_lab_constraints_added
            extra["lab_penalty_terms"] = lab_penalty_terms
            extra["theory_teachers_constrained"] = sorted(theory_teachers_constrained)
            extra["lab_teachers_hard_constrained"] = sorted(lab_teachers_hard_constrained)
            extra["lab_teachers_penalized"] = sorted(lab_teachers_penalized)
            extra["teacher_availability"] = {
                tid: {
                    "preferred_days": sorted(availability.preferred_days),
                    "alternative_lab_days": sorted(availability.alternative_lab_days),
                    "hard_lab_limit": availability.hard_lab_limit,
                    "time_windows": list(availability.time_windows),
                    "day_time_windows": {
                        day: list(windows)
                        for day, windows in availability.day_time_windows
                    },
                    "lab_day_time_windows": {
                        day: list(windows)
                        for day, windows in availability.lab_day_time_windows
                    },
                }
                for tid, availability in teacher_availability.items()
            }

        status = ConstraintStatus.APPLIED if (
            hard_constraints_added or hard_lab_constraints_added or lab_penalty_terms
        ) else ConstraintStatus.SKIPPED
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details={
                "hard_theory_constraints": hard_constraints_added,
                "hard_lab_constraints": hard_lab_constraints_added,
                "lab_penalty_terms": lab_penalty_terms,
                "theory_teachers_constrained": len(theory_teachers_constrained),
                "lab_teachers_hard_constrained": len(lab_teachers_hard_constrained),
                "lab_teachers_penalized": len(lab_teachers_penalized),
                "pop_teachers_loaded": len(teacher_availability),
            },
        )

    def _load_pop_data(
        self, context: ConstraintContext
    ) -> list[dict[str, str]]:
        """Load POP staff data from the CSV file."""
        base_dir = getattr(context.config, "base_dir", None)
        if base_dir:
            csv_path = Path(base_dir) / self._pop_csv_path
        else:
            csv_path = Path(self._pop_csv_path)

        if not csv_path.exists():
            # Try relative to current working directory
            csv_path = Path.cwd() / self._pop_csv_path
            if not csv_path.exists():
                self._logger.warning("POP CSV file not found: %s", self._pop_csv_path)
                return []

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except Exception as exc:
            self._logger.error("Failed to load POP CSV: %s", exc)
            return []

    def _lab_penalty_weight(self, tier: str) -> int:
        if tier == "preferred_window":
            return 0
        if tier == "preferred_day":
            return self._lab_preferred_day_penalty
        if tier == "alternative_day":
            return self._lab_alternative_day_penalty
        return self._lab_other_day_penalty


def build_pop_day_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> PopDayConstraint:
    return PopDayConstraint(metadata=metadata, params=params)


__all__ = ["build_pop_day_constraint", "PopDayConstraint"]
