from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LabScheduleEntry:
	teacher_id: str
	teacher_name: str
	course_instance_id: str
	course_code: str
	course_name: str
	group_id: str
	department: str
	semester: int
	day: str
	day_index: int
	session_name: str
	session_slots: Tuple[int, ...]
	session_time: str
	room_id: str
	student_count: int
	tags: Tuple[str, ...]
	is_lunch_window: bool
	five_pm_policy: Optional[str]
	five_pm_flag: bool
	# Legacy export metadata
	course_code_display: Optional[str] = None
	practical_hours: int = 0
	staff_code: Optional[str] = None
	room_number: Optional[str] = None
	block: Optional[str] = None
	capacity: Optional[int] = None
	total_students: Optional[int] = None
	is_batched: bool = False
	batch_info: Optional[str] = None
	num_batches: int = 1
	batch_number: Optional[int] = None
	batch_label: Optional[str] = None
	schedule_type: str = "lab"
	group_name: Optional[str] = None
	group_index: Optional[int] = None
	day_pattern: Optional[str] = None
	is_co_scheduled: bool = False
	co_schedule_id: Optional[str] = None
	co_schedule_group_size: int = 1
	co_schedule_partner_teachers: Optional[str] = None
	co_schedule_info: Optional[str] = None
	capacity_info: Optional[str] = None

	def to_dict(self) -> Dict[str, object]:
		return {
			"day": self.day,
			"session_name": self.session_name,
			"time_range": self.session_time,
			"course_instance_id": self.course_instance_id,
			"course_code": self.course_code,
			"course_code_display": self.course_code_display or self.course_code,
			"course_name": self.course_name,
			"practical_hours": self.practical_hours,
			"teacher_id": self.teacher_id,
			"teacher_name": self.teacher_name,
			"staff_code": self.staff_code or self.teacher_id,
			"room_id": self.room_id,
			"room_number": self.room_number,
			"block": self.block,
			"capacity": self.capacity,
			"student_count": self.student_count,
			"total_students": self.total_students or self.student_count,
			"is_batched": self.is_batched,
			"batch_info": self.batch_info,
			"num_batches": self.num_batches,
			"batch_number": self.batch_number,
			"batch_label": self.batch_label or self.batch_info,
			"schedule_type": self.schedule_type,
			"group_name": self.group_name or self.group_id,
			"group_index": self.group_index,
			"department": self.department,
			"semester": self.semester,
			"day_pattern": self.day_pattern or "",
			"is_co_scheduled": self.is_co_scheduled,
			"co_schedule_id": self.co_schedule_id,
			"co_schedule_group_size": self.co_schedule_group_size,
			"co_schedule_partner_teachers": self.co_schedule_partner_teachers,
			"co_schedule_info": self.co_schedule_info,
			"capacity_info": self.capacity_info,
		}


@dataclass(frozen=True)
class TheoryScheduleEntry:
	group_id: str
	department: str
	semester: int
	day: str
	day_index: int
	slot_index: int
	slot_label: str
	teacher_ids: Tuple[str, ...]
	teacher_names: Tuple[str, ...]
	course_codes: Tuple[str, ...]
	is_lunch_window: bool
	five_pm_policy: Optional[str]
	five_pm_flag: bool
	tags: Tuple[str, ...]
	course_instance_id: Optional[str] = None
	course_code: Optional[str] = None
	course_name: Optional[str] = None
	session_type: Optional[str] = None
	session_number: int = 0
	teacher_id: Optional[str] = None
	teacher_name: Optional[str] = None
	staff_code: Optional[str] = None
	room_id: Optional[str] = None
	room_number: Optional[str] = None
	block: Optional[str] = None
	student_count: Optional[int] = None
	lecture_hours: Optional[int] = None
	tutorial_hours: Optional[int] = None
	schedule_type: str = "theory"
	group_name: Optional[str] = None
	group_index: Optional[int] = None
	day_pattern: Optional[str] = None
	is_co_scheduled: bool = False
	capacity_info: Optional[str] = None
	partner_instance_id: Optional[str] = None
	delivery_mode: str = "legacy_full_slot"
	bundle_id: Optional[str] = None
	bundle_group_id: Optional[str] = None
	bundle_label: Optional[str] = None
	bundle_course_codes: Tuple[str, ...] = field(default_factory=tuple)
	bundle_teacher_ids: Tuple[str, ...] = field(default_factory=tuple)
	half_index: Optional[int] = None
	half_minutes: int = 50
	half_time: Optional[str] = None
	partner_course_code: Optional[str] = None
	partner_teacher_id: Optional[str] = None
	partner_teacher_name: Optional[str] = None
	pairing_score: int = 0
	selection_mode: str = "CHOOSE_FACULTY"

	def to_dict(self) -> Dict[str, object]:
		return {
			"day": self.day,
			"time_slot": self.slot_label,
			"slot_index": self.slot_index,
			"course_instance_id": self.course_instance_id,
			"course_code": self.course_code or (self.course_codes[0] if self.course_codes else None),
			"course_name": self.course_name,
			"session_type": self.session_type,
			"session_number": self.session_number,
			"teacher_id": self.teacher_id or (self.teacher_ids[0] if self.teacher_ids else None),
			"teacher_name": self.teacher_name or (self.teacher_names[0] if self.teacher_names else None),
			"staff_code": self.staff_code or self.teacher_id,
			"room_id": self.room_id,
			"room_number": self.room_number,
			"block": self.block,
			"student_count": self.student_count,
			"lecture_hours": self.lecture_hours,
			"tutorial_hours": self.tutorial_hours,
			"schedule_type": self.schedule_type,
			"is_co_scheduled": self.is_co_scheduled,
			"capacity_info": self.capacity_info,
			"partner_instance_id": self.partner_instance_id,
			"delivery_mode": self.delivery_mode,
			"bundle_id": self.bundle_id,
			"bundle_group_id": self.bundle_group_id,
			"bundle_label": self.bundle_label,
			"bundle_course_codes": self.bundle_course_codes,
			"bundle_teacher_ids": self.bundle_teacher_ids,
			"half_index": self.half_index,
			"half_minutes": self.half_minutes,
			"half_time": self.half_time,
			"partner_course_code": self.partner_course_code,
			"partner_teacher_id": self.partner_teacher_id,
			"partner_teacher_name": self.partner_teacher_name,
			"pairing_score": self.pairing_score,
			"selection_mode": self.selection_mode,
			"group_name": self.group_name or self.group_id,
			"group_index": self.group_index,
			"department": self.department,
			"semester": self.semester,
			"day_pattern": self.day_pattern or "",
		}


