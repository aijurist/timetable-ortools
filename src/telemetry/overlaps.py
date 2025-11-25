"""Telemetry builder for overlap diagnostics across lab and theory schedules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ..constraints.schema import ConstraintApplicationResult
from ..data.schemas import TimeSystemArtifacts
from ..runtime.extractor_schema import LabScheduleEntry, ScheduleExtractionResult, TheoryScheduleEntry


@dataclass(frozen=True)
class _ActivitySnapshot:
	group_id: Optional[str]
	department: Optional[str]
	semester: Optional[int]
	teacher_id: Optional[str]
	teacher_name: Optional[str]
	course_code: Optional[str]
	kind: str  # "lab" or "theory"
	label: str
	origin: str  # e.g., course_instance_id or slot label


@dataclass
class OverlapTelemetryBuilder:
	"""Detect and report residual overlaps for groups and teachers."""

	constraint_results: Sequence[ConstraintApplicationResult]
	time_system: TimeSystemArtifacts
	timestamp: Optional[datetime] = None

	def build(self, schedule: ScheduleExtractionResult) -> Mapping[str, Any]:
		theory_slots = tuple(self.time_system.theory_slots)
		lab_to_theory = {str(name): tuple(indices) for name, indices in self.time_system.lab_session_to_theory.items()}

		group_buckets, teacher_buckets = _build_activity_buckets(
			schedule.theory_entries,
			schedule.lab_entries,
			lab_to_theory,
		)
		group_conflicts = _detect_group_conflicts(group_buckets, theory_slots)
		teacher_conflicts = _detect_teacher_conflicts(teacher_buckets, theory_slots)

		group_summary = {
			"dept_semesters": len(group_buckets),
			"conflict_windows": len(group_conflicts),
			"departments_impacted": len({(entry["department"], entry["semester"]) for entry in group_conflicts}),
		}
		teacher_summary = {
			"teachers_with_conflicts": len({entry["teacher_id"] for entry in teacher_conflicts}),
			"conflict_windows": len(teacher_conflicts),
		}

		return {
			"generated_at": (self.timestamp or datetime.now(timezone.utc)).isoformat(),
			"group_summary": group_summary,
			"group_conflicts": group_conflicts,
			"teacher_summary": teacher_summary,
			"teacher_conflicts": teacher_conflicts,
			"constraints": _serialize_constraints(
				self.constraint_results,
				{
					"group_non_overlap": "Department Group Non-Overlap",
					"teacher_overlap": "Teacher Overlap Guard",
				},
			),
		}

	def write(self, schedule: ScheduleExtractionResult, destination: Path) -> Path:
		payload = self.build(schedule)
		destination.parent.mkdir(parents=True, exist_ok=True)
		destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
		return destination


def _build_activity_buckets(
	theory_entries: Sequence[TheoryScheduleEntry],
	lab_entries: Sequence[LabScheduleEntry],
	lab_to_theory: Mapping[str, Sequence[int]],
) -> Tuple[
	Mapping[Tuple[str, Optional[int]], Dict[Tuple[str, int], list[_ActivitySnapshot]]],
	Mapping[str, Dict[Tuple[str, int], list[_ActivitySnapshot]]],
]:
	group_buckets: Dict[Tuple[str, Optional[int]], Dict[Tuple[str, int], list[_ActivitySnapshot]]] = {}
	teacher_buckets: Dict[str, Dict[Tuple[str, int], list[_ActivitySnapshot]]] = {}

	for entry in theory_entries:
		if entry.slot_index is None or entry.day is None:
			continue
		bucket_key = (str(entry.department or "Unassigned"), entry.semester)
		group_bucket = group_buckets.setdefault(bucket_key, {})
		day_key = _normalize_day(entry.day)
		snapshot = _ActivitySnapshot(
			group_id=entry.group_id,
			department=entry.department,
			semester=entry.semester,
			teacher_id=entry.teacher_id or (entry.teacher_ids[0] if entry.teacher_ids else None),
			teacher_name=entry.teacher_name or (entry.teacher_names[0] if entry.teacher_names else None),
			course_code=entry.course_code or (entry.course_codes[0] if entry.course_codes else None),
			kind="theory",
			label=entry.slot_label,
			origin=entry.course_instance_id or entry.group_id,
		)
		group_bucket.setdefault((day_key, entry.slot_index), []).append(snapshot)
		teacher_key = snapshot.teacher_id or snapshot.teacher_name
		if teacher_key:
			teacher_bucket = teacher_buckets.setdefault(str(teacher_key), {})
			teacher_bucket.setdefault((day_key, entry.slot_index), []).append(snapshot)

	for entry in lab_entries:
		if entry.session_name is None or entry.day is None:
			continue
		mapped_slots = lab_to_theory.get(str(entry.session_name)) or tuple()
		if not mapped_slots:
			continue
		bucket_key = (str(entry.department or "Unassigned"), entry.semester)
		group_bucket = group_buckets.setdefault(bucket_key, {})
		day_key = _normalize_day(entry.day)
		snapshot = _ActivitySnapshot(
			group_id=entry.group_id,
			department=entry.department,
			semester=entry.semester,
			teacher_id=entry.teacher_id,
			teacher_name=entry.teacher_name,
			course_code=entry.course_code,
			kind="lab",
			label=f"{entry.session_name} ({entry.session_time})",
			origin=entry.course_instance_id,
		)
		for slot_index in mapped_slots:
			group_bucket.setdefault((day_key, int(slot_index)), []).append(snapshot)
			teacher_key = snapshot.teacher_id or snapshot.teacher_name
			if teacher_key:
				teacher_bucket = teacher_buckets.setdefault(str(teacher_key), {})
				teacher_bucket.setdefault((day_key, int(slot_index)), []).append(snapshot)

	return group_buckets, teacher_buckets


def _detect_group_conflicts(
	group_buckets: Mapping[Tuple[str, Optional[int]], Dict[Tuple[str, int], list[_ActivitySnapshot]]],
	theory_slots: Sequence[str],
) -> Tuple[Mapping[str, Any], ...]:
	conflicts: list[Mapping[str, Any]] = []
	for (department, semester), day_map in group_buckets.items():
		for (day_key, slot_index), activities in day_map.items():
			group_ids = sorted({activity.group_id for activity in activities if activity.group_id})
			if len(group_ids) <= 1:
				continue
			conflicts.append(
				{
					"department": department,
					"semester": semester,
					"day": _format_day(day_key),
					"slot_index": slot_index,
					"slot_label": _slot_label(theory_slots, slot_index),
					"groups": group_ids,
					"activities": [_serialize_activity(activity) for activity in activities],
				},
			)
	return tuple(sorted(conflicts, key=lambda entry: (entry["department"], entry["semester"], entry["day"], entry["slot_index"])))


def _detect_teacher_conflicts(
	teacher_buckets: Mapping[str, Dict[Tuple[str, int], list[_ActivitySnapshot]]],
	theory_slots: Sequence[str],
) -> Tuple[Mapping[str, Any], ...]:
	conflicts: list[Mapping[str, Any]] = []
	for teacher_id, day_map in teacher_buckets.items():
		teacher_name = None
		for snapshots in day_map.values():
			for snapshot in snapshots:
				if snapshot.teacher_name:
					teacher_name = snapshot.teacher_name
					break
			if teacher_name:
				break
		for (day_key, slot_index), activities in day_map.items():
			if len(activities) <= 1:
				continue
			conflicts.append(
				{
					"teacher_id": teacher_id,
					"teacher_name": teacher_name or teacher_id,
					"day": _format_day(day_key),
					"slot_index": slot_index,
					"slot_label": _slot_label(theory_slots, slot_index),
					"activities": [_serialize_activity(activity) for activity in activities],
				},
			)
	return tuple(sorted(conflicts, key=lambda entry: (entry["teacher_id"], entry["day"], entry["slot_index"])))


def _serialize_activity(activity: _ActivitySnapshot) -> Mapping[str, Any]:
	return {
		"group_id": activity.group_id,
		"department": activity.department,
		"semester": activity.semester,
		"teacher_id": activity.teacher_id,
		"teacher_name": activity.teacher_name,
		"course_code": activity.course_code,
		"kind": activity.kind,
		"label": activity.label,
		"origin": activity.origin,
	}


def _serialize_constraints(
	results: Sequence[ConstraintApplicationResult],
	targets: Mapping[str, str],
) -> Mapping[str, Mapping[str, Any]]:
	payload: Dict[str, Mapping[str, Any]] = {}
	for key, title in targets.items():
		result = _find_constraint(results, title)
		if result is None:
			continue
		payload[key] = {
			"name": result.name,
			"status": result.status,
			"enabled": result.enabled,
			"priority": result.priority,
			"details": _normalize(result.details),
		}
	return payload


def _find_constraint(
	results: Sequence[ConstraintApplicationResult],
	title: str,
) -> Optional[ConstraintApplicationResult]:
	for result in results:
		if result.name.lower() == title.lower():
			return result
	return None


def _normalize_day(day: str) -> str:
	return day.strip().lower() if day else "unspecified"


def _format_day(day_key: str) -> str:
	return day_key.capitalize() if day_key else "Unspecified"


def _slot_label(labels: Sequence[str], index: int) -> str:
	if 0 <= index < len(labels):
		return labels[index]
	return f"Slot {index}"


def _normalize(value: Any) -> Any:
	if isinstance(value, Mapping):
		return {key: _normalize(val) for key, val in value.items()}
	if isinstance(value, (list, tuple, set)):
		return [_normalize(item) for item in value]
	return value


__all__ = ["OverlapTelemetryBuilder"]
