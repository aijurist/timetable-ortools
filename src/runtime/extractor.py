"""Schedule extraction utilities bridging solver output to viewer-friendly payloads."""

from __future__ import annotations

import csv
import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..data.schemas import (
	CourseGroup,
	ExtendedDataContainer,
	LabSessionDetail,
	NormalizedCourseInstance,
)
from ..models.model_builder import ConstraintModel
from ..models.schema import GroupTimeslotRequirement, LabCourseRequirement
from .solver_schema import SolverResult
from .extractor_schema import (
    CombinedScheduleEntry,
    InstanceAssignment,
    LabScheduleEntry,
    ScheduleExtractionResult,
    TheoryScheduleEntry,
	FivePmPolicy,
)

LOGGER = logging.getLogger(__name__)



class _FivePmPolicyIndex:
	def __init__(self, payload: Optional[Mapping[str, Mapping[str, object]]] = None) -> None:
		self._rules: Dict[Tuple[str, Optional[int]], FivePmPolicy] = {}
		if not payload:
			return
		for severity, section in payload.items():
			departments = section.get("departments", []) if isinstance(section, Mapping) else []
			for token in departments:
				dept, semester = self._split_token(str(token))
				self._rules[(dept, semester)] = FivePmPolicy(
					policy=severity,
					blocked_theory_slots=tuple(section.get("blocked_theory_slots", []) or []),
					blocked_lab_sessions=tuple(section.get("blocked_lab_sessions", []) or []),
					discouraged_theory_slots=tuple(section.get("discouraged_theory_slots", []) or []),
					discouraged_lab_sessions=tuple(section.get("discouraged_lab_sessions", []) or []),
				)

	@staticmethod
	def _split_token(token: str) -> Tuple[str, Optional[int]]:
		if "_S" in token:
			dept, _, suffix = token.partition("_S")
			try:
				return dept.strip(), int(suffix)
			except ValueError:
				return token.strip(), None
		return token.strip(), None

	def resolve(self, department: str, semester: Optional[int]) -> Optional[FivePmPolicy]:
		return self._rules.get((department, semester)) or self._rules.get((department, None))


class _SolutionAccessor:
	def __init__(self, model: cp_model.CpModel, response: cp_model.CpSolverResponse) -> None:
		proto = model.Proto()
		self._values: Dict[str, int] = {}
		values = list(response.solution)
		for index, variable in enumerate(proto.variables):
			name = variable.name or f"var_{index}"
			value = values[index] if index < len(values) else 0
			self._values[name] = value

	def value(self, var: cp_model.IntVar) -> int:
		return self._values.get(var.Name(), 0)

	def bool_value(self, var: cp_model.IntVar) -> bool:
		return bool(self.value(var))


