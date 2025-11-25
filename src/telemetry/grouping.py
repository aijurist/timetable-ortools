"""Telemetry builder for group-level scheduling statistics."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ..constraints.schema import ConstraintApplicationResult
from ..runtime.extractor_schema import InstanceAssignment, ScheduleExtractionResult


@dataclass
class GroupTelemetryBuilder:
	"""Aggregate department/semester grouping metrics into a JSON payload."""

	constraint_results: Sequence[ConstraintApplicationResult]
	timestamp: Optional[datetime] = None

	def build(self, schedule: ScheduleExtractionResult) -> Mapping[str, Any]:
		group_records = _collect_group_records(schedule.instance_index.values())
		departments = _build_department_entries(group_records.values())
		summary = _summarize_groups(group_records, departments)

		return {
			"generated_at": (self.timestamp or datetime.now(timezone.utc)).isoformat(),
			"summary": summary,
			"departments": departments,
			"constraints": _serialize_constraints(
				self.constraint_results,
				{
					"group_non_overlap": "Department Group Non-Overlap",
				},
			),
		}

	def write(self, schedule: ScheduleExtractionResult, destination: Path) -> Path:
		payload = self.build(schedule)
		destination.parent.mkdir(parents=True, exist_ok=True)
		destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
		return destination


def _collect_group_records(assignments: Iterable[InstanceAssignment]) -> Mapping[str, MutableMapping[str, Any]]:
	records: Dict[str, MutableMapping[str, Any]] = {}
	for assignment in assignments:
		group_id = assignment.group_id
		if not group_id:
			continue
		record = records.setdefault(
			group_id,
			{
				"group_id": group_id,
				"department": assignment.department,
				"semester": assignment.semester,
				"course_instances": set(),
				"course_codes": set(),
				"teachers": set(),
				"lab_sessions": set(),
				"theory_slots": set(),
				"lab_entries": 0,
				"theory_entries": 0,
			},
		)
		record["course_instances"].add(assignment.course_instance_id)

		for lab_entry in assignment.lab_entries:
			record["lab_entries"] += 1
			record["teachers"].add(lab_entry.teacher_name or lab_entry.teacher_id)
			record["course_codes"].add(lab_entry.course_code)
			record["lab_sessions"].add(_format_lab_label(lab_entry.day, lab_entry.session_name, lab_entry.session_time))
			if not record.get("department"):
				record["department"] = lab_entry.department
			if record.get("semester") is None:
				record["semester"] = lab_entry.semester

		for theory_entry in assignment.theory_entries:
			record["theory_entries"] += 1
			record["teachers"].update(theory_entry.teacher_names or tuple())
			record["course_codes"].update(theory_entry.course_codes or tuple())
			if theory_entry.course_code:
				record["course_codes"].add(theory_entry.course_code)
			record["theory_slots"].add(_format_theory_label(theory_entry.day, theory_entry.slot_label))
			if not record.get("department"):
				record["department"] = theory_entry.department
			if record.get("semester") is None:
				record["semester"] = theory_entry.semester

	return records


def _build_department_entries(records: Iterable[Mapping[str, Any]]) -> Tuple[Mapping[str, Any], ...]:
	bucket: MutableMapping[Tuple[str, Optional[int]], list[Mapping[str, Any]]] = defaultdict(list)
	for record in records:
		department = str(record.get("department") or "Unassigned")
		semester = record.get("semester")
		bucket[(department, semester)].append(record)

	payload: list[Mapping[str, Any]] = []
	for (department, semester), entries in sorted(bucket.items(), key=lambda item: (item[0][0], item[0][1] or 0)):
		groups = []
		lab_sessions_total = 0
		theory_slots_total = 0
		for entry in sorted(entries, key=lambda e: e.get("group_id")):
			lab_sessions = sorted(entry["lab_sessions"])
			theory_slots = sorted(entry["theory_slots"])
			groups.append(
				{
					"group_id": entry["group_id"],
					"course_instances": sorted(entry["course_instances"]),
					"course_codes": sorted(code for code in entry["course_codes"] if code),
					"teachers": sorted(name for name in entry["teachers"] if name),
					"lab_sessions": lab_sessions,
					"theory_slots": theory_slots,
					"lab_session_count": len(lab_sessions),
					"theory_slot_count": len(theory_slots),
					"lab_entry_count": entry["lab_entries"],
					"theory_entry_count": entry["theory_entries"],
				},
			)
			lab_sessions_total += len(lab_sessions)
			theory_slots_total += len(theory_slots)

		payload.append(
			{
				"department": department,
				"semester": semester,
				"group_count": len(entries),
				"lab_sessions": lab_sessions_total,
				"theory_slots": theory_slots_total,
				"groups": groups,
			},
		)
	return tuple(payload)


def _summarize_groups(
	records: Mapping[str, Mapping[str, Any]],
	departments: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
	groups_without_lab = sum(1 for record in records.values() if record["lab_entries"] == 0)
	groups_without_theory = sum(1 for record in records.values() if record["theory_entries"] == 0)
	department_count = len(departments)
	return {
		"total_groups": len(records),
		"departments": department_count,
		"groups_without_lab_sessions": groups_without_lab,
		"groups_without_theory_slots": groups_without_theory,
	}


def _serialize_constraints(
	results: Sequence[ConstraintApplicationResult],
	targets: Mapping[str, str],
) -> Mapping[str, Mapping[str, Any]]:
	payload: Dict[str, Mapping[str, Any]] = {}
	for key, name in targets.items():
		result = _find_constraint(results, name)
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


def _format_lab_label(day: Optional[str], session: Optional[str], time_range: Optional[str]) -> str:
	parts = [
		(day or "Unspecified").strip().title(),
		(session or "Session").strip(),
	]
	if time_range:
		parts.append(time_range.strip())
	return " · ".join(parts)


def _format_theory_label(day: Optional[str], slot_label: Optional[str]) -> str:
	return f"{(day or 'Unspecified').strip().title()} · {(slot_label or 'Slot').strip()}"


def _normalize(value: Any) -> Any:
	if isinstance(value, Mapping):
		return {key: _normalize(val) for key, val in value.items()}
	if isinstance(value, (list, tuple, set)):
		return [_normalize(item) for item in value]
	return value


__all__ = ["GroupTelemetryBuilder"]
