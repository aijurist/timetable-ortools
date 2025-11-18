from ortools.sat.python import cp_model
from ..data.schemas import GroupRequirement

from dataclasses import dataclass, field
from typing import Dict, Mapping,Optional, Tuple

LabAssignmentDict = Dict[str, Dict[str, Dict[int, Dict[str, Dict[str, cp_model.IntVar]]]]]
GroupTimeslotDict = Dict[str, Dict[int, Dict[int, cp_model.IntVar]]]

@dataclass(frozen=True)
class LabCourseRequirement:
	course_instance_id: str
	course_code: str
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