class ScheduleExtractor:
	"""Translate solver assignments into lab/theory/combined schedule payloads."""

	def __init__(self, data: ExtendedDataContainer, constraint_model: ConstraintModel) -> None:
		self._data = data
		self._constraint_model = constraint_model
		self._lab_vars = constraint_model.variables.lab
		self._theory_vars = constraint_model.variables.theory
		self._time = data.raw.time
		self._lunch_windows = data.raw.departments.lunch_slot_windows
		self._day_patterns = data.raw.departments.day_patterns
		self._five_pm_index = _FivePmPolicyIndex(data.raw.departments.five_pm_constraints)
		self._instance_lookup = self._index_instances()
		self._group_lookup = self._index_groups()
		self._teacher_lookup = self._index_teachers()
		self._room_index = self._index_rooms()
		self._course_row_lookup = self._index_course_rows()
		self._group_display = self._build_group_display()
		self._group_slot_sequence_cache: Dict[str, Tuple[Tuple[Optional[str], str], ...]] = {}
		self._group_course_map = {
			group.group_id: tuple(group.course_instance_ids)
			for group in self._group_lookup.values()
		}

	def extract(self, solver_result: SolverResult) -> ScheduleExtractionResult:
		accessor = _SolutionAccessor(self._constraint_model.model, solver_result.response)
		lab_entries = self._build_lab_entries(accessor)
		theory_entries = self._build_theory_entries(accessor)
		combined = self._combine_entries(lab_entries, theory_entries)
		instance_index = self._build_instance_index(lab_entries, theory_entries)
		return ScheduleExtractionResult(
			lab_entries=lab_entries,
			theory_entries=theory_entries,
			combined_entries=combined,
			instance_index=instance_index,
		)

	def export(
		self,
		solver_result: SolverResult,
		*,
		output_dir: Optional[Path] = None,
		write_json: bool = True,
		write_csv: bool = False,
	) -> ScheduleExtractionResult:
		result = self.extract(solver_result)
		if output_dir:
			if write_json:
				result.write_json((output_dir / "schedule.json").resolve())
			if write_csv:
				result.write_csv_bundle((output_dir / "csv").resolve())
		return result

	def _build_lab_entries(self, accessor: _SolutionAccessor) -> Tuple[LabScheduleEntry, ...]:
		entries: List[LabScheduleEntry] = []
		lab_sessions = self._time.lab_sessions
		for teacher_id, course_map in self._lab_vars.assignments.items():
			for course_instance_id, day_map in course_map.items():
				requirement = self._lab_vars.requirements.get(course_instance_id)
				if not requirement:
					continue
				instance = self._instance_lookup.get(course_instance_id)
				teacher_name = (instance.teacher_name if instance else None) or self._teacher_lookup.get(teacher_id, teacher_id)
				course_code = requirement.course_code
				course_name = instance.course_name if instance else course_code
				day_pattern = self._lab_vars.day_patterns.get(course_instance_id, self._time.working_days)
				day_pattern_label = self._format_day_pattern(day_pattern)
				group_display = self._group_display.get(requirement.group_id, {})
				group = self._group_lookup.get(requirement.group_id)
				group_name = group_display.get("name") or self._format_group_name(group) or requirement.group_id
				group_index = group_display.get("index") or (group.ordinal if group else None)
				total_students = group_display.get("total_students") or (group.summary.total_student_count if group else requirement.student_count)
				course_row = self._get_course_row(instance)
				course_code_display = self._coalesce_str(
					(course_row or {}).get("course_code_display"),
					instance.metadata.get("course_code_display") if instance and instance.metadata else None,
					course_code,
				)
				staff_code = self._coalesce_str(
					(course_row or {}).get("staff_code"),
					instance.metadata.get("staff_code") if instance and instance.metadata else None,
					teacher_id,
				)
				batch_info = self._coalesce_str(
					(course_row or {}).get("batch_info"),
					(course_row or {}).get("batch_label"),
					(course_row or {}).get("batch_name"),
				)
				num_batches = self._safe_int((course_row or {}).get("num_batches")) or 1
				is_batched = bool(batch_info) or num_batches > 1
				co_schedule_id = self._coalesce_str(
					(course_row or {}).get("co_schedule_id"),
					(course_row or {}).get("virtual_id"),
					(course_row or {}).get("co_scheduled_id"),
				)
				co_schedule_group_size = self._safe_int((course_row or {}).get("co_schedule_group_size")) or 1
				co_schedule_partner_teachers = self._coalesce_str(
					(course_row or {}).get("co_schedule_partner_teachers"),
					(course_row or {}).get("partner_teachers"),
				)
				co_schedule_info = self._coalesce_str(
					(course_row or {}).get("co_schedule_info"),
					"Single session" if not co_schedule_id else f"Co-scheduled ({co_schedule_id})",
				)
				for day_index, session_map in day_map.items():
					day_label = day_pattern[day_index % len(day_pattern)] if day_pattern else str(day_index)
					for session_name, room_map in session_map.items():
						session_detail = lab_sessions.get(session_name)
						session_slots = session_detail.slots if isinstance(session_detail, LabSessionDetail) else tuple()
						session_time = session_detail.time_range if isinstance(session_detail, LabSessionDetail) else session_name
						for room_id, var in room_map.items():
							if not accessor.bool_value(var):
								continue
							is_lunch = self._lab_session_overlaps_lunch(requirement.department, session_name)
							five_policy, five_flag = self._lab_five_pm(requirement.department, requirement.semester, session_name)
							room_meta = self._get_room_metadata(room_id)
							room_number = self._coalesce_str(
								room_meta.get("room_number"),
								room_meta.get("room_no"),
								room_meta.get("name"),
							)
							block = self._coalesce_str(room_meta.get("block"), room_meta.get("building"))
							capacity = self._safe_int(
								room_meta.get("room_max_cap")
								or room_meta.get("capacity")
								or room_meta.get("room_capacity")
								or room_meta.get("max_capacity")
							)
							capacity_info = f"{requirement.student_count}/{capacity}" if capacity else None
							entry = LabScheduleEntry(
								teacher_id=teacher_id,
								teacher_name=teacher_name,
								course_instance_id=course_instance_id,
								course_code=course_code,
								course_name=course_name,
								group_id=requirement.group_id,
								department=requirement.department,
								semester=requirement.semester,
								day=day_label,
								day_index=day_index,
								session_name=session_name,
								session_slots=session_slots,
								session_time=session_time,
								room_id=room_id,
								student_count=requirement.student_count,
								tags=requirement.tags,
								is_lunch_window=is_lunch,
								five_pm_policy=five_policy,
								five_pm_flag=five_flag,
								course_code_display=course_code_display,
								practical_hours=requirement.practical_hours,
								staff_code=staff_code,
								room_number=room_number,
								block=block,
								capacity=capacity,
								total_students=total_students,
								is_batched=is_batched,
								batch_info=batch_info,
								num_batches=num_batches,
								schedule_type="lab",
								group_name=group_name,
								group_index=group_index,
								day_pattern=day_pattern_label,
								is_co_scheduled=bool(co_schedule_id),
								co_schedule_id=co_schedule_id,
								co_schedule_group_size=co_schedule_group_size,
								co_schedule_partner_teachers=co_schedule_partner_teachers,
								co_schedule_info=co_schedule_info,
								capacity_info=capacity_info,
							)
							entries.append(entry)
		return tuple(self._annotate_lab_batches(entries))

	def _annotate_lab_batches(self, entries: Sequence[LabScheduleEntry]) -> Sequence[LabScheduleEntry]:
		if not entries:
			return entries
		per_course: Dict[str, List[int]] = defaultdict(list)
		annotated = list(entries)
		for idx, entry in enumerate(entries):
			per_course[entry.course_instance_id].append(idx)
		for course_id, indices in per_course.items():
			if not indices:
				continue
			requirement = self._lab_vars.requirements.get(course_id)
			base_sessions = max(1, int(getattr(requirement, "required_sessions", 1) or 1)) if requirement else 1
			session_groups: Dict[Tuple[int, str], List[int]] = defaultdict(list)
			capacity_batches = 1
			for idx in indices:
				entry = annotated[idx]
				key = (entry.day_index, entry.session_name)
				session_groups[key].append(idx)
				if entry.capacity and entry.capacity > 0 and entry.student_count:
					capacity_batches = max(capacity_batches, math.ceil(entry.student_count / entry.capacity))
			total_sessions = len(indices)
			simultaneous_batches = max((len(group) for group in session_groups.values()), default=1)
			sequential_batches = math.ceil(total_sessions / base_sessions)
			final_batches = max(1, capacity_batches, simultaneous_batches, sequential_batches)
			if final_batches <= 1:
				continue
			# First, assign batch numbers for sessions that run simultaneously (multiple rooms)
			for group_indices in session_groups.values():
				if len(group_indices) <= 1:
					continue
				sorted_group = sorted(
					group_indices,
					key=lambda idx: (
						(annotated[idx].room_number or "").lower(),
						(annotated[idx].room_id or "").lower(),
					),
				)
				for batch_number, idx in enumerate(sorted_group, start=1):
					entry = annotated[idx]
					label = entry.batch_label or entry.batch_info or f"Batch {batch_number}"
					annotated[idx] = replace(
						entry,
						batch_number=batch_number,
						batch_label=label,
						batch_info=entry.batch_info or label,
						num_batches=final_batches,
						is_batched=True,
					)
			# Next, handle sequential batches (same course scheduled in different slots)
			ordered_keys = sorted(session_groups.keys(), key=lambda key: (key[1], key[0]))
			session_rank = {key: rank for rank, key in enumerate(ordered_keys)}
			remaining = sorted(
				(idx for idx in indices if not annotated[idx].batch_number),
				key=lambda idx: (
					session_rank[(annotated[idx].day_index, annotated[idx].session_name)],
					annotated[idx].day_index,
					annotated[idx].session_name,
					annotated[idx].session_slots,
				),
			)
			for offset, idx in enumerate(remaining):
				entry = annotated[idx]
				number_hint = self._parse_batch_number(entry.batch_label or entry.batch_info)
				batch_number = number_hint or ((offset % final_batches) + 1)
				label = entry.batch_label or entry.batch_info or f"Batch {batch_number}"
				annotated[idx] = replace(
					entry,
					batch_number=batch_number,
					batch_label=label,
					batch_info=entry.batch_info or label,
					num_batches=final_batches,
					is_batched=True,
				)
		return annotated

	@staticmethod
	def _parse_batch_number(label: Optional[str]) -> Optional[int]:
		if not label:
			return None
		match = re.search(r"(\d+)", label)
		if not match:
			return None
		try:
			return int(match.group(1))
		except ValueError:
			return None

	def _build_theory_entries(self, accessor: _SolutionAccessor) -> Tuple[TheoryScheduleEntry, ...]:
		entries: List[TheoryScheduleEntry] = []
		sequence_cache: Dict[str, Tuple[Tuple[Optional[str], str], ...]] = {
			group_id: self._get_group_slot_sequence(group_id)
			for group_id in self._theory_vars.group_timeslots.keys()
		}
		slot_positions: Dict[str, int] = defaultdict(int)
		course_session_counts: Dict[str, int] = defaultdict(int)
		for group_id, day_map in self._theory_vars.group_timeslots.items():
			requirement = self._theory_vars.requirements.get(group_id)
			group = self._group_lookup.get(group_id)
			if not requirement or not group:
				continue
			day_pattern = self._theory_vars.day_patterns.get(group_id, self._time.working_days)
			day_pattern_label = self._format_day_pattern(day_pattern)
			teacher_names = tuple(self._teacher_lookup.get(tid, tid) for tid in group.teacher_ids)
			sequence = sequence_cache.get(group_id, tuple())
			group_display = self._group_display.get(group_id, {})
			group_name = group_display.get("name") or self._format_group_name(group) or group_id
			group_index = group_display.get("index") or group.ordinal
			for day_index, slot_map in day_map.items():
				day_label = day_pattern[day_index % len(day_pattern)] if day_pattern else str(day_index)
				for slot_index, var in slot_map.items():
					if not accessor.bool_value(var):
						continue
					slot_label = self._time.theory_slots[slot_index] if slot_index < len(self._time.theory_slots) else f"slot_{slot_index}"
					is_lunch = self._is_lunch_slot(requirement.department, slot_index)
					five_policy, five_flag = self._theory_five_pm(requirement.department, requirement.semester, slot_index)
					course_instance_id: Optional[str] = None
					session_type = "Theory"
					if sequence:
						position = slot_positions[group_id]
						if position < len(sequence):
							course_instance_id, session_type = sequence[position]
						else:
							idx = position % len(sequence)
							course_instance_id, session_type = sequence[idx]
					slot_positions[group_id] += 1
					instance = self._instance_lookup.get(course_instance_id) if course_instance_id else None
					course_row = self._get_course_row(instance)
					teacher_id = instance.teacher_id if instance else (group.teacher_ids[0] if group.teacher_ids else None)
					teacher_name = instance.teacher_name if instance else (teacher_names[0] if teacher_names else teacher_id)
					staff_code = self._coalesce_str(
						(course_row or {}).get("staff_code"),
						instance.metadata.get("staff_code") if instance and instance.metadata else None,
						teacher_id,
					)
					if course_instance_id:
						course_session_counts[course_instance_id] += 1
						session_number = course_session_counts[course_instance_id]
					else:
						session_number = slot_positions[group_id]
					student_count = instance.student_count if instance else group.summary.total_student_count
					entry = TheoryScheduleEntry(
						group_id=group_id,
						department=requirement.department,
						semester=requirement.semester,
						day=day_label,
						day_index=day_index,
						slot_index=slot_index,
						slot_label=slot_label,
						teacher_ids=group.teacher_ids,
						teacher_names=teacher_names,
						course_codes=group.course_codes,
						is_lunch_window=is_lunch,
						five_pm_policy=five_policy,
						five_pm_flag=five_flag,
						tags=requirement.tags,
						course_instance_id=course_instance_id,
						course_code=instance.course_code if instance else None,
						course_name=instance.course_name if instance else None,
						session_type=session_type,
						session_number=session_number,
						teacher_id=teacher_id,
						teacher_name=teacher_name,
						staff_code=staff_code,
						room_id=None,
						room_number=None,
						block=None,
						student_count=student_count,
						lecture_hours=instance.lecture_hours if instance else None,
						tutorial_hours=instance.tutorial_hours if instance else None,
						schedule_type="theory",
						group_name=group_name,
						group_index=group_index,
						day_pattern=day_pattern_label,
						is_co_scheduled=False,
						capacity_info=None,
						partner_instance_id=None,
					)
					entries.append(entry)
		return tuple(entries)

	@staticmethod
	def _combine_entries(
		lab_entries: Sequence[LabScheduleEntry],
		theory_entries: Sequence[TheoryScheduleEntry],
	) -> Tuple[CombinedScheduleEntry, ...]:
		combined: List[CombinedScheduleEntry] = []
		for entry in lab_entries:
			combined.append(
				CombinedScheduleEntry(
					entry_type="lab",
					department=entry.department,
					semester=entry.semester,
					group_id=entry.group_id,
					identifier=entry.course_instance_id,
					day=entry.day,
					label=f"{entry.session_name} ({entry.session_time})",
					resource_id=entry.room_id,
					payload=entry.to_dict(),
				)
			)
		for entry in theory_entries:
			combined.append(
				CombinedScheduleEntry(
					entry_type="theory",
					department=entry.department,
					semester=entry.semester,
					group_id=entry.group_id,
					identifier=f"{entry.group_id}_{entry.day_index}_{entry.slot_index}",
					day=entry.day,
					label=entry.slot_label,
					resource_id=None,
					payload=entry.to_dict(),
				)
			)
		return tuple(combined)

	def _build_instance_index(
		self,
		lab_entries: Sequence[LabScheduleEntry],
		theory_entries: Sequence[TheoryScheduleEntry],
	) -> Mapping[str, InstanceAssignment]:
		buffer: Dict[str, Dict[str, object]] = {}
		for entry in lab_entries:
			bucket = buffer.setdefault(
				entry.course_instance_id,
				{"group_id": entry.group_id, "department": entry.department, "semester": entry.semester, "lab": [], "theory": []},
			)
			bucket["lab"].append(entry)
		for entry in theory_entries:
			target_ids: Sequence[str]
			if entry.course_instance_id:
				target_ids = (entry.course_instance_id,)
			else:
				target_ids = self._group_course_map.get(entry.group_id, tuple())
			for instance_id in target_ids:
				bucket = buffer.setdefault(
					instance_id,
					{
						"group_id": entry.group_id,
						"department": entry.department,
						"semester": entry.semester,
						"lab": [],
						"theory": [],
					},
				)
				bucket["theory"].append(entry)
		return {
			course_instance_id: InstanceAssignment(
				course_instance_id=course_instance_id,
				group_id=data["group_id"],
				department=data["department"],
				semester=data["semester"],
				lab_entries=tuple(data["lab"]),
				theory_entries=tuple(data["theory"]),
			)
			for course_instance_id, data in buffer.items()
		}

	def _lab_session_overlaps_lunch(self, department: str, session_name: str) -> bool:
		window = self._lunch_windows.get(department) or self._lunch_windows.get("__default__") or tuple()
		if not window:
			return False
		theory_slots = self._time.lab_session_to_theory.get(session_name, tuple())
		return any(slot in window for slot in theory_slots)

	def _lab_five_pm(self, department: str, semester: int, session_name: str) -> Tuple[Optional[str], bool]:
		policy = self._five_pm_index.resolve(department, semester)
		if not policy:
			return None, False
		blocked = policy.blocked_lab_sessions or ()
		discouraged = policy.discouraged_lab_sessions or ()
		if session_name in blocked:
			return policy.policy, True
		if policy.policy != "hard" and session_name in discouraged:
			return policy.policy, True
		return policy.policy, False

	def _is_lunch_slot(self, department: str, slot_index: int) -> bool:
		window = self._lunch_windows.get(department) or self._lunch_windows.get("__default__") or tuple()
		return slot_index in window

	def _theory_five_pm(self, department: str, semester: int, slot_index: int) -> Tuple[Optional[str], bool]:
		policy = self._five_pm_index.resolve(department, semester)
		if not policy:
			return None, False
		if slot_index in policy.blocked_theory_slots:
			return policy.policy, True
		if policy.policy != "hard" and slot_index in policy.discouraged_theory_slots:
			return policy.policy, True
		return policy.policy, False

	def _index_instances(self) -> Dict[str, NormalizedCourseInstance]:
		index: Dict[str, NormalizedCourseInstance] = {}
		for instances in self._data.preprocessing.normalized_instances.values():
			for instance in instances:
				index[instance.instance_id] = instance
		return index

	def _index_groups(self) -> Dict[str, CourseGroup]:
		index: Dict[str, CourseGroup] = {}
		for groups in self._data.preprocessing.groups.values():
			for group in groups:
				index[group.group_id] = group
		return index

	def _index_teachers(self) -> Dict[str, str]:
		lookup: Dict[str, str] = {}
		for instance in self._instance_lookup.values():
			if instance.teacher_id and instance.teacher_name:
				lookup.setdefault(instance.teacher_id, instance.teacher_name)
		return lookup

	def _index_rooms(self) -> Dict[str, Mapping[str, Any]]:
		registry = getattr(self._data.raw, "room_registry", None) or {}
		return {str(room_id): payload or {} for room_id, payload in registry.items()}

	def _index_course_rows(self) -> Dict[int, Mapping[str, Any]]:
		courses_df = getattr(self._data.raw, "courses_df", None)
		if courses_df is None:
			return {}
		try:
			reset_df = courses_df.reset_index(drop=True)
		except Exception:  # pragma: no cover - defensive for non-DataFrame inputs
			reset_df = courses_df
		data = reset_df.to_dict("index") if hasattr(reset_df, "to_dict") else {}
		return {int(idx): row for idx, row in data.items()}

	def _build_group_display(self) -> Dict[str, Dict[str, Any]]:
		display: Dict[str, Dict[str, Any]] = {}
		for group_id, group in self._group_lookup.items():
			display[group_id] = {
				"name": self._format_group_name(group),
				"index": group.ordinal,
				"total_students": group.summary.total_student_count,
				"department": group.key.department,
				"semester": group.key.semester,
			}
		return display

	def _get_room_metadata(self, room_id: Optional[str]) -> Mapping[str, Any]:
		if room_id is None:
			return {}
		return self._room_index.get(str(room_id), {})

	def _get_course_row(self, instance: Optional[NormalizedCourseInstance]) -> Mapping[str, Any]:
		if not instance or not instance.metadata:
			return {}
		row_index = instance.metadata.get("raw_row")
		if row_index is None:
			return {}
		try:
			return self._course_row_lookup.get(int(row_index), {})
		except (TypeError, ValueError):  # pragma: no cover - defensive parsing
			return {}

	@staticmethod
	def _coalesce_str(*values: Any) -> Optional[str]:
		for value in values:
			if value is None:
				continue
			text = str(value).strip()
			if text:
				return text
		return None

	@staticmethod
	def _safe_int(value: Any) -> Optional[int]:
		if value is None:
			return None
		if isinstance(value, str) and not value.strip():
			return None
		try:
			return int(round(float(value)))
		except Exception:
			return None

	@staticmethod
	def _format_day_pattern(pattern: Sequence[str]) -> str:
		if not pattern:
			return ""
		normalized = [str(day).strip().title() for day in pattern if day]
		if not normalized:
			return ""
		if len(normalized) == 1:
			return normalized[0]
		return f"{normalized[0]}-{normalized[-1]}"

	@staticmethod
	def _format_group_name(group: Optional[CourseGroup]) -> Optional[str]:
		if not group:
			return None
		return f"{group.key.department}_S{group.key.semester}_G{group.ordinal}"

	def _get_group_slot_sequence(self, group_id: str) -> Tuple[Tuple[Optional[str], str], ...]:
		if group_id in self._group_slot_sequence_cache:
			return self._group_slot_sequence_cache[group_id]
		group = self._group_lookup.get(group_id)
		if not group:
			self._group_slot_sequence_cache[group_id] = tuple()
			return self._group_slot_sequence_cache[group_id]
		sequence: List[Tuple[Optional[str], str]] = []
		for instance_id in group.course_instance_ids:
			instance = self._instance_lookup.get(instance_id)
			if not instance:
				continue
			for _ in range(max(instance.lecture_hours, 0)):
				sequence.append((instance_id, "Lecture"))
			for _ in range(max(instance.tutorial_hours, 0)):
				sequence.append((instance_id, "Tutorial"))
		if not sequence:
			sequence = [(instance_id, "Theory") for instance_id in group.course_instance_ids]
		self._group_slot_sequence_cache[group_id] = tuple(sequence)
		return self._group_slot_sequence_cache[group_id]


