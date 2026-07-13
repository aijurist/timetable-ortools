import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from ..config.schemas import (
    DepartmentSettings,
    SchedulerConfig,
)

if TYPE_CHECKING:
    from .schedule_blocking import ScheduleBlockingMask


def dataclass_to_dict(instance: Any) -> Dict[str, Any]:

	if instance is None:
		return {}
	if hasattr(instance, "__dataclass_fields__"):
		result: Dict[str, Any] = {}
		for field_name in instance.__dataclass_fields__:
			value = getattr(instance, field_name)
			if isinstance(value, tuple) and value and hasattr(value[0], "__dataclass_fields__"):
				result[field_name] = [dataclass_to_dict(item) for item in value]
			elif hasattr(value, "__dataclass_fields__"):
				result[field_name] = dataclass_to_dict(value)
			elif isinstance(value, (tuple, list)):
				result[field_name] = list(value)
			elif isinstance(value, Mapping):
				result[field_name] = dict(value)
			else:
				result[field_name] = value
		return result
	return instance


@dataclass(frozen=True)
class LabSessionDetail:
    """Snapshot of a lab session window (L1–L6) in the legacy scheduler."""

    name: str
    slots: Tuple[int, ...]
    time_range: str

    @property
    def start_slot(self) -> int:
        return self.slots[0]

    @property
    def end_slot(self) -> int:
        return self.slots[-1]


@dataclass(frozen=True)
class TimeSystemArtifacts:
    """Aggregated time-system data mirroring legacy combined scheduler semantics."""

    theory_slots: Tuple[str, ...]
    lab_slots: Tuple[str, ...]
    lab_sessions: Dict[str, LabSessionDetail]
    working_days: Tuple[str, ...]
    lab_slot_to_theory: Dict[int, Tuple[int, ...]]
    theory_slot_to_lab: Dict[int, Tuple[int, ...]]
    lab_session_to_theory: Dict[str, Tuple[int, ...]]

    @property
    def num_lab_slots(self) -> int:
        return len(self.lab_slots)

    @property
    def num_theory_slots(self) -> int:
        return len(self.theory_slots)

    @property
    def num_lab_sessions(self) -> int:
        return len(self.lab_sessions)


@dataclass(frozen=True)
class ShiftDefinitionSnapshot:
    """Adapts `ShiftTemplate` into the structure used by the legacy scheduler."""

    identifier: str
    theory_slots: Tuple[int, ...]
    lab_sessions: Tuple[str, ...]
    start_time: str
    end_time: str
    label: str


@dataclass(frozen=True)
class DepartmentArtifacts:
    """Department-level defaults and overrides used downstream."""

    default_settings: DepartmentSettings
    overrides: Dict[str, DepartmentSettings]
    day_patterns: Dict[str, Tuple[str, ...]]
    lunch_break_slots: Dict[str, Optional[int]]
    lunch_slot_windows: Dict[str, Tuple[int, ...]]
    shift_assignments: Dict[str, str]
    shift_definitions: Dict[str, ShiftDefinitionSnapshot]
    valid_shift_patterns: Tuple[Tuple[int, int], ...]
    flexible_lunch_departments: Tuple[str, ...]
    five_pm_constraints: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class RoomCollections:
    """Convenience grouping for room subsets needed by the scheduler."""

    lab_rooms: pd.DataFrame
    theory_rooms: pd.DataFrame
    lab_room_ids: Tuple[str, ...]
    theory_room_ids: Tuple[str, ...]
    laboratory_room_ids: Tuple[str, ...]


