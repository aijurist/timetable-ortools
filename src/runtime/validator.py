"""Schedule validation utilities derived from the legacy combined analytics suite."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

from ..data.schemas import ExtendedDataContainer, NormalizedCourseInstance
from ..models.model_builder import ConstraintModel
from .extractor_schema import (
	LabScheduleEntry,
	ScheduleExtractionResult,
	TheoryScheduleEntry,
)

LOGGER = logging.getLogger(__name__)


class ValidationSeverity:
	"""String constants describing severity levels."""

	ERROR = "error"
	WARNING = "warning"
	INFO = "info"


@dataclass(frozen=True)
class ValidationIssue:
	"""Single validation result emitted by a check."""

	category: str
	severity: str
	message: str
	context: Mapping[str, object] = field(default_factory=dict)

	def to_dict(self) -> Dict[str, object]:
		return {
			"category": self.category,
			"severity": self.severity,
			"message": self.message,
			"context": dict(self.context),
		}


@dataclass(frozen=True)
class ValidationReport:
	"""Aggregated response returned by :meth:`ScheduleValidator.validate`."""

	generated_at: datetime
	issues: Tuple[ValidationIssue, ...]
	executed_checks: Tuple[str, ...]
	severity_counts: Mapping[str, int]
	metadata: Mapping[str, object]

	def to_dict(self) -> Dict[str, object]:
		return {
			"generated_at": self.generated_at.isoformat(timespec="seconds"),
			"issues": [issue.to_dict() for issue in self.issues],
			"executed_checks": self.executed_checks,
			"severity_counts": dict(self.severity_counts),
			"metadata": dict(self.metadata),
		}

	@property
	def has_errors(self) -> bool:
		return self.severity_counts.get(ValidationSeverity.ERROR, 0) > 0


class ScheduleValidator:
	"""Perform structural validations on extracted lab and theory schedules."""

	def __init__(
		self,
		data: ExtendedDataContainer,
		constraint_model: ConstraintModel,
		*,
		logger_: Optional[logging.Logger] = None,
	) -> None:
		self._data = data
		self._model = constraint_model
		self._logger = logger_ or LOGGER.getChild("ScheduleValidator")
		self._time = data.raw.time
		self._lab_requirements = constraint_model.variables.lab.requirements
		self._theory_requirements = constraint_model.variables.theory.requirements
		self._theory_course_requirements = getattr(
			constraint_model.variables.theory,
			"course_requirements",
			{},
		)
		self._instance_lookup = self._build_instance_lookup(data)
		self._instance_group_lookup = dict(constraint_model.variables.lab.instance_group_lookup)
		self._check_registry = self._build_check_registry()

	def validate(
		self,
		schedule: ScheduleExtractionResult,
		*,
		checks: Optional[Iterable[str]] = None,
	) -> ValidationReport:
		"""Run configured checks against the provided schedule payload."""

		issues: List[ValidationIssue] = []
		executed: List[str] = []
		selected = self._resolve_checks(checks)
		self._logger.debug("Executing %d validation checks", len(selected))
		for name, check in selected:
			executed.append(name)
			issues.extend(check(schedule))
		severity_counts = Counter(issue.severity for issue in issues)
		metadata = {
			"lab_entries": len(schedule.lab_entries),
			"theory_entries": len(schedule.theory_entries),
			"combined_entries": len(schedule.combined_entries),
		}
		return ValidationReport(
			generated_at=datetime.utcnow(),
			issues=tuple(issues),
			executed_checks=tuple(executed),
			severity_counts=severity_counts,
			metadata=metadata,
		)

	def _resolve_checks(self, requested: Optional[Iterable[str]]) -> List[Tuple[str, Callable[[ScheduleExtractionResult], List[ValidationIssue]]]]:
		if not requested:
			return list(self._check_registry.items())
		selected: List[Tuple[str, Callable[[ScheduleExtractionResult], List[ValidationIssue]]]] = []
		for name in requested:
			check = self._check_registry.get(name)
			if check:
				selected.append((name, check))
			else:
				self._logger.warning("Unknown validation check '%s' skipped", name)
		return selected

	def _build_check_registry(self) -> Mapping[str, Callable[[ScheduleExtractionResult], List[ValidationIssue]]]:
		return {
			"lab_teacher_conflicts": self._check_lab_teacher_conflicts,
			"theory_teacher_conflicts": self._check_theory_teacher_conflicts,
			"lab_room_conflicts": self._check_lab_room_conflicts,
			"group_overlaps": self._check_group_overlaps,
			"theory_lab_conflicts": self._check_theory_lab_conflicts,
			"lab_coverage": self._check_lab_session_coverage,
			"theory_coverage": self._check_theory_slot_coverage,
			"ltp_presence": self._check_instance_presence,
		}

	def _check_lab_teacher_conflicts(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
		bucket: MutableMapping[Tuple[str, int, str], List[LabScheduleEntry]] = defaultdict(list)
		for entry in schedule.lab_entries:
			bucket[(entry.teacher_id, entry.day_index, entry.session_name)].append(entry)
		issues: List[ValidationIssue] = []
		for key, entries in bucket.items():
			if len(entries) <= 1:
				continue
			teacher_id, day_index, session_name = key
			issues.append(
				ValidationIssue(
					category="lab_teacher_conflict",
					severity=ValidationSeverity.ERROR,
					message=f"Teacher {teacher_id} double-booked for lab session {session_name} on day {day_index}",
					context={
						"teacher_id": teacher_id,
						"day_index": day_index,
						"session": session_name,
						"course_instance_ids": [entry.course_instance_id for entry in entries],
						"rooms": [entry.room_id for entry in entries],
					},
				)
			)
		return issues

	def _check_theory_teacher_conflicts(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
		bucket: MutableMapping[Tuple[str, int, int], List[str]] = defaultdict(list)
		for entry in schedule.theory_entries:
			for teacher_id in entry.teacher_ids:
				key = (teacher_id, entry.day_index, entry.slot_index)
				bucket[key].append(entry.group_id)
		issues: List[ValidationIssue] = []
		for (teacher_id, day_index, slot_index), groups in bucket.items():
			if len(groups) <= 1:
				continue
			issues.append(
				ValidationIssue(
					category="theory_teacher_conflict",
					severity=ValidationSeverity.ERROR,
					message=f"Teacher {teacher_id} assigned to multiple theory groups at slot {slot_index} on day {day_index}",
					context={
						"teacher_id": teacher_id,
						"day_index": day_index,
						"slot_index": slot_index,
						"group_ids": groups,
					},
				)
			)
		return issues

	def _check_lab_room_conflicts(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
		bucket: MutableMapping[Tuple[str, int, str], List[LabScheduleEntry]] = defaultdict(list)
		for entry in schedule.lab_entries:
			bucket[(entry.room_id, entry.day_index, entry.session_name)].append(entry)
		issues: List[ValidationIssue] = []
		for (room_id, day_index, session_name), entries in bucket.items():
			if len(entries) <= 1:
				continue
			issues.append(
				ValidationIssue(
					category="lab_room_conflict",
					severity=ValidationSeverity.ERROR,
					message=f"Room {room_id} allocated to multiple labs during {session_name} on day {day_index}",
					context={
						"room_id": room_id,
						"day_index": day_index,
						"session": session_name,
						"course_instance_ids": [entry.course_instance_id for entry in entries],
					},
				)
			)
		return issues

	def _check_group_overlaps(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
		bucket: MutableMapping[Tuple[str, int, int, int], List[str]] = defaultdict(list)
		for entry in schedule.theory_entries:
			bucket[(entry.department, entry.semester, entry.day_index, entry.slot_index)].append(entry.group_id)
		issues: List[ValidationIssue] = []
		for key, groups in bucket.items():
			unique_groups = set(groups)
			if len(unique_groups) <= 1:
				continue
			dept, semester, day_index, slot_index = key
			issues.append(
				ValidationIssue(
					category="group_overlap",
					severity=ValidationSeverity.ERROR,
					message=(
						f"Multiple groups from {dept} S{semester} share theory slot {slot_index} on day {day_index}"
					),
					context={
						"department": dept,
						"semester": semester,
						"day_index": day_index,
						"slot_index": slot_index,
						"group_ids": sorted(unique_groups),
					},
				)
			)
		return issues

	def _check_theory_lab_conflicts(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
		theory_index: MutableMapping[Tuple[str, int, int, int], List[TheoryScheduleEntry]] = defaultdict(list)
		for entry in schedule.theory_entries:
			theory_index[(entry.department, entry.semester, entry.day_index, entry.slot_index)].append(entry)
		issues: List[ValidationIssue] = []
		for lab_entry in schedule.lab_entries:
			theory_slots = self._time.lab_session_to_theory.get(lab_entry.session_name, ())
			for slot_index in theory_slots:
				key = (lab_entry.department, lab_entry.semester, lab_entry.day_index, slot_index)
				conflicts = theory_index.get(key)
				if not conflicts:
					continue
				issues.append(
					ValidationIssue(
						category="theory_lab_conflict",
						severity=ValidationSeverity.ERROR,
						message=(
							f"Lab session {lab_entry.session_name} for {lab_entry.department} S{lab_entry.semester} "
							f"overlaps with theory slot {slot_index}"
						),
						context={
							"lab_course_instance_id": lab_entry.course_instance_id,
							"lab_session": lab_entry.session_name,
							"day_index": lab_entry.day_index,
							"slot_index": slot_index,
							"conflicting_groups": [conflict.group_id for conflict in conflicts],
						},
					),
				)
		return issues

	def _check_lab_session_coverage(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
		counts = Counter(entry.course_instance_id for entry in schedule.lab_entries)
		issues: List[ValidationIssue] = []
		for requirement in self._lab_requirements.values():
			scheduled = counts.get(requirement.course_instance_id, 0)
			if scheduled == requirement.required_sessions:
				continue
			severity = (
				ValidationSeverity.ERROR
				if scheduled < requirement.required_sessions
				else ValidationSeverity.WARNING
			)
			issues.append(
				ValidationIssue(
					category="lab_coverage",
					severity=severity,
					message=(
						f"Course {requirement.course_code} expected {requirement.required_sessions} lab sessions "
						f"but found {scheduled}"
					),
					context={
						"course_instance_id": requirement.course_instance_id,
						"required_sessions": requirement.required_sessions,
						"scheduled_sessions": scheduled,
					},
				),
			)
		return issues

	def _check_theory_slot_coverage(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
		if self._theory_course_requirements:
			counts = Counter(
				entry.course_instance_id
				for entry in schedule.theory_entries
				if entry.course_instance_id
			)
			issues: List[ValidationIssue] = []
			for requirement in self._theory_course_requirements.values():
				required = max(0, requirement.required_slots)
				scheduled = counts.get(requirement.course_instance_id, 0)
				if scheduled == required:
					continue
				severity = (
					ValidationSeverity.ERROR
					if scheduled < required
					else ValidationSeverity.WARNING
				)
				issues.append(
					ValidationIssue(
						category="theory_coverage",
						severity=severity,
						message=(
							f"Course {requirement.course_code} ({requirement.course_instance_id}) expected {required} theory slots "
							f"but found {scheduled}"
						),
						context={
							"course_instance_id": requirement.course_instance_id,
							"group_id": requirement.group_id,
							"department": requirement.department,
							"semester": requirement.semester,
							"required_slots": required,
							"scheduled_slots": scheduled,
						},
					),
				)
			return issues

		counts = Counter(entry.group_id for entry in schedule.theory_entries)
		issues: List[ValidationIssue] = []
		for requirement in self._theory_requirements.values():
			scheduled = counts.get(requirement.group_id, 0)
			if scheduled == requirement.required_theory_slots:
				continue
			severity = (
				ValidationSeverity.ERROR
				if scheduled < requirement.required_theory_slots
				else ValidationSeverity.WARNING
			)
			issues.append(
				ValidationIssue(
					category="theory_coverage",
					severity=severity,
					message=(
						f"Group {requirement.group_id} expected {requirement.required_theory_slots} theory slots "
						f"but found {scheduled}"
					),
					context={
						"group_id": requirement.group_id,
						"department": requirement.department,
						"semester": requirement.semester,
						"required_slots": requirement.required_theory_slots,
						"scheduled_slots": scheduled,
					},
				),
			)
		return issues

	def _check_instance_presence(self, schedule: ScheduleExtractionResult) -> List[ValidationIssue]:
		lab_counts = Counter(entry.course_instance_id for entry in schedule.lab_entries)
		theory_counts = Counter(
			entry.course_instance_id
			for entry in schedule.theory_entries
			if entry.course_instance_id
		)
		group_counts = Counter(entry.group_id for entry in schedule.theory_entries)
		issues: List[ValidationIssue] = []
		for instance in self._instance_lookup.values():
			if instance.has_lab and instance.practical_hours > 0:
				scheduled = lab_counts.get(instance.instance_id, 0)
				if scheduled == 0:
					issues.append(
						ValidationIssue(
							category="ltp_presence",
							severity=ValidationSeverity.ERROR,
							message=f"Lab hours missing for {instance.course_code} ({instance.instance_id})",
							context={
								"course_instance_id": instance.instance_id,
								"department": instance.student_dept,
								"semester": instance.semester,
							},
						),
					)
			group_id = self._instance_group_lookup.get(instance.instance_id)
			if instance.has_theory and (instance.lecture_hours + instance.tutorial_hours) > 0:
				required = instance.lecture_hours + instance.tutorial_hours
				scheduled = theory_counts.get(instance.instance_id)
				if scheduled is None and group_id:
					scheduled = group_counts.get(group_id, 0)
				if scheduled is None:
					scheduled = 0
				if scheduled == 0:
					issues.append(
						ValidationIssue(
							category="ltp_presence",
							severity=ValidationSeverity.WARNING,
							message=(
								f"Theory slots missing for {instance.course_code}"
							),
							context={
								"course_instance_id": instance.instance_id,
								"group_id": group_id,
								"expected_hours": required,
							},
						),
					)
		return issues

	@staticmethod
	def _build_instance_lookup(data: ExtendedDataContainer) -> Mapping[str, NormalizedCourseInstance]:
		lookup: Dict[str, NormalizedCourseInstance] = {}
		for instances in data.preprocessing.normalized_instances.values():
			for instance in instances:
				lookup[instance.instance_id] = instance
		return lookup


__all__ = [
	"ScheduleValidator",
	"ValidationReport",
	"ValidationIssue",
	"ValidationSeverity",
]
