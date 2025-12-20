"""Restrict POP (Part-time/On-call/Particular) staff to their preferred days.

This constraint reads a CSV file containing staff members who can only teach on
specific days of the week. It blocks any assignment on days not in their
preferred day list. This is a hard constraint with no soft violations.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, Mapping, Optional, Set, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    ensure_extra_bucket,
    iter_lab_session_variables,
    iter_course_timeslot_variables,
    resolve_day_pattern,
)


class PopDayConstraint(Constraint):
    """Block POP staff from teaching on days outside their preferred list."""

    def __init__(
        self,
        metadata: ConstraintMetadata,
        params: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(metadata, params=params)
        params = params or {}
        self._pop_csv_path = str(params.get("pop_csv_path", "data/pop.csv"))
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
        working_days = tuple(
            getattr(context.data.raw.time, "working_days", tuple())
        ) or ("monday", "tuesday", "wed", "thur", "fri", "saturday")

        # Build mapping: teacher_id -> allowed day indices
        teacher_allowed_days = self._build_teacher_day_mapping(pop_data, working_days)
        if not teacher_allowed_days:
            return ConstraintApplicationResult(
                name=self.metadata.name,
                domain=self.metadata.category,
                priority=self.metadata.priority,
                enabled=True,
                status=ConstraintStatus.SKIPPED,
                details={"constraints": 0, "reason": "No valid teacher day mappings found"},
            )

        constraints_added = 0
        teachers_constrained = set()

        # Process lab variables
        for teacher_id, course_id, day_idx, session, room, var in iter_lab_session_variables(context):
            normalized_tid = self._normalize_teacher_id(teacher_id)
            if normalized_tid not in teacher_allowed_days:
                continue
            allowed_days = teacher_allowed_days[normalized_tid]
            if day_idx not in allowed_days:
                model.Add(var == 0)
                constraints_added += 1
                teachers_constrained.add(normalized_tid)

        # Process theory variables
        for teacher_id, course_id, day_idx, slot_idx, var in iter_course_timeslot_variables(context):
            normalized_tid = self._normalize_teacher_id(teacher_id)
            if normalized_tid not in teacher_allowed_days:
                continue
            allowed_days = teacher_allowed_days[normalized_tid]
            if day_idx not in allowed_days:
                model.Add(var == 0)
                constraints_added += 1
                teachers_constrained.add(normalized_tid)

        # Record for debugging
        if constraints_added:
            extra = ensure_extra_bucket(context, "pop_day")
            extra["constraints_added"] = constraints_added
            extra["teachers_constrained"] = list(teachers_constrained)
            extra["teacher_allowed_days"] = {
                tid: list(days) for tid, days in teacher_allowed_days.items()
            }

        status = ConstraintStatus.APPLIED if constraints_added else ConstraintStatus.SKIPPED
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details={
                "constraints": constraints_added,
                "teachers_constrained": len(teachers_constrained),
                "pop_teachers_loaded": len(teacher_allowed_days),
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

    def _build_teacher_day_mapping(
        self,
        pop_data: list[dict[str, str]],
        working_days: Tuple[str, ...],
    ) -> Dict[str, Set[int]]:
        """Build mapping from teacher ID to allowed day indices."""
        day_name_to_index = {
            self._normalize_day(day): idx
            for idx, day in enumerate(working_days)
        }

        teacher_days: Dict[str, Set[int]] = {}
        for row in pop_data:
            # Get teacher ID and normalize it (handle float like "413.0" -> "413")
            raw_tid = row.get("Teacher ID", "").strip()
            if not raw_tid:
                continue
            teacher_id = self._normalize_teacher_id(raw_tid)

            # Get preferred days (support up to 3 preferred days)
            day1 = self._normalize_day(row.get("Preferred Day 1", "").strip())
            day2 = self._normalize_day(row.get("Preferred Day 2", "").strip())
            day3 = self._normalize_day(row.get("Preferred Day 3", "").strip())

            allowed_indices = set()
            if day1 and day1 != "-" and day1 in day_name_to_index:
                allowed_indices.add(day_name_to_index[day1])
            if day2 and day2 != "-" and day2 in day_name_to_index:
                allowed_indices.add(day_name_to_index[day2])
            if day3 and day3 != "-" and day3 in day_name_to_index:
                allowed_indices.add(day_name_to_index[day3])

            if allowed_indices:
                if teacher_id in teacher_days:
                    # Merge if teacher appears multiple times (multiple courses)
                    teacher_days[teacher_id].update(allowed_indices)
                else:
                    teacher_days[teacher_id] = allowed_indices

        self._logger.info(
            "Loaded %d POP teacher day restrictions from CSV",
            len(teacher_days),
        )
        return teacher_days

    @staticmethod
    def _normalize_teacher_id(tid: str) -> str:
        """Normalize teacher ID to handle float representations like '413.0' -> '413'."""
        if not tid:
            return tid
        tid_str = str(tid).strip()
        # Handle float representation (e.g., "413.0" -> "413")
        try:
            float_val = float(tid_str)
            if float_val.is_integer():
                return str(int(float_val))
        except ValueError:
            pass
        return tid_str

    @staticmethod
    def _normalize_day(day: str) -> str:
        """Normalize day name for case-insensitive matching."""
        if not day:
            return ""
        normalized = day.strip().lower()
        # Handle common abbreviations
        day_aliases = {
            "monday": "monday",
            "mon": "monday",
            "tuesday": "tuesday",
            "tue": "tuesday",
            "tues": "tuesday",
            "wednesday": "wed",
            "wed": "wed",
            "thursday": "thur",
            "thur": "thur",
            "thu": "thur",
            "friday": "fri",
            "fri": "fri",
            "saturday": "saturday",
            "sat": "saturday",
            "sunday": "sunday",
            "sun": "sunday",
        }
        return day_aliases.get(normalized, normalized)


def build_pop_day_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> PopDayConstraint:
    return PopDayConstraint(metadata=metadata, params=params)


__all__ = ["build_pop_day_constraint", "PopDayConstraint"]