@dataclass(frozen=True)
class CombinedScheduleEntry:
	entry_type: str
	department: str
	semester: int
	group_id: Optional[str]
	identifier: str
	day: str
	label: str
	resource_id: Optional[str]
	payload: Mapping[str, object]

	def to_dict(self) -> Dict[str, object]:
		return {
			"entry_type": self.entry_type,
			"department": self.department,
			"semester": self.semester,
			"group_id": self.group_id,
			"identifier": self.identifier,
			"day": self.day,
			"label": self.label,
			"resource_id": self.resource_id,
			"payload": dict(self.payload),
		}


@dataclass(frozen=True)
class InstanceAssignment:
	course_instance_id: str
	group_id: Optional[str]
	department: Optional[str]
	semester: Optional[int]
	lab_entries: Tuple[LabScheduleEntry, ...]
	theory_entries: Tuple[TheoryScheduleEntry, ...]

	def to_dict(self) -> Dict[str, object]:
		return {
			"course_instance_id": self.course_instance_id,
			"group_id": self.group_id,
			"department": self.department,
			"semester": self.semester,
			"lab_entries": [entry.to_dict() for entry in self.lab_entries],
			"theory_entries": [entry.to_dict() for entry in self.theory_entries],
		}


@dataclass(frozen=True)
class ScheduleExtractionResult:
	lab_entries: Tuple[LabScheduleEntry, ...]
	theory_entries: Tuple[TheoryScheduleEntry, ...]
	combined_entries: Tuple[CombinedScheduleEntry, ...]
	instance_index: Mapping[str, InstanceAssignment]

	def to_dict(self) -> Dict[str, object]:
		return {
			"lab_entries": [entry.to_dict() for entry in self.lab_entries],
			"theory_entries": [entry.to_dict() for entry in self.theory_entries],
			"combined_entries": [entry.to_dict() for entry in self.combined_entries],
			"instance_index": {key: value.to_dict() for key, value in self.instance_index.items()},
		}

	def write_json(self, destination: Path) -> Path:
		destination.parent.mkdir(parents=True, exist_ok=True)
		destination.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
		return destination

	def write_csv_bundle(self, directory: Path) -> Tuple[Path, Path]:
		directory.mkdir(parents=True, exist_ok=True)
		lab_path = directory / "lab_schedule.csv"
		theory_path = directory / "theory_schedule.csv"
		_write_csv(lab_path, self.lab_entries[0].to_dict().keys() if self.lab_entries else [], self.lab_entries)
		_write_csv(
			theory_path,
			self.theory_entries[0].to_dict().keys() if self.theory_entries else [],
			self.theory_entries,
		)
		return lab_path, theory_path


def _write_csv(path: Path, headers: Iterable[str], entries: Sequence[object]) -> None:
	if not entries:
		path.write_text("", encoding="utf-8")
		return
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", newline="", encoding="utf-8") as handle:
		writer = csv.DictWriter(handle, fieldnames=list(headers))
		writer.writeheader()
		for entry in entries:
			writer.writerow(entry.to_dict())


@dataclass(frozen=True)
class FivePmPolicy:
	policy: str
	blocked_theory_slots: Tuple[int, ...] = field(default_factory=tuple)
	blocked_lab_sessions: Tuple[str, ...] = field(default_factory=tuple)
	discouraged_theory_slots: Tuple[int, ...] = field(default_factory=tuple)
	discouraged_lab_sessions: Tuple[str, ...] = field(default_factory=tuple)
