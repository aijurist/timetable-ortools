"""CP-SAT variable creation utilities for the modular scheduler pipeline."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..data.schemas import (
	CourseGroup,
	ExtendedDataContainer,
	GroupRequirement,
	NormalizedCourseInstance,
)
from ..data.pop_availability import (
	DEFAULT_POP_END_TIME,
	DEFAULT_POP_START_TIME,
	PopTeacherAvailability,
	build_pop_availability_from_dataframe,
	normalize_teacher_id,
)
from ..data.room_eligibility import RoomEligibilityIndex, build_room_eligibility_index
from ..data.schedule_blocking import ScheduleBlockingMask
from ..utils.time_utils import DayNormalizer

from .schema import (
	LabCourseRequirement,
	GroupTimeslotRequirement,
	LabVariableBlock,
	TheoryAssignmentDict,
	TheoryCourseRequirement,
	TheoryVariableBlock,
	VariableCreationResult,
)

LabAssignmentDict = Dict[str, Dict[str, Dict[int, Dict[str, Dict[str, cp_model.IntVar]]]]]
GroupTimeslotDict = Dict[str, Dict[int, Dict[int, cp_model.IntVar]]]

logger = logging.getLogger(__name__)


class VariableCreator:
	"""Create CP-SAT decision variables backed by preprocessing artefacts."""

	def __init__(self, data: ExtendedDataContainer, *, logger_: Optional[logging.Logger] = None) -> None:
		self._data = data
		self._logger = logger_ or logging.getLogger(__name__)
		self._instance_index = self._index_instances()
		self._instance_group_index = self._build_instance_group_lookup()
		self._instance_group_lookup = {
			instance_id: group.group_id
			for instance_id, group in self._instance_group_index.items()
		}
		self._group_index = self._build_group_index()
		self._group_requirement_index = self._build_group_requirement_index()
		self._day_pattern_cache: Dict[str, Tuple[str, ...]] = {}
		self._lab_room_ids = tuple(str(room_id) for room_id in data.raw.rooms.lab_room_ids)
		self._theory_room_ids = tuple(str(room_id) for room_id in getattr(data.raw.rooms, "theory_room_ids", tuple()))
		self._theory_slot_labels = tuple(str(label) for label in data.raw.time.theory_slots)
		self._lab_session_names = tuple(data.raw.time.lab_sessions.keys())

		# Optimization: Index rooms by type for pruning
		self._lab_rooms_by_type = defaultdict(list)
		if "room_type" in data.raw.rooms.lab_rooms.columns:
			for _, row in data.raw.rooms.lab_rooms.iterrows():
				r_type = str(row.get("room_type", "")).strip()
				r_id = str(row.get("id", ""))
				if r_type and r_id:
					self._lab_rooms_by_type[r_type].append(r_id)
		
		self._theory_rooms_by_type = defaultdict(list)
		if "room_type" in data.raw.rooms.theory_rooms.columns:
			for _, row in data.raw.rooms.theory_rooms.iterrows():
				r_type = str(row.get("room_type", "")).strip()
				r_id = str(row.get("id", ""))
				if r_type and r_id:
					self._theory_rooms_by_type[r_type].append(r_id)

		# Build room eligibility index for pre-filtering (major optimization)
		core_lab_df = getattr(data.raw, "core_lab_mapping_df", None)
		rooms_df = getattr(data.raw, "rooms_df", None)
		laboratory_room_ids = getattr(data.raw.rooms, "laboratory_room_ids", None)
		model_config = getattr(getattr(data.raw, "config", None), "model", None)
		use_sparse_theory_rooms = bool(getattr(model_config, "use_sparse_variables", True))
		theory_room_candidate_limit = getattr(model_config, "theory_room_candidate_limit", 12)
		if not use_sparse_theory_rooms:
			theory_room_candidate_limit = None
		
		# DEBUG: Log what we're passing
		self._logger.info(
			"Room eligibility init: core_lab_df=%s rows, rooms_df=%s rows, laboratory_room_ids=%s",
			len(core_lab_df) if core_lab_df is not None else "None",
			len(rooms_df) if rooms_df is not None else "None",
			len(laboratory_room_ids) if laboratory_room_ids else "None",
		)
		
		self._room_eligibility = build_room_eligibility_index(
			core_lab_df=core_lab_df,
			rooms_df=rooms_df,
			lab_room_ids=self._lab_room_ids,
			theory_room_ids=self._theory_room_ids,
			laboratory_room_ids=tuple(str(rid) for rid in laboratory_room_ids) if laboratory_room_ids else None,
			theory_room_candidate_limit=theory_room_candidate_limit,
			theory_room_min_candidates=getattr(model_config, "theory_room_min_candidates", 4),
			theory_room_anchor_candidates=getattr(model_config, "theory_room_anchor_candidates", 4),
			theory_room_capacity_slack=getattr(model_config, "room_capacity_slack", 0),
		)

		self._blocking_mask: Optional[ScheduleBlockingMask] = getattr(data.raw, "blocking_mask", None)
		if self._blocking_mask:
			self._logger.info(
				"Blocking mask loaded: lab_rooms=%d, lab_teachers=%d, theory_rooms=%d, theory_teachers=%d",
				len(self._blocking_mask.blocked_lab_rooms),
				len(self._blocking_mask.blocked_lab_teacher_sessions),
				len(self._blocking_mask.blocked_theory_rooms),
				len(self._blocking_mask.blocked_theory_teacher_slots),
			)

		self._pop_availability = self._build_pop_availability_index()
		if self._pop_availability:
			self._logger.info(
				"Loaded POP theory availability for %d teachers during variable creation",
				len(self._pop_availability),
			)

		# Cohorts (department_lower, semester) whose theory courses are bundled. Their
		# courses must share one room when paired, so give the whole cohort an identical
		# theory-room candidate set (shared salt) instead of per-course rotated tails.
		self._bundle_cohorts = self._compute_bundle_cohorts()

		# Combined lab-block courses (DBMS/OOP-Java/...): restricted to the ANEW big rooms.
		combined_cfg = getattr(model_config, "combined_lab_courses", {}) or {}
		self._combined_lab_codes = frozenset(
			str(c).strip().upper() for c in combined_cfg.get("course_codes", ()) if str(c).strip()
		)
		combined_room_numbers = {str(r).strip() for r in combined_cfg.get("room_numbers", ()) if str(r).strip()}
		self._combined_lab_room_ids: Tuple[str, ...] = tuple()
		if self._combined_lab_codes and combined_room_numbers:
			registry = getattr(data.raw, "room_registry", {}) or {}
			ids = [
				str(rid)
				for rid, meta in registry.items()
				if str((meta or {}).get("room_number", "")).strip() in combined_room_numbers
			]
			self._combined_lab_room_ids = tuple(ids)
			self._logger.info(
				"Combined-lab courses %s restricted to ANEW rooms %s (ids %s)",
				sorted(self._combined_lab_codes),
				sorted(combined_room_numbers),
				self._combined_lab_room_ids,
			)

	def create(self, model: cp_model.CpModel) -> VariableCreationResult:
		"""Create all decision variables and return a structured handle bundle."""

		lab_block = self._create_lab_variables(model)
		theory_block = self._create_theory_variables(model)

		metadata = {
			"lab_courses": len(lab_block.requirements),
			"lab_teachers": len(lab_block.teacher_courses),
			"theory_courses": len(theory_block.course_requirements),
			"theory_teachers": len(theory_block.teacher_courses),
			"groups": len(theory_block.requirements),
		}

		self._logger.info(
			"VariableCreator initialised %s lab courses across %s teachers and %s theory courses across %s teachers spanning %s groups",
			metadata["lab_courses"],
			metadata["lab_teachers"],
			metadata["theory_courses"],
			metadata["theory_teachers"],
			metadata["groups"],
		)
		self._logger.info(
			"Created %d lab variables and %d theory variables",
			self._lab_var_count,
			self._theory_var_count,
		)

		return VariableCreationResult(lab=lab_block, theory=theory_block, metadata=metadata)

	def _create_lab_variables(self, model: cp_model.CpModel) -> LabVariableBlock:
		self._lab_var_count = 0
		self._lab_pruned_count = 0
		requirements = self._build_lab_course_requirements()
		assignments: LabAssignmentDict = {}
		teacher_courses: Dict[str, Tuple[str, ...]] = {}
		day_patterns: Dict[str, Tuple[str, ...]] = {}
		lab_eligibility_cache: Dict[str, Tuple[str, ...]] = {}

		for teacher_id, course_requirements in self._group_requirements_by_teacher(requirements).items():
			assignments[teacher_id] = {}
			teacher_courses[teacher_id] = tuple(req.course_instance_id for req in course_requirements)

			for requirement in course_requirements:
				course_vars: Dict[int, Dict[str, Dict[str, cp_model.IntVar]]] = {}
				assignments[teacher_id][requirement.course_instance_id] = course_vars
				pattern = self._resolve_day_pattern(requirement.department)
				day_patterns[requirement.course_instance_id] = pattern
				lab_cache_key = (
					str(requirement.course_code or "").strip().upper(),
					str(getattr(requirement, "department", "") or "").strip().lower(),
				)
				eligible_rooms = lab_eligibility_cache.get(lab_cache_key)
				if eligible_rooms is None:
					eligible_rooms = self._room_eligibility.get_eligible_lab_rooms(
						requirement.course_code,
						getattr(requirement, "department", ""),
					)
					lab_eligibility_cache[lab_cache_key] = eligible_rooms
				for day_index, day_label in enumerate(pattern):
					normalized_day = self._normalize_day_for_blocking(day_label)
					session_map: Dict[str, Dict[str, cp_model.IntVar]] = {}
					course_vars[day_index] = session_map
					for session_name in self._lab_session_names:
						room_map: Dict[str, cp_model.IntVar] = {}
						session_map[session_name] = room_map

						for room_id in eligible_rooms:
							if self._blocking_mask and self._blocking_mask.is_lab_variable_blocked(
								teacher_id=teacher_id,
								course_id=requirement.course_instance_id,
								day_label=normalized_day,
								session_name=session_name,
								room_id=room_id,
							):
								self._lab_pruned_count += 1
								continue

							var_name = (
								f"lab_{teacher_id}_{requirement.course_instance_id}_d{day_index}_{session_name}_{room_id}"
							)
							room_map[room_id] = model.NewBoolVar(var_name)
							self._lab_var_count += 1

		if self._lab_pruned_count > 0:
			self._logger.info("Pruned %d lab variables via blocking mask", self._lab_pruned_count)

		return LabVariableBlock(
			assignments=assignments,
			requirements=requirements,
			teacher_courses=teacher_courses,
			day_patterns=day_patterns,
			lab_session_names=self._lab_session_names,
			room_ids=self._lab_room_ids,
			instance_group_lookup=self._instance_group_lookup,
		)

	def _create_theory_variables(self, model: cp_model.CpModel) -> TheoryVariableBlock:
		self._theory_var_count = 0
		self._theory_pruned_count = 0
		self._theory_slot_pruned_count = 0
		self._theory_pop_pruned_count = 0
		group_requirements = self._build_group_timeslot_requirements()
		course_requirements = self._build_theory_course_requirements()
		assignments: TheoryAssignmentDict = {}
		room_assignments: Dict[str, Dict[str, Dict[int, Dict[int, Dict[str, cp_model.IntVar]]]]] = {}
		teacher_courses: Dict[str, Tuple[str, ...]] = {}
		course_day_patterns: Dict[str, Tuple[str, ...]] = {}
		theory_eligibility_cache: Dict[Tuple[int, Optional[int], str, str], Tuple[str, ...]] = {}
		group_course_buffer: MutableMapping[str, set[str]] = defaultdict(set)
		group_slot_sources: MutableMapping[
			str,
			MutableMapping[int, MutableMapping[int, list[cp_model.IntVar]]],
		] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

		for teacher_id, course_list in self._group_requirements_by_teacher(course_requirements).items():
			assignments[teacher_id] = {}
			room_assignments[teacher_id] = {}
			teacher_courses[teacher_id] = tuple(req.course_instance_id for req in course_list)
			for requirement in course_list:
				course_id = requirement.course_instance_id
				course_vars: Dict[int, Dict[int, cp_model.IntVar]] = {}
				room_course_vars: Dict[int, Dict[int, Dict[str, cp_model.IntVar]]] = {}
				assignments[teacher_id][course_id] = course_vars
				room_assignments[teacher_id][course_id] = room_course_vars
				pattern = self._resolve_day_pattern(requirement.department)
				course_day_patterns[course_id] = pattern
				group_course_buffer[requirement.group_id].add(course_id)
				student_count = int(getattr(requirement, "student_count", 0) or 0)
				semester = getattr(requirement, "semester", None)
				# Bundle cohorts share one salt so all their theory courses get an identical
				# room candidate set (required for a paired pair to share a room). Scope the salt
				# PER SECTION so parallel sections spread across rooms instead of contending for
				# one shared 20-room pool (non-section cohorts share section_id=None -> one set).
				if self._is_bundle_cohort(getattr(requirement, "department", None), semester):
					salt_course_id = None
					salt_group_id = (
						f"bundle::{requirement.department}::{semester}::sec{getattr(requirement, 'section_id', None)}"
					)
				else:
					salt_course_id = course_id
					salt_group_id = requirement.group_id
				theory_cache_key = (
					student_count,
					int(semester) if semester is not None else None,
					str(salt_course_id),
					str(salt_group_id),
				)
				# Combined lab-block courses use ONLY the designated ANEW rooms (bypass the
				# capacity/block-ranked theory eligibility).
				if (
					self._combined_lab_room_ids
					and str(getattr(requirement, "course_code", "")).strip().upper() in self._combined_lab_codes
				):
					eligible_rooms = self._combined_lab_room_ids
				else:
					eligible_rooms = theory_eligibility_cache.get(theory_cache_key)
					if eligible_rooms is None:
						eligible_rooms = self._room_eligibility.get_eligible_theory_rooms(
							student_count=student_count,
							semester=theory_cache_key[1],
							course_id=salt_course_id,
							group_id=salt_group_id,
						)
						theory_eligibility_cache[theory_cache_key] = eligible_rooms
				for day_index, day_label in enumerate(pattern):
					normalized_day = self._normalize_day_for_blocking(day_label)
					slot_map: Dict[int, cp_model.IntVar] = {}
					room_day_map: Dict[int, Dict[str, cp_model.IntVar]] = {}
					course_vars[day_index] = slot_map
					room_course_vars[day_index] = {}
					for slot_index, _ in enumerate(self._theory_slot_labels):
						if self._is_pop_theory_slot_blocked(
							teacher_id,
							normalized_day,
							self._theory_slot_labels[slot_index],
						):
							self._theory_pop_pruned_count += 1
							room_day_map = room_course_vars[day_index]
							room_day_map[slot_index] = {}
							continue

						slot_blocked = (
							self._blocking_mask
							and self._blocking_mask.is_theory_slot_blocked(
								teacher_id=teacher_id,
								course_id=course_id,
								day_label=normalized_day,
								slot_index=slot_index,
							)
						)

						if slot_blocked:
							self._theory_slot_pruned_count += 1
							room_day_map = room_course_vars[day_index]
							room_day_map[slot_index] = {}
							continue

						var_name = (
							f"theory_{teacher_id}_{course_id}_d{day_index}_s{slot_index}"
						)
						literal = model.NewBoolVar(var_name)
						slot_map[slot_index] = literal
						room_bucket: Dict[str, cp_model.IntVar] = {}

						if eligible_rooms:
							for room_id in eligible_rooms:
								if self._blocking_mask and self._blocking_mask.is_theory_variable_blocked(
									teacher_id=teacher_id,
									course_id=course_id,
									day_label=normalized_day,
									slot_index=slot_index,
									room_id=room_id,
								):
									self._theory_pruned_count += 1
									continue

								room_var = model.NewBoolVar(
									f"theory_{teacher_id}_{course_id}_d{day_index}_s{slot_index}_r{room_id}"
								)
								room_bucket[room_id] = room_var
								self._theory_var_count += 1
							if room_bucket:
								model.Add(sum(room_bucket.values()) == literal)
							else:
								model.Add(literal == 0)
						else:
							model.Add(literal == 0)
						room_day_map = room_course_vars[day_index]
						room_day_map[slot_index] = room_bucket
						group_slot_sources[requirement.group_id][day_index][slot_index].append(literal)

		if self._theory_pruned_count > 0 or self._theory_slot_pruned_count > 0 or self._theory_pop_pruned_count > 0:
			self._logger.info(
				"Pruned %d theory room vars, %d theory slot vars via blocking mask, and %d POP theory slot vars",
				self._theory_pruned_count,
				self._theory_slot_pruned_count,
				self._theory_pop_pruned_count,
			)

		group_timeslots: GroupTimeslotDict = {}
		day_patterns: Dict[str, Tuple[str, ...]] = {}
		for group_id, requirement in group_requirements.items():
			pattern = requirement.day_pattern or self._default_day_pattern()
			day_patterns[group_id] = pattern
			group_timeslots[group_id] = {}
			for day_index, _ in enumerate(pattern):
				group_timeslots[group_id][day_index] = {}
				for slot_index, _ in enumerate(self._theory_slot_labels):
					var_name = f"grp_{group_id}_d{day_index}_t{slot_index}"
					group_var = model.NewBoolVar(var_name)
					group_timeslots[group_id][day_index][slot_index] = group_var
					sources = (
						group_slot_sources.get(group_id, {})
						.get(day_index, {})
						.get(slot_index, [])
					)
					if sources:
						model.Add(sum(sources) >= group_var)
						model.Add(sum(sources) <= len(sources) * group_var)
					else:
						model.Add(group_var == 0)

		group_course_index = {
			group_id: tuple(sorted(course_ids))
			for group_id, course_ids in group_course_buffer.items()
		}

		return TheoryVariableBlock(
			assignments=assignments,
			room_assignments=room_assignments,
			course_requirements=course_requirements,
			teacher_courses=teacher_courses,
			course_day_patterns=course_day_patterns,
			group_timeslots=group_timeslots,
			requirements=group_requirements,
			day_patterns=day_patterns,
			theory_slot_labels=self._theory_slot_labels,
			group_course_index=group_course_index,
			instance_group_lookup=self._instance_group_lookup,
			room_ids=self._theory_room_ids,
		)

	def _build_lab_course_requirements(self) -> Dict[str, LabCourseRequirement]:
		requirements: Dict[str, LabCourseRequirement] = {}
		for instance_id, instance in self._instance_index.items():
			if not instance.has_lab or instance.practical_hours <= 0:
				continue
			group = self._instance_group_index.get(instance_id)
			if not group:
				self._logger.debug("Skipping lab instance %s without group assignment", instance_id)
				continue
			required_sessions = max(1, math.ceil(instance.practical_hours / 2))
			requirements[instance_id] = LabCourseRequirement(
				course_instance_id=instance_id,
				course_code=instance.course_code,
				teacher_id=instance.teacher_id,
				group_id=group.group_id,
				department=instance.student_dept,
				semester=instance.semester,
				practical_hours=instance.practical_hours,
				required_sessions=required_sessions,
				student_count=instance.student_count,
				preferred_room_type=instance.preferred_room_type,
				required_room_type=instance.required_room_type,
				tags=instance.tags,
				section_id=instance.section_id,
			)
		return requirements

	def _build_theory_course_requirements(self) -> Dict[str, TheoryCourseRequirement]:
		requirements: Dict[str, TheoryCourseRequirement] = {}
		for instance_id, instance in self._instance_index.items():
			if not instance.has_theory:
				continue
			required_slots = max(instance.lecture_hours + instance.tutorial_hours, 0)
			if required_slots <= 0:
				continue
			group = self._instance_group_index.get(instance_id)
			if not group:
				self._logger.debug("Skipping theory instance %s without group assignment", instance_id)
				continue
			requirements[instance_id] = TheoryCourseRequirement(
				course_instance_id=instance_id,
				course_code=instance.course_code,
				group_id=group.group_id,
				teacher_id=instance.teacher_id,
				department=instance.student_dept,
				semester=instance.semester,
				required_slots=required_slots,
				lecture_hours=max(instance.lecture_hours, 0),
				tutorial_hours=max(instance.tutorial_hours, 0),
				student_count=instance.student_count,
				preferred_room_type=instance.preferred_room_type,
				required_room_type=instance.required_room_type,
				tags=instance.tags,
				section_id=instance.section_id,
			)
		return requirements

	def _group_requirements_by_teacher(
		self,
		requirements: Mapping[str, Any],
	) -> Dict[str, Tuple[Any, ...]]:
		grouped: Dict[str, Tuple[Any, ...]] = {}
		buffer: MutableMapping[str, list] = defaultdict(list)
		for requirement in requirements.values():
			teacher_id = getattr(requirement, "teacher_id", None)
			if not teacher_id:
				continue
			teacher_key = normalize_teacher_id(teacher_id)
			if not teacher_key:
				continue
			buffer[teacher_key].append(requirement)
		for teacher_id, entries in buffer.items():
			grouped[teacher_id] = tuple(
				sorted(entries, key=lambda item: getattr(item, "course_instance_id", ""))
			)
		return grouped

	def _build_group_timeslot_requirements(self) -> Dict[str, GroupTimeslotRequirement]:
		requirements: Dict[str, GroupTimeslotRequirement] = {}
		for group_id, group in self._group_index.items():
			pattern = self._resolve_day_pattern(group.key.department)
			base_requirement = self._group_requirement_index.get(group_id)
			tags = set(group.tags)
			if base_requirement:
				tags.update(base_requirement.tags)
			requirements[group_id] = GroupTimeslotRequirement(
				group_id=group_id,
				department=group.key.department,
				semester=group.key.semester,
				required_theory_slots=max(group.summary.theory_hours, 0),
				day_pattern=pattern,
				lunch_slot_window=base_requirement.lunch_slot_window if base_requirement else tuple(),
				five_pm_policy=base_requirement.five_pm_policy if base_requirement else None,
				tags=tuple(sorted(tags)),
				base_requirement=base_requirement,
				section_id=group.section_id,
			)
		return requirements

	def _index_instances(self) -> Dict[str, NormalizedCourseInstance]:
		index: Dict[str, NormalizedCourseInstance] = {}
		for instances in self._data.preprocessing.normalized_instances.values():
			for instance in instances:
				index[instance.instance_id] = instance
		return index

	def _build_group_index(self) -> Dict[str, CourseGroup]:
		index: Dict[str, CourseGroup] = {}
		for groups in self._data.preprocessing.groups.values():
			for group in groups:
				index[group.group_id] = group
		return index

	def _build_group_requirement_index(self) -> Dict[str, GroupRequirement]:
		index: Dict[str, GroupRequirement] = {}
		for package in self._data.preprocessing.scheduling_packages.values():
			for requirement in package.requirements:
				index[requirement.group_id] = requirement
		return index

	def _build_instance_group_lookup(self) -> Dict[str, CourseGroup]:
		lookup: Dict[str, CourseGroup] = {}
		for groups in self._data.preprocessing.groups.values():
			for group in groups:
				for instance_id in group.course_instance_ids:
					lookup[instance_id] = group
		return lookup

	def _resolve_day_pattern(self, department: str) -> Tuple[str, ...]:
		if department in self._day_pattern_cache:
			return self._day_pattern_cache[department]
		patterns = self._data.raw.departments.day_patterns
		pattern = patterns.get(department) or patterns.get("__default__")
		if not pattern:
			pattern = self._data.raw.time.working_days
		self._day_pattern_cache[department] = tuple(pattern)
		return self._day_pattern_cache[department]

	def _default_day_pattern(self) -> Tuple[str, ...]:
		patterns = self._data.raw.departments.day_patterns
		return patterns.get("__default__", tuple(self._data.raw.time.working_days))

	def _normalize_day_for_blocking(self, day_label: str) -> str:
		"""Normalize day label for blocking mask lookup."""
		normalized = DayNormalizer.normalize_day_name(day_label)
		if normalized:
			return normalized
		return str(day_label).strip().lower()

	def _compute_bundle_cohorts(self) -> set:
		"""Read the bundled_theory allowlist into a set of (department_lower, semester)."""

		result: set = set()
		config = getattr(self._data.raw, "config", None)
		constraints = getattr(config, "constraints", None)
		cross_system = getattr(constraints, "cross_system", None) or {}
		getter = getattr(cross_system, "get", None)
		setting = getter("bundled_theory") if callable(getter) else None
		if setting is None or not getattr(setting, "enabled", False):
			return result
		params = getattr(setting, "params", {}) or {}
		for token in params.get("eligible_cohorts", ()) or ():
			value = str(token).strip()
			dept, semester = value, None
			if "_S" in value:
				dept, _, suffix = value.partition("_S")
				try:
					semester = int(suffix)
				except ValueError:
					semester = None
			if dept:
				dept_key = "*" if dept.strip().lower() in ("*", "all") else dept.strip().lower()
				result.add((dept_key, semester))
		return result

	def _is_bundle_cohort(self, department: object, semester: object) -> bool:
		if not self._bundle_cohorts:
			return False
		dept_norm = str(department).strip().lower()
		try:
			sem_value = int(semester) if semester is not None else None
		except (TypeError, ValueError):
			sem_value = None
		return (
			(dept_norm, sem_value) in self._bundle_cohorts
			or (dept_norm, None) in self._bundle_cohorts
			or ("*", sem_value) in self._bundle_cohorts
			or ("*", None) in self._bundle_cohorts
		)

	def _build_pop_availability_index(self) -> Dict[str, PopTeacherAvailability]:
		setting = self._pop_constraint_setting()
		if setting is None or not getattr(setting, "enabled", False):
			return {}
		params = getattr(setting, "params", {}) or {}
		preferences_df = getattr(self._data.raw, "teacher_preferences_df", None)
		return build_pop_availability_from_dataframe(
			preferences_df,
			default_start_time=params.get("default_start_time", DEFAULT_POP_START_TIME),
			default_end_time=params.get("default_end_time", DEFAULT_POP_END_TIME),
		)

	def _pop_constraint_setting(self) -> Optional[Any]:
		config = getattr(self._data.raw, "config", None)
		constraints = getattr(config, "constraints", None)
		cross_system = getattr(constraints, "cross_system", {}) or {}
		getter = getattr(cross_system, "get", None)
		if not callable(getter):
			return None
		return getter("pop_day")

	def _is_pop_theory_slot_blocked(self, teacher_id: object, day_label: object, slot_label: object) -> bool:
		if not self._pop_availability:
			return False
		availability = self._pop_availability.get(normalize_teacher_id(teacher_id))
		if availability is None:
			return False
		return not availability.allows_theory(day_label, slot_label)


__all__ = [
	"LabVariableBlock",
	"TheoryVariableBlock",
	"LabCourseRequirement",
	"TheoryCourseRequirement",
	"GroupTimeslotRequirement",
	"VariableCreationResult",
	"VariableCreator",
]

if __name__ == "__main__":
    from ortools.sat.python import cp_model
    from ..config.manager import ConfigManager
    from ..data.data_loader import DataLoader
    from ..data.preprocessing import DataPreprocessor
    from pathlib import Path

    base_dir = Path.cwd()
    config_manager = ConfigManager(base_dir=base_dir)
    config = config_manager.load()
    
    data_loader = DataLoader(config, base_dir=base_dir)
    res = data_loader.load()

    pre = DataPreprocessor(config)
    output = pre.build_extended_container(data=res)
	
    model = cp_model.CpModel()
    variable_creator = VariableCreator(data=output)
    model_res = variable_creator.create(model=model)

