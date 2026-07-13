"""Pre-solve DBMS/OOPS pair and room/session allocation.

This deliberately removes the high-symmetry partner and slot choices from the
main timetable model.  A small CP-SAT feasibility model schedules permanent
same-course pairs against fixed room occupancy, then the main model only sees
those selected cells.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Sequence, Tuple

from ortools.sat.python import cp_model

from ..config.schemas import SchedulerConfig
from ..utils.time_utils import DayNormalizer
from .schemas import (
	CombinedLabAllocation,
	CombinedLabCell,
	DataLoadResult,
	DepartmentSemesterKey,
	NormalizedCourseInstance,
)


@dataclass(frozen=True)
class _PairUnit:
	allocation_id: str
	course_code: str
	semester: int
	instances: Tuple[NormalizedCourseInstance, ...]
	days: Tuple[str, ...]

	@property
	def departments(self) -> Tuple[str, ...]:
		return tuple(sorted({instance.student_dept for instance in self.instances}))

	@property
	def student_count(self) -> int:
		return sum(max(0, int(instance.student_count or 0)) for instance in self.instances)


class CombinedLabPreallocator:
	"""Build permanent instance pairs and allocate their weekly lab cells."""

	def __init__(self, config: SchedulerConfig, *, logger: logging.Logger | None = None) -> None:
		self._config = config
		self._logger = logger or logging.getLogger(__name__)

	def plan(
		self,
		normalized: Mapping[DepartmentSemesterKey, Tuple[NormalizedCourseInstance, ...]],
		data: DataLoadResult,
	) -> tuple[Tuple[CombinedLabAllocation, ...], Mapping[str, object]]:
		cfg = getattr(getattr(self._config, "model", None), "combined_lab_courses", {}) or {}
		codes = frozenset(
			str(code).strip().upper() for code in cfg.get("course_codes", ()) if str(code).strip()
		)
		if not codes or not bool(cfg.get("preallocate_slots", True)):
			return tuple(), {"enabled": False, "allocations": 0}

		instances = tuple(
			instance
			for cohort_instances in normalized.values()
			for instance in cohort_instances
			if str(instance.course_code).strip().upper() in codes
		)
		if not instances:
			return tuple(), {"enabled": True, "allocations": 0, "instances": 0}

		blocks = max(1, int(cfg.get("blocks", 4) or 4))
		max_unique_slots_per_course = max(
			blocks,
			int(cfg.get("max_unique_slots_per_course", 6) or 6),
		)
		configured_rooms = tuple(
			str(room).strip() for room in cfg.get("room_numbers", ()) if str(room).strip()
		)
		room_ids, room_capacities, missing_rooms = self._resolve_rooms(data, configured_rooms)
		if missing_rooms:
			raise ValueError(
				"Combined-lab preallocation references rooms absent from the active room CSV: "
				+ ", ".join(missing_rooms)
			)
		if not room_ids:
			raise ValueError("Combined-lab preallocation has no configured rooms")

		units = self._build_pair_units(instances, data)
		model = cp_model.CpModel()
		variables: Dict[Tuple[str, str, str, str], cp_model.IntVar] = {}
		unit_variables: MutableMapping[str, list[cp_model.IntVar]] = defaultdict(list)
		unit_day_variables: MutableMapping[Tuple[str, str], list[cp_model.IntVar]] = defaultdict(list)
		unit_time_variables: MutableMapping[Tuple[str, str, str], list[cp_model.IntVar]] = defaultdict(list)
		room_time_variables: MutableMapping[Tuple[str, str, str], list[cp_model.IntVar]] = defaultdict(list)
		cohort_course_time_variables: MutableMapping[
			Tuple[str, int, str, str, str], list[cp_model.IntVar]
		] = defaultdict(list)
		course_time_variables: MutableMapping[
			Tuple[str, int, str, str], list[cp_model.IntVar]
		] = defaultdict(list)

		blocked_mask = getattr(data, "blocking_mask", None)
		session_names = tuple(str(name) for name in data.time.lab_sessions.keys())
		if not session_names:
			raise ValueError("Combined-lab preallocation requires configured lab sessions")

		for unit in units:
			for day in unit.days:
				for session_name in session_names:
					if self._violates_hard_lunch(unit, session_name, data):
						continue
					for room_id in room_ids:
						capacity = room_capacities.get(room_id)
						if capacity is not None and unit.student_count > capacity:
							continue
						if self._is_fixed_room_blocked(
							blocked_mask,
							data,
							day=day,
							session_name=session_name,
							room_id=room_id,
						):
							continue
						key = (unit.allocation_id, day, session_name, room_id)
						variable = model.NewBoolVar(
							f"combined_pre_{self._slug(unit.allocation_id)}_{day}_{session_name}_{room_id}"
						)
						variables[key] = variable
						unit_variables[unit.allocation_id].append(variable)
						unit_day_variables[(unit.allocation_id, day)].append(variable)
						unit_time_variables[(unit.allocation_id, day, session_name)].append(variable)
						room_time_variables[(day, session_name, room_id)].append(variable)
						course_time_variables[
							(unit.course_code, unit.semester, day, session_name)
						].append(variable)
						for department in unit.departments:
							cohort_course_time_variables[
								(department, unit.semester, unit.course_code, day, session_name)
							].append(variable)

		for unit in units:
			bucket = unit_variables.get(unit.allocation_id, ())
			if len(bucket) < blocks:
				raise ValueError(
					f"Combined-lab allocation {unit.allocation_id} has only {len(bucket)} available cells "
					f"for {blocks} required blocks"
				)
			model.Add(sum(bucket) == blocks)
			max_per_day = 1 if len(unit.days) >= blocks else max(1, math.ceil(blocks / len(unit.days)))
			for day in unit.days:
				day_bucket = unit_day_variables.get((unit.allocation_id, day), ())
				if day_bucket:
					model.Add(sum(day_bucket) <= max_per_day)

		for bucket in unit_time_variables.values():
			if len(bucket) > 1:
				model.AddAtMostOne(bucket)
		for bucket in room_time_variables.values():
			if len(bucket) > 1:
				model.AddAtMostOne(bucket)

		# Keep each external course compact. Multiple permanent staff pairs may
		# run in parallel rooms, but DBMS and OOPS each consume at most this many
		# distinct day/session cells in the timetable.
		course_slot_active: Dict[Tuple[str, int, str, str], cp_model.IntVar] = {}
		course_active_by_code: MutableMapping[Tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
		for key, bucket in sorted(course_time_variables.items()):
			course_code, semester, day, session_name = key
			active = model.NewBoolVar(
				f"combined_pre_course_active_{course_code}_s{semester}_{day}_{session_name}"
			)
			model.Add(sum(bucket) >= active)
			model.Add(sum(bucket) <= len(bucket) * active)
			course_slot_active[key] = active
			course_active_by_code[(course_code, semester)].append(active)
		for bucket in course_active_by_code.values():
			model.Add(sum(bucket) <= max_unique_slots_per_course)

		# A cohort may run multiple parallel pairs of the same course, but DBMS
		# and OOPS cannot occupy the cohort at the same time.
		cohort_time_active: MutableMapping[
			Tuple[str, int, str, str], list[cp_model.IntVar]
		] = defaultdict(list)
		for (department, semester, course_code, day, session_name), bucket in sorted(
			cohort_course_time_variables.items()
		):
			active = model.NewBoolVar(
				f"combined_pre_active_{self._slug(department)}_s{semester}_{course_code}_{day}_{session_name}"
			)
			model.Add(sum(bucket) >= active)
			model.Add(sum(bucket) <= len(bucket) * active)
			cohort_time_active[(department, semester, day, session_name)].append(active)
		for bucket in cohort_time_active.values():
			if len(bucket) > 1:
				model.AddAtMostOne(bucket)

		ordered_variables = [variables[key] for key in sorted(variables)]
		if ordered_variables:
			model.AddDecisionStrategy(
				ordered_variables,
				cp_model.CHOOSE_FIRST,
				cp_model.SELECT_MAX_VALUE,
			)
		if course_slot_active:
			model.Minimize(sum(course_slot_active.values()))

		solver = cp_model.CpSolver()
		solver.parameters.max_time_in_seconds = max(
			1.0, float(cfg.get("preallocation_time_limit_sec", 30) or 30)
		)
		solver.parameters.num_search_workers = max(
			1, int(cfg.get("preallocation_workers", 1) or 1)
		)
		solver.parameters.random_seed = int(cfg.get("preallocation_seed", 23) or 23)
		status = solver.Solve(model)
		if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
			raise ValueError(
				"Combined-lab preallocation failed before the main solve: "
				f"status={solver.StatusName(status)}, units={len(units)}, variables={len(variables)}"
			)

		allocations = []
		for unit in units:
			selected = tuple(
				CombinedLabCell(day=day, session_name=session_name, room_id=room_id)
				for (allocation_id, day, session_name, room_id), variable in sorted(variables.items())
				if allocation_id == unit.allocation_id and solver.BooleanValue(variable)
			)
			if len(selected) != blocks:
				raise RuntimeError(
					f"Combined-lab preallocation returned {len(selected)} cells for {unit.allocation_id}; "
					f"expected {blocks}"
				)
			allocations.append(
				CombinedLabAllocation(
					allocation_id=unit.allocation_id,
					course_code=unit.course_code,
					instance_ids=tuple(instance.instance_id for instance in unit.instances),
					teacher_ids=tuple(instance.teacher_id for instance in unit.instances),
					departments=unit.departments,
					semester=unit.semester,
					cells=selected,
				)
			)

		paired = sum(1 for allocation in allocations if len(allocation.instance_ids) == 2)
		singletons = len(allocations) - paired
		unique_slots_by_course: MutableMapping[str, set[Tuple[str, str]]] = defaultdict(set)
		for allocation in allocations:
			for cell in allocation.cells:
				unique_slots_by_course[allocation.course_code].add((cell.day, cell.session_name))
		stats: Mapping[str, object] = {
			"enabled": True,
			"instances": len(instances),
			"allocations": len(allocations),
			"paired_allocations": paired,
			"singletons": singletons,
			"blocks_per_allocation": blocks,
			"max_unique_slots_per_course": max_unique_slots_per_course,
			"unique_slots_by_course": {
				course_code: len(slots)
				for course_code, slots in sorted(unique_slots_by_course.items())
			},
			"candidate_variables": len(variables),
			"solver_status": solver.StatusName(status),
			"wall_time_sec": solver.WallTime(),
		}
		self._logger.info("Combined-lab preallocation completed: %s", stats)
		return tuple(allocations), stats

	def _violates_hard_lunch(
		self,
		unit: _PairUnit,
		session_name: str,
		data: DataLoadResult,
	) -> bool:
		"""Reject a block that alone removes every valid hard-lunch choice."""

		setting = getattr(getattr(self._config, "constraints", None), "cross_system", {}).get(
			"lunch_alignment"
		)
		if setting is None or not bool(getattr(setting, "enabled", False)):
			return False
		params = getattr(setting, "params", {}) or {}
		minimum_free = max(1, int(params.get("minimum_free_slots", 1) or 1))
		overlap = {
			int(slot)
			for slot in (data.time.lab_session_to_theory.get(session_name, ()) or ())
		}
		if not overlap:
			return False

		windows = getattr(data.departments, "lunch_slot_windows", {}) or {}
		default_window = tuple(
			int(slot)
			for slot in (
				params.get("lunch_slot_window", ())
				or windows.get("__default__", ())
				or (3, 4, 5)
			)
		)
		for instance in unit.instances:
			if not self._has_hard_lunch(instance.student_dept, unit.semester, data, params):
				continue
			window = tuple(int(slot) for slot in (windows.get(instance.student_dept) or default_window))
			if window and len(set(window) - overlap) < min(minimum_free, len(window)):
				return True
		return False

	@staticmethod
	def _has_hard_lunch(
		department: str,
		semester: int,
		data: DataLoadResult,
		params: Mapping[str, object],
	) -> bool:
		hard_overrides = {str(token).strip() for token in (params.get("hard_overrides", ()) or ())}
		if CombinedLabPreallocator._matches_department_token(hard_overrides, department, semester):
			return True
		flexible = set(getattr(data.departments, "flexible_lunch_departments", ()) or ())
		flexible.update(str(token).strip() for token in (params.get("flexible_departments", ()) or ()))
		if CombinedLabPreallocator._matches_department_token(flexible, department, semester):
			return False
		soft = {str(token).strip() for token in (params.get("soft_departments", ()) or ())}
		if CombinedLabPreallocator._matches_department_token(soft, department, semester):
			return False
		soft_semesters = {int(value) for value in (params.get("soft_semesters", ()) or ())}
		return int(semester) not in soft_semesters

	@staticmethod
	def _matches_department_token(tokens: Iterable[str], department: str, semester: int) -> bool:
		needle = str(department).strip().lower()
		for token in tokens:
			text = str(token).strip()
			if not text:
				continue
			match = re.match(r"^(.*)_S(\d+)$", text, flags=re.IGNORECASE)
			if match:
				if match.group(1).strip().lower() == needle and int(match.group(2)) == int(semester):
					return True
			elif text.lower() == needle:
				return True
		return False

	def _build_pair_units(
		self,
		instances: Sequence[NormalizedCourseInstance],
		data: DataLoadResult,
	) -> Tuple[_PairUnit, ...]:
		by_course_semester: MutableMapping[Tuple[str, int], list[NormalizedCourseInstance]] = defaultdict(list)
		for instance in instances:
			by_course_semester[(str(instance.course_code).strip().upper(), int(instance.semester))].append(
				instance
			)

		units = []
		for (course_code, semester), course_instances in sorted(by_course_semester.items()):
			remaining = sorted(
				course_instances,
				key=lambda item: (item.student_dept.lower(), str(item.teacher_id), item.instance_id),
			)
			ordinal = 1
			while remaining:
				department_counts: MutableMapping[str, int] = defaultdict(int)
				for instance in remaining:
					department_counts[instance.student_dept] += 1
				first_department = min(
					department_counts,
					key=lambda department: (-department_counts[department], department.lower()),
				)
				first_index = next(
					index for index, instance in enumerate(remaining) if instance.student_dept == first_department
				)
				first = remaining.pop(first_index)
				candidate_indexes = [
					index
					for index, candidate in enumerate(remaining)
					if str(candidate.teacher_id) != str(first.teacher_id)
				]
				second = None
				if candidate_indexes:
					second_index = min(
						candidate_indexes,
						key=lambda index: (
							remaining[index].student_dept == first.student_dept,
							-department_counts.get(remaining[index].student_dept, 0),
							remaining[index].student_dept.lower(),
							str(remaining[index].teacher_id),
						),
					)
					second = remaining.pop(second_index)
				pair = (first,) if second is None else (first, second)
				days = self._common_days(pair, data)
				if not days:
					raise ValueError(
						f"Combined-lab pair {[instance.instance_id for instance in pair]} has no common teaching day"
					)
				units.append(
					_PairUnit(
						allocation_id=(
							f"combined_{course_code.lower()}_s{semester}_{ordinal:02d}_"
							+ "__".join(self._slug(instance.instance_id) for instance in pair)
						),
						course_code=course_code,
						semester=semester,
						instances=pair,
						days=days,
					)
				)
				ordinal += 1
		return tuple(units)

	def _common_days(
		self,
		instances: Sequence[NormalizedCourseInstance],
		data: DataLoadResult,
	) -> Tuple[str, ...]:
		patterns = getattr(data.departments, "day_patterns", {}) or {}
		working_days = tuple(self._normalize_day(day) for day in data.time.working_days)
		common: set[str] | None = None
		for instance in instances:
			pattern = patterns.get(instance.student_dept) or patterns.get("__default__") or data.time.working_days
			normalized = {self._normalize_day(day) for day in pattern}
			common = normalized if common is None else common & normalized
		return tuple(day for day in working_days if day in (common or set()))

	@staticmethod
	def _resolve_rooms(
		data: DataLoadResult,
		configured_rooms: Sequence[str],
	) -> tuple[Tuple[str, ...], Mapping[str, int | None], Tuple[str, ...]]:
		by_number = {
			str((metadata or {}).get("room_number", "")).strip().upper(): (str(room_id), metadata or {})
			for room_id, metadata in (data.room_registry or {}).items()
		}
		room_ids = []
		capacities: Dict[str, int | None] = {}
		missing = []
		for room_number in configured_rooms:
			entry = by_number.get(str(room_number).strip().upper())
			if entry is None:
				missing.append(room_number)
				continue
			room_id, metadata = entry
			room_ids.append(room_id)
			capacities[room_id] = CombinedLabPreallocator._capacity(metadata)
		return tuple(room_ids), capacities, tuple(missing)

	@staticmethod
	def _capacity(metadata: Mapping[str, object]) -> int | None:
		for key in ("capacity", "room_max_cap", "max_capacity", "room_min_cap"):
			value = metadata.get(key)
			try:
				if value is not None and str(value).strip():
					return int(float(value))
			except (TypeError, ValueError):
				continue
		return None

	@staticmethod
	def _is_fixed_room_blocked(
		mask: object,
		data: DataLoadResult,
		*,
		day: str,
		session_name: str,
		room_id: str,
	) -> bool:
		if mask is None:
			return False
		if (day, session_name, room_id) in (getattr(mask, "blocked_lab_rooms", set()) or set()):
			return True
		blocked_theory = getattr(mask, "blocked_theory_rooms", set()) or set()
		for slot_index in (data.time.lab_session_to_theory.get(session_name, ()) or ()):
			if (day, int(slot_index), room_id) in blocked_theory:
				return True
		return False

	@staticmethod
	def _normalize_day(value: object) -> str:
		return DayNormalizer.normalize_day_name(value) or str(value or "").strip().lower()

	@staticmethod
	def _slug(value: object) -> str:
		return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_") or "item"


__all__ = ["CombinedLabPreallocator"]
