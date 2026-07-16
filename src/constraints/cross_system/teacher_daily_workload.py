"""Limit each teacher's combined lab + theory workload per day."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal, register_objective_penalty

# CP-SAT linear expressions use integer coefficients.  Represent teacher load in
# half-hour units so a normal 50-minute theory cell is 2 units and one Kutty half
# is 1 unit.  Lab/fixed-schedule hours are converted with the same scale.
HALF_HOUR_UNITS_PER_HOUR = 2
HourLiteral = Tuple[cp_model.IntVar, int]


@dataclass(frozen=True)
class TeacherDailyWorkloadConfig:
	"""Configuration payload for the workload constraint."""

	max_daily_hours: int
	mode: str
	soft_cap_hours: Optional[int]
	penalty_weight: int
	excluded_departments: Tuple[str, ...]

	@staticmethod
	def from_params(params: Optional[Mapping[str, object]]) -> "TeacherDailyWorkloadConfig":
		params = params or {}
		max_hours = max(1, int(params.get("max_daily_hours", 5)))
		mode = str(params.get("mode", "hard")).strip().lower()
		if mode not in {"hard", "soft"}:
			mode = "hard"
		soft_cap_value = params.get("soft_cap_hours")
		soft_cap = None
		if soft_cap_value is not None:
			try:
				soft_cap = max(max_hours, int(soft_cap_value))
			except (TypeError, ValueError):  # pragma: no cover - defensive
				soft_cap = max_hours
		penalty_weight = int(params.get("soft_penalty_weight", 5))
		excluded_departments = tuple(str(d).strip() for d in params.get("excluded_departments", ()) if d)
		return TeacherDailyWorkloadConfig(
			max_daily_hours=max_hours,
			mode=mode,
			soft_cap_hours=soft_cap,
			penalty_weight=max(0, penalty_weight),
			excluded_departments=excluded_departments,
		)


@dataclass
class _ConstraintStats:
	teachers_considered: int = 0
	hard_constraints: int = 0
	soft_penalties: int = 0
	fixed_hours_applied: int = 0  # Count teachers with non-zero fixed hours

	def as_details(self) -> Mapping[str, int]:
		return {
			"teachers_considered": self.teachers_considered,
			"hard_constraints": self.hard_constraints,
			"soft_penalties": self.soft_penalties,
			"fixed_hours_applied": self.fixed_hours_applied,
		}


class TeacherDailyWorkloadConstraint(Constraint):
	"""Restrict teacher workload to the configured number of daily hours."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		config = TeacherDailyWorkloadConfig.from_params(self.params)
		theory_literals = _collect_theory_daily_literals(context)
		lab_literals = _collect_lab_daily_literals(context)
		teacher_ids = sorted(set(theory_literals) | set(lab_literals))
		if not teacher_ids:
			return _skip_result(self.metadata, "no teacher assignments present")

		working_days = tuple(getattr(context.data.raw.time, "working_days", tuple())) or ("monday",)
		stats = _ConstraintStats()

		blocking_mask = getattr(context.data.raw, "blocking_mask", None)
		fixed_hours_map = getattr(blocking_mask, "teacher_daily_fixed_hours", {}) if blocking_mask else {}

		excluded_teachers = set()
		if config.excluded_departments:
			preprocessing = getattr(context.data, "preprocessing", None)
			if preprocessing and preprocessing.normalized_instances:
				for key, instances in preprocessing.normalized_instances.items():
					dept_name = key.department
					cohort_token = f"{dept_name}_S{key.semester}"
					
					if (dept_name in config.excluded_departments or 
						cohort_token in config.excluded_departments):
						for inst in instances:
							excluded_teachers.add(inst.teacher_id)
			
			if excluded_teachers:
				context.logger.info(
					"Workload constraint disabled for %d teachers in excluded departments: %s",
					len(excluded_teachers), config.excluded_departments
				)

		for teacher_id in teacher_ids:
			day_names = set(theory_literals.get(teacher_id, {}).keys()) | set(
				lab_literals.get(teacher_id, {}).keys()
			)
			if not day_names:
				continue
			stats.teachers_considered += 1
			for day_name in _sort_day_names(day_names, working_days):
				terms = []
				for literal, half_hour_units in theory_literals.get(teacher_id, {}).get(day_name, tuple()):
					terms.append((literal, half_hour_units))
				for literal, hours in lab_literals.get(teacher_id, {}).get(day_name, tuple()):
					terms.append((literal, hours * HALF_HOUR_UNITS_PER_HOUR))
				if not terms:
					continue

				fixed_hours = fixed_hours_map.get((teacher_id, day_name), 0)
				if teacher_id in excluded_teachers:
					fixed_hours = 0
				if fixed_hours > 0:
					stats.fixed_hours_applied += 1
				fixed_units = int(fixed_hours) * HALF_HOUR_UNITS_PER_HOUR
				max_daily_units = config.max_daily_hours * HALF_HOUR_UNITS_PER_HOUR
				remaining_capacity = max_daily_units - fixed_units
				total_half_hours = sum(weight * literal for literal, weight in terms)
				
				# context.logger.info(
				# 	"Workload check: Teacher=%s Day=%s Fixed=%d Limit=%d Terms=%d",
				# 	teacher_id, day_name, fixed_hours, config.max_daily_hours, len(terms)
				# )

				if fixed_hours > 0:
					effective_limit = max(0, remaining_capacity)
					max_overage = 48
					overage = context.model.NewIntVar(0, max_overage, f"teacher_daily_overage_fix_{teacher_id}_{day_name}")
					context.model.Add(total_half_hours <= effective_limit + overage)

					weight = config.penalty_weight * 2 if config.penalty_weight > 0 else 10
					register_objective_penalty(
						context,
						overage,
						weight=weight,
						tag=f"teacher_spread:daily_workload_fix:{teacher_id}:{day_name}",
					)
					stats.soft_penalties += 1
					
					# context.logger.info(
					# 	"  -> Soft constraint applied: limit=%d + slack (fixed=%d)",
					# 	effective_limit, fixed_hours
					# )
				else:
					stats.hard_constraints += 1
					if config.mode == "soft" and config.soft_cap_hours:
						cap = max(0, config.soft_cap_hours * HALF_HOUR_UNITS_PER_HOUR - fixed_units)
						context.model.Add(total_half_hours <= cap)
						if cap > remaining_capacity:
							max_overage = cap - remaining_capacity
							overage = context.model.NewIntVar(0, max_overage, f"teacher_daily_overage_{teacher_id}_{day_name}")
							context.model.Add(total_half_hours - remaining_capacity <= overage)
							register_objective_penalty(
								context,
								overage,
								weight=config.penalty_weight,
								tag=f"teacher_spread:daily_workload:{teacher_id}:{day_name}",
							)
							stats.soft_penalties += 1
							# context.logger.info("  -> Configured Soft mode applied: cap=%d, buffer_limit=%d", cap, remaining_capacity)
						else:
							context.model.Add(total_half_hours <= remaining_capacity)
							# context.logger.info("  -> Configured Soft mode (hard equivalent) applied: limit=%d", remaining_capacity)
					else:
						context.model.Add(total_half_hours <= remaining_capacity)
						# context.logger.info("  -> Hard constraint applied: limit=%d", remaining_capacity)


		status = ConstraintStatus.APPLIED if stats.hard_constraints else ConstraintStatus.SKIPPED
		details = dict(stats.as_details())
		details.update(
			{
				"mode": config.mode,
				"max_daily_hours": config.max_daily_hours,
				"soft_cap_hours": config.soft_cap_hours,
				"workload_unit_minutes": 25,
				"ordinary_theory_units": HALF_HOUR_UNITS_PER_HOUR,
				"kutty_half_units": 1,
			}
		)
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=details,
		)