__all__ = [
	"ScheduleExtractor",
	"ScheduleExtractionResult",
	"LabScheduleEntry",
	"TheoryScheduleEntry",
	"CombinedScheduleEntry",
	"InstanceAssignment",
]


if __name__ == "__main__":
	from datetime import datetime
	from ortools.sat.python import cp_model
	from ..config.manager import ConfigManager
	from ..data.data_loader import DataLoader
	from ..data.preprocessing import DataPreprocessor
	from ..models.model_builder import ModelBuilder
	from .solver import SolverRunner
	
	from pathlib import Path

	# logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

	base_dir = Path.cwd()
	config_manager = ConfigManager(base_dir=base_dir)
	config = config_manager.load(config_path=base_dir / "config" / "scheduler.yaml")
	print(config.constraints.lab)
	data_loader = DataLoader(config, base_dir=base_dir)
	res = data_loader.load()

	pre = DataPreprocessor(config)
	output = pre.build_extended_container(data=res)
	
	
	builder = ModelBuilder(config=config)
	constraint_model = builder.build(data=output)
	print(constraint_model.constraint_results)
	runner = SolverRunner(config=config)
	final_res = runner.solve(constraint_model)
	print(final_res)
	extractor = ScheduleExtractor(data=output, constraint_model=constraint_model)
	schedule = extractor.export(final_res, output_dir=base_dir / "output" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S"), write_csv=True)