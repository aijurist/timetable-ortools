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

	def to_dict(self) -> Dict[str, object]:
		return {
			"teacher_id": self.teacher_id,
			"teacher_name": self.teacher_name,
			"course_instance_id": self.course_instance_id,
			"course_code": self.course_code,
			"course_name": self.course_name,
			"group_id": self.group_id,
			"department": self.department,
			"semester": self.semester,
			"day": self.day,
			"day_index": self.day_index,
			"session_name": self.session_name,
			"session_slots": self.session_slots,
			"session_time": self.session_time,
			"room_id": self.room_id,
			"student_count": self.student_count,
			"tags": self.tags,
			"is_lunch_window": self.is_lunch_window,
			"five_pm_policy": self.five_pm_policy,
			"five_pm_flag": self.five_pm_flag,
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

	def to_dict(self) -> Dict[str, object]:
		return {
			"group_id": self.group_id,
			"department": self.department,
			"semester": self.semester,
			"day": self.day,
			"day_index": self.day_index,
			"slot_index": self.slot_index,
			"slot_label": self.slot_label,
			"teacher_ids": self.teacher_ids,
			"teacher_names": self.teacher_names,
			"course_codes": self.course_codes,
			"is_lunch_window": self.is_lunch_window,
			"five_pm_policy": self.five_pm_policy,
			"five_pm_flag": self.five_pm_flag,
			"tags": self.tags,
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