def _collect_theory_daily_literals(
	context: ConstraintContext,
) -> Mapping[str, Mapping[str, Tuple[HourLiteral, ...]]]:
	"""Collect pair-aware theory load in integer half-hour units.

	Every theory course variable initially contributes two units (one ordinary
	50-minute cell).  For an active Kutty pair, each shared cell then subtracts
	one unit from each partner teacher, leaving a net load of one unit/0.5 hour.
	For unequal-load pairs the shorter course identifies exactly the shared cells,
	so the longer course's remaining solo cells keep their full two-unit weight.

	This weighting is deliberately used only for workload.  ``teacher_overlap``
	continues to treat the same variable as occupying the full physical cell, which
	prevents another lab/theory assignment during either half of those 50 minutes.
	"""
	assignments = getattr(context.variables.theory, "assignments", {}) or {}
	day_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
	course_reqs = getattr(context.variables.theory, "course_requirements", {}) or {}
	# Combined lab-block courses are staff-less: they don't count toward teacher daily workload.
	combined_cfg = getattr(getattr(context.config, "model", None), "combined_lab_courses", {}) or {}
	combined_codes = frozenset(
		str(c).strip().upper() for c in combined_cfg.get("course_codes", ()) if str(c).strip()
	)
	collector: MutableMapping[str, MutableMapping[str, list[HourLiteral]]] = defaultdict(
		lambda: defaultdict(list)
	)
	# course -> (day index, slot index) -> (teacher, day label, course literal)
	course_slots: Dict[str, Dict[Tuple[int, int], Tuple[str, str, cp_model.IntVar]]] = defaultdict(dict)

	for teacher_id, course_map in assignments.items():
		for course_id, day_map in course_map.items():
			req = course_reqs.get(course_id)
			if req is not None and str(getattr(req, "course_code", "")).strip().upper() in combined_codes:
				continue
			pattern = day_patterns.get(course_id, tuple())
			for day_idx, slot_map in day_map.items():
				if not slot_map:
					continue
				day_name = _safe_day_name(pattern, day_idx)
				for slot_idx, literal in slot_map.items():
					collector[teacher_id][day_name].append(
						(literal, HALF_HOUR_UNITS_PER_HOUR)
					)
					course_slots[str(course_id)][(int(day_idx), int(slot_idx))] = (
						str(teacher_id),
						day_name,
						literal,
					)

	# ``bundled_theory`` runs at priority 2 and publishes its pair candidates before
	# this priority-9 workload constraint.  Each stored pair is short-course first;
	# for equal loads either course can act as the shared-cell marker.
	bundles = context.extra.get("bundles")
	if isinstance(bundles, Mapping):
		for bundle in bundles.values():
			if not isinstance(bundle, Mapping):
				continue
			for entry in bundle.get("pairs", ()) or ():
				if not isinstance(entry, (tuple, list)) or len(entry) < 3:
					continue
				pair_literal, short_course_id, long_course_id = entry[:3]
				short_map = course_slots.get(str(short_course_id), {})
				long_map = course_slots.get(str(long_course_id), {})
				for coordinate, short_entry in short_map.items():
					long_entry = long_map.get(coordinate)
					if long_entry is None:
						# Such a cell cannot be shared by bundled_theory, so it has no
						# half-hour discount to apply.
						continue
					short_teacher, short_day, short_slot_literal = short_entry
					long_teacher, long_day, _long_slot_literal = long_entry
					shared_literal = _build_and_literal(
						context.model,
						pair_literal,
						short_slot_literal,
						f"teacher_kutty_half_{short_course_id}_{long_course_id}_d{coordinate[0]}_s{coordinate[1]}",
					)
					collector[short_teacher][short_day].append((shared_literal, -1))
					collector[long_teacher][long_day].append((shared_literal, -1))

	return {
		teacher_id: {
			day_name: tuple(slots)
			for day_name, slots in day_map.items()
			if slots
		}
		for teacher_id, day_map in collector.items()
	}


