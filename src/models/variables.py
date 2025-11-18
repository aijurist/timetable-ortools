"""CP-SAT variable creation utilities for the modular scheduler pipeline."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Mapping, MutableMapping, Optional, Tuple

from ortools.sat.python import cp_model

from ..data.schemas import (
	CourseGroup,
	ExtendedDataContainer,
	GroupRequirement,
	NormalizedCourseInstance,
)


LabAssignmentDict = Dict[str, Dict[str, Dict[int, Dict[str, Dict[str, cp_model.IntVar]]]]]
GroupTimeslotDict = Dict[str, Dict[int, Dict[int, cp_model.IntVar]]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LabCourseRequirement:
	course_instance_id: str
	teacher_id: str
	group_id: str
	department: str
	semester: int
	practical_hours: int
	required_sessions: int
	student_count: int
	preferred_room_type: Optional[str]
	required_room_type: Optional[str]
	tags: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GroupTimeslotRequirement:
	group_id: str
	department: str
	semester: int
	required_theory_slots: int
	day_pattern: Tuple[str, ...]
	lunch_slot_window: Tuple[int, ...]
	five_pm_policy: Optional[str]
	tags: Tuple[str, ...] = field(default_factory=tuple)
	base_requirement: Optional[GroupRequirement] = None

	@property
	def requires_lab(self) -> bool:
		return bool(self.base_requirement and self.base_requirement.has_lab)

	@property
	def required_lab_sessions(self) -> int:
		return self.base_requirement.required_lab_sessions if self.base_requirement else 0

	@property
	def prefer_consecutive_labs(self) -> bool:
		return bool(self.base_requirement and self.base_requirement.prefer_consecutive_labs)


@dataclass
class LabVariableBlock:
	assignments: LabAssignmentDict
	requirements: Mapping[str, LabCourseRequirement]
	teacher_courses: Mapping[str, Tuple[str, ...]]
	day_patterns: Mapping[str, Tuple[str, ...]]
	lab_session_names: Tuple[str, ...]
	room_ids: Tuple[str, ...]
	instance_group_lookup: Mapping[str, str]


@dataclass
class TheoryVariableBlock:
	group_timeslots: GroupTimeslotDict
	requirements: Mapping[str, GroupTimeslotRequirement]
	day_patterns: Mapping[str, Tuple[str, ...]]
	theory_slot_labels: Tuple[str, ...]


@dataclass(frozen=True)
class VariableCreationResult:
	lab: LabVariableBlock
	theory: TheoryVariableBlock
	metadata: Mapping[str, int]


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
		self._theory_slot_labels = tuple(str(label) for label in data.raw.time.theory_slots)
		self._lab_session_names = tuple(data.raw.time.lab_sessions.keys())

	def create(self, model: cp_model.CpModel) -> VariableCreationResult:
		"""Create all decision variables and return a structured handle bundle."""

		lab_block = self._create_lab_variables(model)
		theory_block = self._create_theory_variables(model)

		metadata = {
			"lab_courses": len(lab_block.requirements),
			"lab_teachers": len(lab_block.teacher_courses),
			"groups": len(theory_block.requirements),
		}

		self._logger.info(
			"VariableCreator initialised %s lab courses across %s teachers and %s groups",
			metadata["lab_courses"],
			metadata["lab_teachers"],
			metadata["groups"],
		)

		return VariableCreationResult(lab=lab_block, theory=theory_block, metadata=metadata)

	def _create_lab_variables(self, model: cp_model.CpModel) -> LabVariableBlock:
		requirements = self._build_lab_course_requirements()
		assignments: LabAssignmentDict = {}
		teacher_courses: Dict[str, Tuple[str, ...]] = {}
		day_patterns: Dict[str, Tuple[str, ...]] = {}

		for teacher_id, course_requirements in self._group_requirements_by_teacher(requirements).items():
			assignments[teacher_id] = {}
			teacher_courses[teacher_id] = tuple(req.course_instance_id for req in course_requirements)

			for requirement in course_requirements:
				course_vars: Dict[int, Dict[str, Dict[str, cp_model.IntVar]]] = {}
				assignments[teacher_id][requirement.course_instance_id] = course_vars
				pattern = self._resolve_day_pattern(requirement.department)
				day_patterns[requirement.course_instance_id] = pattern
				for day_index, _ in enumerate(pattern):
					session_map: Dict[str, Dict[str, cp_model.IntVar]] = {}
					course_vars[day_index] = session_map
					for session_name in self._lab_session_names:
						room_map: Dict[str, cp_model.IntVar] = {}
						session_map[session_name] = room_map
						for room_id in self._lab_room_ids:
							var_name = (
								f"lab_{teacher_id}_{requirement.course_instance_id}_d{day_index}_{session_name}_{room_id}"
							)
							room_map[room_id] = model.NewBoolVar(var_name)

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
		requirements = self._build_group_timeslot_requirements()
		group_timeslots: GroupTimeslotDict = {}
		day_patterns: Dict[str, Tuple[str, ...]] = {}

		for group_id, requirement in requirements.items():
			pattern = requirement.day_pattern or self._default_day_pattern()
			day_patterns[group_id] = pattern
			group_timeslots[group_id] = {}
			for day_index, _ in enumerate(pattern):
				group_timeslots[group_id][day_index] = {}
				for slot_index, _ in enumerate(self._theory_slot_labels):
					var_name = f"grp_{group_id}_d{day_index}_t{slot_index}"
					group_timeslots[group_id][day_index][slot_index] = model.NewBoolVar(var_name)

		return TheoryVariableBlock(
			group_timeslots=group_timeslots,
			requirements=requirements,
			day_patterns=day_patterns,
			theory_slot_labels=self._theory_slot_labels,
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
			)
		return requirements

	def _group_requirements_by_teacher(
		self,
		requirements: Mapping[str, LabCourseRequirement],
	) -> Dict[str, Tuple[LabCourseRequirement, ...]]:
		grouped: Dict[str, Tuple[LabCourseRequirement, ...]] = {}
		buffer: MutableMapping[str, list] = defaultdict(list)
		for requirement in requirements.values():
			buffer[requirement.teacher_id].append(requirement)
		for teacher_id, entries in buffer.items():
			grouped[teacher_id] = tuple(sorted(entries, key=lambda item: item.course_instance_id))
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


__all__ = [
	"LabVariableBlock",
	"TheoryVariableBlock",
	"LabCourseRequirement",
	"GroupTimeslotRequirement",
	"VariableCreationResult",
	"VariableCreator",
]