@dataclass(frozen=True)
class DataLoadResult:
    """Structured view of all artefacts produced during data loading."""

    config: SchedulerConfig
    courses_df: pd.DataFrame
    rooms_df: pd.DataFrame
    day_order_df: Optional[pd.DataFrame]
    core_lab_mapping_df: Optional[pd.DataFrame]
    computer_lab_mapping_df: Optional[pd.DataFrame]
    teacher_preferences_df: Optional[pd.DataFrame]
    time: TimeSystemArtifacts
    departments: DepartmentArtifacts
    rooms: RoomCollections
    teachers: Tuple[str, ...]
    departments_list: Tuple[str, ...]
    room_registry: Dict[str, Dict[str, Any]]
    load_timestamp: datetime
    blocking_mask: Optional["ScheduleBlockingMask"] = None

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Provide a dict closely matching the combined scheduler runtime state."""

        time = self.time
        departments = self.departments
        rooms = self.rooms

        lab_sessions_payload = {
            name: {"slots": detail.slots, "time_range": detail.time_range}
            for name, detail in time.lab_sessions.items()
        }

        shift_payload = {
            identifier: {
                "name": snapshot.label,
                "theory_slots": snapshot.theory_slots,
                "lab_sessions": snapshot.lab_sessions,
                "start_time": snapshot.start_time,
                "end_time": snapshot.end_time,
            }
            for identifier, snapshot in departments.shift_definitions.items()
        }

        shift_departments = {
            dept: {
                "enabled": True,
                "shift_id": shift_id,
                "description": f"Department assigned to {shift_id}",
            }
            for dept, shift_id in departments.shift_assignments.items()
        }

        return {
            "courses_df": self.courses_df,
            "rooms_df": self.rooms_df,
            "day_order_df": self.day_order_df,
            "lab_time_slots": time.lab_slots,
            "num_lab_slots": time.num_lab_slots,
            "lab_sessions": lab_sessions_payload,
            "lab_sessions_details": lab_sessions_payload,
            "num_lab_sessions": time.num_lab_sessions,
            "theory_time_slots": time.theory_slots,
            "num_theory_slots": time.num_theory_slots,
            "lab_to_theory_mapping": time.lab_slot_to_theory,
            "theory_to_lab_mapping": time.theory_slot_to_lab,
            "lab_session_to_theory_mapping": time.lab_session_to_theory,
            "shift_definitions": shift_payload,
            "valid_shift_patterns": departments.valid_shift_patterns,
            "shift_departments": shift_departments,
            "lunch_slot_windows": departments.lunch_slot_windows,
            "flexible_lunch_departments": departments.flexible_lunch_departments,
            "five_pm_constraints": departments.five_pm_constraints,
            "lab_rooms": rooms.lab_rooms,
            "theory_rooms": rooms.theory_rooms,
            "lab_room_ids": rooms.lab_room_ids,
            "theory_room_ids": rooms.theory_room_ids,
            "laboratory_room_ids": rooms.laboratory_room_ids,
            "teachers": self.teachers,
            "departments": self.departments_list,
            "room_registry": self.room_registry,
            "core_lab_mapping_df": self.core_lab_mapping_df,
            "computer_lab_mapping_df": self.computer_lab_mapping_df,
            "teacher_preferences_df": self.teacher_preferences_df,
            "working_days": time.working_days,
            "num_days": len(time.working_days),
            "horizon": len(time.working_days) * time.num_theory_slots,
            "load_timestamp": self.load_timestamp.isoformat(timespec="seconds"),
        }

@dataclass(frozen=True)
class DepartmentSemesterKey:
	"""Hashable key referencing a (department, semester) pair."""

	department: str
	semester: int

	def slug(self) -> str:
		safe_department = "".join(ch if ch.isalnum() else "_" for ch in self.department.lower()).strip("_")
		return f"{safe_department or 'dept'}_s{self.semester}"

	def label(self) -> str:
		return f"{self.department} S{self.semester}"


@dataclass(frozen=True)
class NormalizedCourseInstance:
	"""Course instance enriched with all metadata required for grouping."""

	instance_id: str
	course_id: str
	course_code: str
	course_name: str
	course_type: str
	semester: int
	student_dept: str
	course_dept: str
	teacher_id: str
	teacher_name: str
	assistant_teacher_id: Optional[str]
	assistant_teacher_name: Optional[str]
	has_lab: bool
	has_theory: bool
	lecture_hours: int
	tutorial_hours: int
	practical_hours: int
	student_count: int
	requires_special_scheduling: bool
	requires_assistant: bool
	preferred_lab_type: Optional[str]
	preferred_room_type: Optional[str]
	required_room_type: Optional[str]
	pe_flag: bool
	tags: Tuple[str, ...] = field(default_factory=tuple)
	metadata: Mapping[str, Any] = field(default_factory=dict)
	raw_row_index: Optional[int] = None

	def total_hours(self) -> int:
		return self.lecture_hours + self.tutorial_hours + self.practical_hours

	def group_category(self) -> str:
		return "lab" if self.has_lab else "theory"

	def to_optimizer_payload(self) -> Dict[str, Any]:
		"""Convert to the dictionary structure expected by CourseGroupOptimizer."""

		return {
			"id": self.instance_id,
			"course_id": self.course_id,
			"course_code": self.course_code,
			"course_name": self.course_name,
			"course_type": self.course_type,
			"teacher_id": self.teacher_id,
			"semester": self.semester,
			"course_dept": self.course_dept,
			"student_dept": self.student_dept,
			"lecture_hours": self.lecture_hours,
			"tutorial_hours": self.tutorial_hours,
			"practical_hours": self.practical_hours,
			"student_count": self.student_count,
			"has_lab": self.has_lab,
			"has_theory": self.has_theory,
		}

	def as_dict(self) -> Dict[str, Any]:
		return {
			"instance_id": self.instance_id,
			"course_id": self.course_id,
			"course_code": self.course_code,
			"course_name": self.course_name,
			"course_type": self.course_type,
			"semester": self.semester,
			"student_dept": self.student_dept,
			"course_dept": self.course_dept,
			"teacher_id": self.teacher_id,
			"teacher_name": self.teacher_name,
			"assistant_teacher_id": self.assistant_teacher_id,
			"assistant_teacher_name": self.assistant_teacher_name,
			"has_lab": self.has_lab,
			"has_theory": self.has_theory,
			"lecture_hours": self.lecture_hours,
			"tutorial_hours": self.tutorial_hours,
			"practical_hours": self.practical_hours,
			"student_count": self.student_count,
			"requires_special_scheduling": self.requires_special_scheduling,
			"requires_assistant": self.requires_assistant,
			"preferred_lab_type": self.preferred_lab_type,
			"preferred_room_type": self.preferred_room_type,
			"required_room_type": self.required_room_type,
			"pe_flag": self.pe_flag,
			"tags": self.tags,
			"metadata": dict(self.metadata),
			"raw_row_index": self.raw_row_index,
		}


@dataclass(frozen=True)
class GroupSummary:
	num_instances: int
	num_courses: int
	num_teachers: int
	lab_instances: int
	theory_instances: int
	total_student_count: int
	lab_hours: int
	theory_hours: int


@dataclass(frozen=True)
class CourseGroup:
	key: DepartmentSemesterKey
	group_id: str
	ordinal: int
	is_professional_elective: bool
	course_instance_ids: Tuple[str, ...]
	teacher_ids: Tuple[str, ...]
	course_codes: Tuple[str, ...]
	summary: GroupSummary
	tags: Tuple[str, ...] = field(default_factory=tuple)

	def as_dict(self) -> Dict[str, Any]:
		return {
			"group_id": self.group_id,
			"ordinal": self.ordinal,
			"department": self.key.department,
			"semester": self.key.semester,
			"is_professional_elective": self.is_professional_elective,
			"course_instance_ids": self.course_instance_ids,
			"teacher_ids": self.teacher_ids,
			"course_codes": self.course_codes,
			"summary": dataclass_to_dict(self.summary),
			"tags": self.tags,
		}


@dataclass(frozen=True)
class KuttyBundle:
	"""A permanent second-year theory offering pair.

	Matched bundles teach ``first`` then ``second`` for 25 minutes each in the
	same room for the common portion of their theory load.  When one course has
	more lecture/tutorial hours, the excess is retained inside the same bundle
	as ordinary 50-minute remainder blocks.  A singleton is an explicit
	full-slot fallback for an odd or genuinely infeasible course code.
	"""

	key: DepartmentSemesterKey
	bundle_id: str
	bundle_group_id: str
	first_instance_id: str
	first_group_id: str
	second_instance_id: Optional[str]
	second_group_id: Optional[str]
	delivery_mode: str
	# Number of shared physical 50-minute blocks.  Each block contains one
	# 25-minute half for each course.
	required_blocks: int
	# Kept for backwards compatibility; this is the first course's L+T load.
	theory_hours: int
	second_theory_hours: int
	first_remainder_blocks: int
	second_remainder_blocks: int
	pairing_score: int
	feasible_slot_count: int
	score_breakdown: Mapping[str, int] = field(default_factory=dict)
	tags: Tuple[str, ...] = field(default_factory=tuple)

	@property
	def is_paired(self) -> bool:
		return bool(self.second_instance_id)

	@property
	def instance_ids(self) -> Tuple[str, ...]:
		if self.second_instance_id:
			return self.first_instance_id, self.second_instance_id
		return (self.first_instance_id,)

	@property
	def shared_blocks(self) -> int:
		return self.required_blocks if self.is_paired else 0

	def remainder_blocks_for(self, instance_id: str) -> int:
		if instance_id == self.first_instance_id:
			return self.first_remainder_blocks
		if instance_id == self.second_instance_id:
			return self.second_remainder_blocks
		return 0

	def as_dict(self) -> Dict[str, Any]:
		return {
			"bundle_id": self.bundle_id,
			"bundle_group_id": self.bundle_group_id,
			"department": self.key.department,
			"semester": self.key.semester,
			"first_instance_id": self.first_instance_id,
			"first_group_id": self.first_group_id,
			"second_instance_id": self.second_instance_id,
			"second_group_id": self.second_group_id,
			"delivery_mode": self.delivery_mode,
			"required_blocks": self.required_blocks,
			"theory_hours": self.theory_hours,
			"second_theory_hours": self.second_theory_hours,
			"first_remainder_blocks": self.first_remainder_blocks,
			"second_remainder_blocks": self.second_remainder_blocks,
			"pairing_score": self.pairing_score,
			"feasible_slot_count": self.feasible_slot_count,
			"score_breakdown": dict(self.score_breakdown),
			"tags": self.tags,
		}


@dataclass(frozen=True)
class GroupRequirement:
	group_id: str
	department: str
	semester: int
	has_lab: bool
	required_lab_sessions: int
	prefer_consecutive_labs: bool
	lunch_slot_window: Tuple[int, ...]
	five_pm_policy: Optional[str]
	tags: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GroupPenaltySpec:
	name: str
	weight: float
	description: str
	applies_to: Tuple[str, ...] = field(default_factory=tuple)
	params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TeacherWorkloadSummary:
	teacher_id: str
	teacher_name: str
	groups: Tuple[str, ...]
	course_codes: Tuple[str, ...]
	course_instance_ids: Tuple[str, ...]
	total_hours: int
	lab_hours: int
	theory_hours: int
	total_students: int


@dataclass(frozen=True)
class DepartmentSchedulingPackage:
	key: DepartmentSemesterKey
	requirements: Tuple[GroupRequirement, ...]
	penalties: Tuple[GroupPenaltySpec, ...]
	teacher_workload: Mapping[str, TeacherWorkloadSummary]
	metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreprocessingResult:
	normalized_instances: Mapping[DepartmentSemesterKey, Tuple[NormalizedCourseInstance, ...]]
	groups: Mapping[DepartmentSemesterKey, Tuple[CourseGroup, ...]]
	scheduling_packages: Mapping[DepartmentSemesterKey, DepartmentSchedulingPackage]
	warnings: Tuple[str, ...]
	stats: Mapping[str, Any]
	kutty_bundles: Mapping[DepartmentSemesterKey, Tuple[KuttyBundle, ...]] = field(default_factory=dict)

	def to_dict(self) -> Dict[str, Any]:
		return {
			"normalized_instances": {
				key.slug(): [instance.as_dict() for instance in instances]
				for key, instances in self.normalized_instances.items()
			},
			"groups": {
				key.slug(): [group.as_dict() for group in groups]
				for key, groups in self.groups.items()
			},
			"scheduling_packages": {
				key.slug(): {
					"requirements": [dataclass_to_dict(req) for req in package.requirements],
					"penalties": [dataclass_to_dict(penalty) for penalty in package.penalties],
					"teacher_workload": {
						teacher_id: dataclass_to_dict(summary)
						for teacher_id, summary in package.teacher_workload.items()
					},
					"metadata": dict(package.metadata),
				}
				for key, package in self.scheduling_packages.items()
			},
			"kutty_bundles": {
				key.slug(): [bundle.as_dict() for bundle in bundles]
				for key, bundles in self.kutty_bundles.items()
			},
			"warnings": list(self.warnings),
			"stats": dict(self.stats),
		}


@dataclass(frozen=True)
class ExtendedDataContainer:
	"""Convenience bundle combining raw load artefacts with preprocessing outputs."""

	raw: DataLoadResult
	preprocessing: PreprocessingResult