def _build_and_literal(
	model: cp_model.CpModel,
	left: cp_model.IntVar,
	right: cp_model.IntVar,
	name: str,
) -> cp_model.IntVar:
	"""Return an exact Boolean conjunction for two CP-SAT literals."""

	literal = model.NewBoolVar(name)
	model.Add(literal <= left)
	model.Add(literal <= right)
	model.Add(literal >= left + right - 1)
	return literal



def _collect_lab_daily_literals(
	context: ConstraintContext,
) -> Mapping[str, Mapping[str, Tuple[HourLiteral, ...]]]:
	assignments = getattr(context.variables.lab, "assignments", {}) or {}
	day_patterns = getattr(context.variables.lab, "day_patterns", {}) or {}
	lab_reqs = getattr(context.variables.lab, "requirements", {}) or {}
	lab_session_to_theory = getattr(context.data.raw.time, "lab_session_to_theory", {}) or {}
	# Combined lab-block courses are staff-less: excluded from teacher daily workload.
	combined_cfg = getattr(getattr(context.config, "model", None), "combined_lab_courses", {}) or {}
	combined_codes = frozenset(
		str(c).strip().upper() for c in combined_cfg.get("course_codes", ()) if str(c).strip()
	)
	collector: MutableMapping[str, MutableMapping[str, list[HourLiteral]]] = defaultdict(
		lambda: defaultdict(list)
	)

	hours_map = {
		session_name: max(1, len(tuple(slots or ())))
		for session_name, slots in lab_session_to_theory.items()
	}
	default_hours = hours_map[next(iter(hours_map))] if hours_map else 2

	model = context.model

	for teacher_id, course_map in assignments.items():
		for course_id, day_map in course_map.items():
			req = lab_reqs.get(course_id)
			if req is not None and str(getattr(req, "course_code", "")).strip().upper() in combined_codes:
				continue
			pattern = day_patterns.get(course_id, tuple())
			for day_idx, session_map in day_map.items():
				if not session_map:
					continue
				day_name = _safe_day_name(pattern, day_idx)
				for session_name, room_map in session_map.items():
					literal = build_presence_literal(
						model,
						tuple(room_map.values()),
						f"teacher_daily_workload_{teacher_id}_{course_id}_d{day_idx}_{session_name}",
					)
					if literal is None:
						continue
					collector[teacher_id][day_name].append((literal, hours_map.get(session_name, default_hours)))

	return {
		teacher_id: {
			day_name: tuple(entries)
			for day_name, entries in day_map.items()
			if entries
		}
		for teacher_id, day_map in collector.items()
	}


def _sort_day_names(day_names: Iterable[str], working_days: Sequence[str]) -> Tuple[str, ...]:
	priority = {day: idx for idx, day in enumerate(working_days)}
	return tuple(sorted(day_names, key=lambda name: (priority.get(name, len(priority)), name)))


def _safe_day_name(pattern: Sequence[str], day_idx: int) -> str:
	if 0 <= day_idx < len(pattern):
		return pattern[day_idx]
	return f"day_{day_idx}"


def _skip_result(metadata: ConstraintMetadata, reason: str) -> ConstraintApplicationResult:
	return ConstraintApplicationResult(
		name=metadata.name,
		domain=metadata.category,
		priority=metadata.priority,
		enabled=True,
		status=ConstraintStatus.SKIPPED,
		details={"reason": reason},
	)


def build_teacher_daily_workload_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TeacherDailyWorkloadConstraint:
	return TeacherDailyWorkloadConstraint(metadata=metadata, params=params)


__all__ = [
	"TeacherDailyWorkloadConstraint",
	"build_teacher_daily_workload_constraint",
]
