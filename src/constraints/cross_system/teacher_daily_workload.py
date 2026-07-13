"""Limit each teacher's combined lab + theory workload per day."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..fixed_schedule_context import get_fixed_schedule_occupancy, normalize_day_label
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal, register_objective_penalty
from ...utils.normalization import normalize_teacher_id

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
		fixed_hours_map = dict(getattr(blocking_mask, "teacher_daily_fixed_hours", {}) if blocking_mask else {})
		fixed_occupancy = get_fixed_schedule_occupancy(context)
		for key, hours in fixed_occupancy.teacher_daily_hours.items():
			fixed_hours_map.setdefault(key, hours)

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
							excluded_teachers.add(normalize_teacher_id(inst.teacher_id))
			
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
					terms.append((literal, hours * 2))
				if not terms:
					continue

				teacher_key = normalize_teacher_id(teacher_id)
				day_key = normalize_day_label(day_name)
				fixed_hours = fixed_hours_map.get((teacher_key, day_key), 0)
				if teacher_key in excluded_teachers:
					fixed_hours = 0
				if fixed_hours > 0:
					stats.fixed_hours_applied += 1
				fixed_units = int(round(float(fixed_hours) * 2))
				remaining_capacity = config.max_daily_hours * 2 - fixed_units
				total_units = sum(weight * literal for literal, weight in terms)

				stats.hard_constraints += 1
				if config.mode == "soft" and config.soft_cap_hours:
					cap = max(0, config.soft_cap_hours * 2 - fixed_units)
					context.model.Add(total_units <= cap)
					if cap > remaining_capacity:
						max_overage = cap - remaining_capacity
						overage = context.model.NewIntVar(0, max_overage, f"teacher_daily_overage_{teacher_key}_{day_key}")
						context.model.Add(total_units - remaining_capacity <= overage)
						register_objective_penalty(
							context,
							overage,
							weight=config.penalty_weight / 2,
							tag=f"teacher_spread:daily_workload:{teacher_key}:{day_key}",
						)
						stats.soft_penalties += 1
					else:
						context.model.Add(total_units <= remaining_capacity)
				else:
					context.model.Add(total_units <= max(0, remaining_capacity))


		status = ConstraintStatus.APPLIED if stats.hard_constraints else ConstraintStatus.SKIPPED
		details = dict(stats.as_details())
		details.update(
			{
				"mode": config.mode,
				"max_daily_hours": config.max_daily_hours,
				"soft_cap_hours": config.soft_cap_hours,
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
	assignments = getattr(context.variables.theory, "assignments", {}) or {}
	day_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
	requirements = getattr(context.variables.theory, "course_requirements", {}) or {}
	collector: MutableMapping[str, MutableMapping[str, list[HourLiteral]]] = defaultdict(lambda: defaultdict(list))

	for teacher_id, course_map in assignments.items():
		teacher_key = normalize_teacher_id(teacher_id)
		for course_id, day_map in course_map.items():
			pattern = day_patterns.get(course_id, tuple())
			requirement = requirements.get(course_id)
			units = 1 if getattr(requirement, "delivery_mode", "") == "kutty_25x2" else 2
			for day_idx, slot_map in day_map.items():
				if not slot_map:
					continue
				day_name = _safe_day_name(pattern, day_idx)
				collector[teacher_key][normalize_day_label(day_name)].extend(
					(literal, units) for literal in slot_map.values()
				)

	return {
		teacher_id: {
			day_name: tuple(slots)
			for day_name, slots in day_map.items()
			if slots
		}
		for teacher_id, day_map in collector.items()
	}



def _collect_lab_daily_literals(
	context: ConstraintContext,
) -> Mapping[str, Mapping[str, Tuple[HourLiteral, ...]]]:
	assignments = getattr(context.variables.lab, "assignments", {}) or {}
	day_patterns = getattr(context.variables.lab, "day_patterns", {}) or {}
	lab_session_to_theory = getattr(context.data.raw.time, "lab_session_to_theory", {}) or {}
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
		teacher_key = normalize_teacher_id(teacher_id)
		for course_id, day_map in course_map.items():
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
					collector[teacher_key][normalize_day_label(day_name)].append((literal, hours_map.get(session_name, default_hours)))

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
