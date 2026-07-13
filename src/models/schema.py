from ortools.sat.python import cp_model
from ..data.schemas import GroupRequirement, KuttyBundle

from dataclasses import dataclass, field
from typing import Dict, Mapping,Optional, Tuple

LabAssignmentDict = Dict[str, Dict[str, Dict[int, Dict[str, Dict[str, cp_model.IntVar]]]]]
TheoryAssignmentDict = Dict[str, Dict[str, Dict[int, Dict[int, cp_model.IntVar]]]]
TheoryRoomAssignmentDict = Dict[str, Dict[str, Dict[int, Dict[int, Dict[str, cp_model.IntVar]]]]]
GroupTimeslotDict = Dict[str, Dict[int, Dict[int, cp_model.IntVar]]]
KuttyBundleAssignmentDict = Dict[str, Dict[int, Dict[int, cp_model.IntVar]]]
KuttyBundleRoomAssignmentDict = Dict[str, Dict[int, Dict[int, Dict[str, cp_model.IntVar]]]]

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
class TheoryCourseRequirement:
	course_instance_id: str
	course_code: str
	group_id: str
	teacher_id: str
	department: str
	semester: int
	required_slots: int
	lecture_hours: int
	tutorial_hours: int
	student_count: int
	preferred_room_type: Optional[str]
	required_room_type: Optional[str]
	# Synthetic remainder components keep their own variable key while pointing
	# back to the real course instance used in exports and bundle selection.
	source_instance_id: Optional[str] = None
	tags: Tuple[str, ...] = field(default_factory=tuple)
	delivery_mode: str = "legacy_full_slot"
	bundle_id: Optional[str] = None
	bundle_group_id: Optional[str] = None
	partner_instance_id: Optional[str] = None
	selection_group_id: Optional[str] = None
	half_index: Optional[int] = None
	half_minutes: int = 50
	pairing_score: int = 0
	schedule_component: str = "full_slot"
	session_sequence_offset: int = 0


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
	assignments: TheoryAssignmentDict = field(default_factory=dict)
	room_assignments: TheoryRoomAssignmentDict = field(default_factory=dict)
	course_requirements: Mapping[str, TheoryCourseRequirement] = field(default_factory=dict)
	teacher_courses: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
	course_day_patterns: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
	group_timeslots: GroupTimeslotDict = field(default_factory=dict)
	requirements: Mapping[str, GroupTimeslotRequirement] = field(default_factory=dict)
	day_patterns: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
	theory_slot_labels: Tuple[str, ...] = field(default_factory=tuple)
	group_course_index: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
	instance_group_lookup: Mapping[str, str] = field(default_factory=dict)
	room_ids: Tuple[str, ...] = field(default_factory=tuple)
	bundle_specs: Mapping[str, KuttyBundle] = field(default_factory=dict)
	bundle_assignments: KuttyBundleAssignmentDict = field(default_factory=dict)
	bundle_room_assignments: KuttyBundleRoomAssignmentDict = field(default_factory=dict)
	instance_bundle_lookup: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VariableCreationResult:
	lab: LabVariableBlock
	theory: TheoryVariableBlock
	metadata: Mapping[str, int]
