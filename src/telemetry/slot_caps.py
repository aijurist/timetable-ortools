"""Telemetry utilities for slot-cap constraint monitoring."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ..constraints.schema import ConstraintApplicationResult
from ..runtime.extractor_schema import InstanceAssignment, LabScheduleEntry, ScheduleExtractionResult

SlotKey = Tuple[Optional[str], Optional[str]]

DEFAULT_SETTINGS: Dict[str, Dict[str, Any]] = {
	"core_group_slot_cap": {"slot_limit": 8, "penalty_weight": 200},
	"computing_group_slot_cap": {"slot_limit": 6},
	"semester_slot_cap": {"slot_limit": 18},
}

CONSTRAINT_TITLE_BY_KEY = {
	"core_group_slot_cap": "Core Group Slot Cap",
	"computing_group_slot_cap": "Computing Group Slot Cap",
	"semester_slot_cap": "Semester Lab Slot Cap",
}


@dataclass
class SlotCapTelemetryBuilder:
	"""Aggregate constraint details and realised usage into dashboard telemetry."""

	constraint_results: Sequence[ConstraintApplicationResult]
	slot_cap_settings: Mapping[str, Mapping[str, Any]]
	timestamp: Optional[datetime] = None

	def build(self, schedule: ScheduleExtractionResult) -> Mapping[str, Any]:
		lab_entries = schedule.lab_entries if schedule else tuple()
		group_usage = _build_group_usage(lab_entries)
		semester_usage = _build_semester_usage(lab_entries)
		group_metadata = _collect_group_metadata(schedule.instance_index.values())

		core_payload = self._build_group_payload(
			"core_group_slot_cap",
			group_usage,
			group_metadata,
			self._core_groups_from_constraints(),
		)
		computing_payload = self._build_group_payload(
			"computing_group_slot_cap",
			group_usage,
			group_metadata,
			self._computing_groups_from_constraints(),
		)
		semester_payload = self._build_semester_payload(
			semester_usage,
			self._semester_tokens_from_constraints(),
		)

		summary = {
			"groups_monitored": len(core_payload) + len(computing_payload),
			"groups_over_limit": sum(1 for entry in (*core_payload, *computing_payload) if entry["breached"]),
			"semesters_over_limit": sum(1 for entry in semester_payload if entry["breached"]),
		}

		payload = {
			"generated_at": (self.timestamp or datetime.now(timezone.utc)).isoformat(),
			"limits": self._merged_settings(),
			"summary": summary,
			"core_groups": core_payload,
			"computing_groups": computing_payload,
			"semesters": semester_payload,
			"constraints": self._serialize_constraint_results(),
		}
		return payload

	def write(self, schedule: ScheduleExtractionResult, destination: Path) -> Path:
		payload = self.build(schedule)
		destination.parent.mkdir(parents=True, exist_ok=True)
		destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
		return destination

	def _merged_settings(self) -> Mapping[str, Mapping[str, Any]]:
		merged: Dict[str, Dict[str, Any]] = {}
		for key, defaults in DEFAULT_SETTINGS.items():
			config_override = self.slot_cap_settings.get(key) or {}
			merged[key] = {**defaults, **dict(config_override)}
		return merged

	def _build_group_payload(
		self,
		constraint_key: str,
		usage: Mapping[str, Mapping[str, Any]],
		metadata: Mapping[str, Mapping[str, Any]],
		group_ids: Sequence[str],
	) -> Tuple[Mapping[str, Any], ...]:
		if not group_ids:
			return tuple()
		settings = self._merged_settings().get(constraint_key, {})
		limit = _to_int(settings.get("slot_limit"))
		records: list[Mapping[str, Any]] = []
		for group_id in group_ids:
			info = usage.get(group_id)
			meta = metadata.get(group_id, {})
			unique_slots = info.get("slots") if info else set()
			slot_labels = _format_slots(unique_slots) if unique_slots else []
			slots_used = len(unique_slots)
			department = info.get("department") if info else meta.get("department")
			semester = info.get("semester") if info else meta.get("semester")
			breached = bool(limit is not None and slots_used > limit)
			records.append(
				{
					"group_id": group_id,
					"department": department,
					"semester": semester,
					"slots_used": slots_used,
					"slot_limit": limit,
					"breached": breached,
					"slots": slot_labels,
				}
			)
		records.sort(key=lambda entry: (entry["department"] or "", entry["semester"] or 0, entry["group_id"]))
		return tuple(records)

	def _build_semester_payload(
		self,
		usage: Mapping[Tuple[str, int], Mapping[str, Any]],
		semester_tokens: Sequence[Tuple[str, int]],
	) -> Tuple[Mapping[str, Any], ...]:
		if not semester_tokens:
			return tuple()
		settings = self._merged_settings().get("semester_slot_cap", {})
		limit = _to_int(settings.get("slot_limit"))
		records: list[Mapping[str, Any]] = []
		for dept, semester in semester_tokens:
			info = usage.get((dept, semester))
			unique_slots = info.get("slots") if info else set()
			slot_labels = _format_slots(unique_slots) if unique_slots else []
			slots_used = len(unique_slots)
			breached = bool(limit is not None and slots_used > limit)
			records.append(
				{
					"department": dept,
					"semester": semester,
					"slots_used": slots_used,
					"slot_limit": limit,
					"breached": breached,
					"slots": slot_labels,
				}
			)
		records.sort(key=lambda entry: (entry["department"], entry["semester"]))
		return tuple(records)

	def _core_groups_from_constraints(self) -> Tuple[str, ...]:
		result = self._find_constraint("core_group_slot_cap")
		if not result:
			return tuple()
		groups = result.details.get("core_groups") or result.details.get("targeted_group_ids")
		if isinstance(groups, (list, tuple)):
			return tuple(str(group) for group in groups)
		return tuple()

	def _computing_groups_from_constraints(self) -> Tuple[str, ...]:
		result = self._find_constraint("computing_group_slot_cap")
		if not result:
			return tuple()
		groups = result.details.get("groups") or result.details.get("group_ids")
		if isinstance(groups, (list, tuple)):
			return tuple(str(group) for group in groups)
		return tuple()

	def _semester_tokens_from_constraints(self) -> Tuple[Tuple[str, int], ...]:
		result = self._find_constraint("semester_slot_cap")
		if not result:
			return tuple()
		semesters = result.details.get("semesters")
		if not isinstance(semesters, (list, tuple)):
			return tuple()
		return tuple(_parse_semester_token(str(token)) for token in semesters)

	def _find_constraint(self, key: str) -> Optional[ConstraintApplicationResult]:
		title = CONSTRAINT_TITLE_BY_KEY.get(key, "").lower()
		for result in self.constraint_results:
			if result.name.lower() == title:
				return result
		return None

	def _serialize_constraint_results(self) -> Mapping[str, Mapping[str, Any]]:
		payload: Dict[str, Mapping[str, Any]] = {}
		for key, title in CONSTRAINT_TITLE_BY_KEY.items():
			result = next((res for res in self.constraint_results if res.name.lower() == title.lower()), None)
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


def _collect_group_metadata(assignments: Iterable[InstanceAssignment]) -> Mapping[str, Mapping[str, Any]]:
	metadata: Dict[str, Dict[str, Any]] = {}
	for assignment in assignments:
		group_id = assignment.group_id
		if not group_id or group_id in metadata:
			continue
		metadata[group_id] = {
			"department": assignment.department,
			"semester": assignment.semester,
		}
	return metadata


def _build_group_usage(entries: Sequence[LabScheduleEntry]) -> Mapping[str, Mapping[str, Any]]:
	usage: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"slots": set(), "department": None, "semester": None})
	for entry in entries:
		info = usage[entry.group_id]
		info["department"] = info.get("department") or entry.department
		info["semester"] = info.get("semester") or entry.semester
		info["slots"].add((entry.day, entry.session_name))
	return usage


def _build_semester_usage(entries: Sequence[LabScheduleEntry]) -> Mapping[Tuple[str, int], Mapping[str, Any]]:
	usage: Dict[Tuple[str, int], Dict[str, Any]] = defaultdict(lambda: {"slots": set()})
	for entry in entries:
		if _is_core_entry(entry):
			continue
		if not entry.department or entry.semester is None:
			continue
		key = (entry.department, entry.semester)
		usage[key]["slots"].add((entry.day, entry.session_name))
	return usage


def _is_core_entry(entry: LabScheduleEntry) -> bool:
	return any(str(tag).lower() == "core" for tag in (entry.tags or tuple()))


def _parse_semester_token(token: str) -> Tuple[str, int]:
	parts = token.split(" S", 1)
	if len(parts) != 2:
		return (token, 0)
	dept = parts[0].strip()
	try:
		semester = int(parts[1])
	except ValueError:
		semester = 0
	return (dept, semester)


def _format_slots(slots: Iterable[SlotKey]) -> Sequence[str]:
	labels = [f"{day or 'Unknown'} · {session or 'Session'}" for day, session in slots]
	labels.sort()
	return labels


def _normalize(value: Any) -> Any:
	if isinstance(value, Mapping):
		return {key: _normalize(val) for key, val in value.items()}
	if isinstance(value, (list, tuple, set)):
		return [_normalize(item) for item in value]
	return value


def _to_int(value: Any) -> Optional[int]:
	if value is None:
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


__all__ = ["SlotCapTelemetryBuilder"]
