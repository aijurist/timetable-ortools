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
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

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
		self._course_slot_sequence_cache: Dict[str, Tuple[str, ...]] = {}
		self._theory_room_assignments = getattr(self._theory_vars, "room_assignments", {}) or {}

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
		session_pair_lookup = self._session_pair_lookup()
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
					existing_number = self._parse_batch_number(entry.batch_label or entry.batch_info)
					existing_label = entry.batch_label or entry.batch_info
					label = existing_label if existing_number == batch_number and existing_label else f"Batch {batch_number}"
					annotated[idx] = replace(
						entry,
						batch_number=batch_number,
						batch_label=label,
						batch_info=label,
						num_batches=final_batches,
						is_batched=True,
					)
			# Next, handle sequential batches (same course scheduled in different slots)
			ordered_keys = sorted(session_groups.keys(), key=lambda key: (key[1], key[0]))
			session_rank = {key: rank for rank, key in enumerate(ordered_keys)}

			def _remaining_sort_key(idx: int) -> Tuple[int, int, int, str, Tuple[int, ...]]:
				entry = annotated[idx]
				partner_session = session_pair_lookup.get(entry.session_name)
				has_partner = bool(
					partner_session
					and session_groups.get((entry.day_index, partner_session))
				)
				return (
					0 if has_partner else 1,
					session_rank[(entry.day_index, entry.session_name)],
					entry.day_index,
					entry.session_name,
					entry.session_slots,
				)

			remaining = sorted(
				(idx for idx in indices if not annotated[idx].batch_number),
				key=_remaining_sort_key,
			)
			target_sessions_per_batch = max(1, base_sessions, math.ceil(total_sessions / final_batches))
			batch_loads: Dict[int, int] = {batch_number: 0 for batch_number in range(1, final_batches + 1)}
			batch_day_loads: Dict[int, Dict[int, int]] = {
				batch_number: defaultdict(int) for batch_number in range(1, final_batches + 1)
			}
			for idx in indices:
				existing_number = annotated[idx].batch_number
				if existing_number and 1 <= existing_number <= final_batches:
					batch_loads[existing_number] += 1
					batch_day_loads[existing_number][annotated[idx].day_index] += 1
			assigned_indices: Set[int] = set()

			def _label_for_batch(batch_number: int, *candidates: Optional[str]) -> str:
				for candidate in candidates:
					if self._parse_batch_number(candidate) == batch_number:
						return str(candidate)
				return f"Batch {batch_number}"

			def _choose_batch_number(entry_count: int, day_index: int, *hints: Optional[int]) -> int:
				for hint in hints:
					if (
						hint
						and 1 <= hint <= final_batches
						and batch_loads[hint] + entry_count <= target_sessions_per_batch
						and batch_day_loads[hint].get(day_index, 0) == 0
					):
						return hint
				candidates = [
					batch_number
					for batch_number, load in batch_loads.items()
					if load + entry_count <= target_sessions_per_batch
					and batch_day_loads[batch_number].get(day_index, 0) == 0
				]
				if not candidates:
					candidates = [
						batch_number
						for batch_number in batch_loads
						if batch_day_loads[batch_number].get(day_index, 0) == 0
					]
				if not candidates:
					candidates = [
						batch_number
						for batch_number, load in batch_loads.items()
						if load + entry_count <= target_sessions_per_batch
					]
				if not candidates:
					candidates = list(batch_loads)
				return min(
					candidates,
					key=lambda batch_number: (
						batch_day_loads[batch_number].get(day_index, 0),
						batch_loads[batch_number],
						batch_number,
					),
				)

			def _assign_batch(target_idx: int, batch_number: int, label: str) -> None:
				current = annotated[target_idx]
				annotated[target_idx] = replace(
					current,
					batch_number=batch_number,
					batch_label=label,
					batch_info=label,
					num_batches=final_batches,
					is_batched=True,
				)

			for idx in remaining:
				if idx in assigned_indices or annotated[idx].batch_number:
					continue
				entry = annotated[idx]
				partner_idx = None
				partner_session = session_pair_lookup.get(entry.session_name)
				if partner_session:
					partner_candidates = session_groups.get((entry.day_index, partner_session), [])
					for candidate in partner_candidates:
						if candidate in assigned_indices or annotated[candidate].batch_number:
							continue
						partner_idx = candidate
						break
				if partner_idx is not None:
					primary_hint = self._parse_batch_number(entry.batch_label or entry.batch_info)
					partner_entry = annotated[partner_idx]
					partner_hint = self._parse_batch_number(partner_entry.batch_label or partner_entry.batch_info)
					batch_number = _choose_batch_number(2, entry.day_index, primary_hint, partner_hint)
					label = _label_for_batch(
						batch_number,
						entry.batch_label
						or entry.batch_info,
						partner_entry.batch_label
						or partner_entry.batch_info,
					)
					for target_idx in (idx, partner_idx):
						_assign_batch(target_idx, batch_number, label)
					batch_loads[batch_number] += 2
					batch_day_loads[batch_number][entry.day_index] += 2
					assigned_indices.update({idx, partner_idx})
					continue
				number_hint = self._parse_batch_number(entry.batch_label or entry.batch_info)
				batch_number = _choose_batch_number(1, entry.day_index, number_hint)
				label = _label_for_batch(batch_number, entry.batch_label or entry.batch_info)
				_assign_batch(idx, batch_number, label)
				batch_loads[batch_number] += 1
				batch_day_loads[batch_number][entry.day_index] += 1
				assigned_indices.add(idx)
		return annotated

	def _session_pair_lookup(self) -> Mapping[str, str]:
		cache = getattr(self, "_session_pair_cache", None)
		if cache is not None:
			return cache
		pairs: Dict[str, str] = {}
		session_items = list(self._time.lab_sessions.items())
		sorted_sessions = sorted(session_items, key=lambda item: min(item[1].slots) if item[1].slots else 0)
		for idx in range(0, len(sorted_sessions), 2):
			if idx + 1 >= len(sorted_sessions):
				break
			a_name, _ = sorted_sessions[idx]
			b_name, _ = sorted_sessions[idx + 1]
			pairs[a_name] = b_name
			pairs[b_name] = a_name
		self._session_pair_cache = pairs
		return pairs

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
		course_session_counts: Dict[str, int] = defaultdict(int)
		assignments = getattr(self._theory_vars, "assignments", {}) or {}
		course_requirements = getattr(self._theory_vars, "course_requirements", {}) or {}
		course_patterns = getattr(self._theory_vars, "course_day_patterns", {}) or {}
		group_requirements = getattr(self._theory_vars, "requirements", {}) or {}
		bundle_specs = getattr(self._theory_vars, "bundle_specs", {}) or {}
		for teacher_id, course_map in assignments.items():
			for assignment_course_id, day_map in course_map.items():
				requirement = course_requirements.get(assignment_course_id)
				if not requirement:
					continue
				course_instance_id = requirement.source_instance_id or assignment_course_id
				group_requirement = group_requirements.get(requirement.group_id)
				instance = self._instance_lookup.get(course_instance_id)
				group = self._group_lookup.get(requirement.group_id)
				bundle = bundle_specs.get(getattr(requirement, "bundle_id", None))
				partner_instance = (
					self._instance_lookup.get(requirement.partner_instance_id)
					if getattr(requirement, "partner_instance_id", None)
					else None
				)
				day_pattern = course_patterns.get(assignment_course_id, self._time.working_days)
				day_pattern_label = self._format_day_pattern(day_pattern)
				group_display = self._group_display.get(requirement.group_id, {})
				group_name = group_display.get("name") or self._format_group_name(group) or requirement.group_id
				group_index = group_display.get("index") or (group.ordinal if group else None)
				teacher_ids = (teacher_id,)
				teacher_names = tuple(self._teacher_lookup.get(tid, tid) for tid in teacher_ids)
				course_codes = (requirement.course_code,)
				bundle_instances = tuple(
					self._instance_lookup.get(instance_id)
					for instance_id in bundle.instance_ids
				) if bundle else tuple()
				bundle_instances = tuple(item for item in bundle_instances if item is not None)
				bundle_course_codes = tuple(item.course_code for item in bundle_instances)
				bundle_teacher_ids = tuple(item.teacher_id for item in bundle_instances)
				bundle_label = self._format_bundle_label(bundle_instances) if bundle and bundle.is_paired else None
				if bundle_label:
					group_name = bundle.bundle_group_id
					course_codes = bundle_course_codes
				course_row = self._get_course_row(instance)
				staff_code = self._coalesce_str(
					(course_row or {}).get("staff_code"),
					instance.metadata.get("staff_code") if instance and instance.metadata else None,
					teacher_id,
				)
				sorted_days = sorted(day_map.keys())
				for day_index in sorted_days:
					slot_map = day_map.get(day_index, {})
					day_label = day_pattern[day_index % len(day_pattern)] if day_pattern else str(day_index)
					for slot_index in sorted(slot_map.keys()):
						var = slot_map.get(slot_index)
						if var is None or not accessor.bool_value(var):
							continue
						course_session_counts[assignment_course_id] += 1
						component_session_number = course_session_counts[assignment_course_id]
						delivery_mode = getattr(requirement, "delivery_mode", "legacy_full_slot")
						session_number = (
							component_session_number
							if delivery_mode == "kutty_25x2"
							else getattr(requirement, "session_sequence_offset", 0) + component_session_number
						)
						session_type = (
							self._resolve_kutty_session_type(instance, component_session_number)
							if delivery_mode == "kutty_25x2"
							else self._resolve_course_session_type(course_instance_id, session_number)
						)
						slot_label = (
							self._time.theory_slots[slot_index]
							if slot_index < len(self._time.theory_slots)
							else f"slot_{slot_index}"
						)
						half_time = self._resolve_half_time(
							slot_label,
							getattr(requirement, "half_index", None),
							getattr(requirement, "half_minutes", 50),
						)
						is_lunch = self._is_lunch_slot(requirement.department, slot_index)
						five_policy, five_flag = self._theory_five_pm(
							requirement.department,
							requirement.semester,
							slot_index,
						)
						tags = set(requirement.tags)
						if group_requirement:
							tags.update(group_requirement.tags)
						student_count: Optional[int]
						if instance:
							student_count = instance.student_count
						elif group:
							student_count = group.summary.total_student_count
						else:
							student_count = None
						teacher_name = (
							instance.teacher_name
							if instance and instance.teacher_name
							else self._teacher_lookup.get(teacher_id, teacher_id)
						)
						room_assignment = self._resolve_theory_room_variable(
							teacher_id,
							assignment_course_id,
							day_index,
							slot_index,
							accessor,
						)
						capacity_info = None
						capacity_value = room_assignment.get("capacity")
						if capacity_value and student_count:
							capacity_info = f"{student_count}/{capacity_value}"
						entry = TheoryScheduleEntry(
							group_id=requirement.group_id,
							department=requirement.department,
							semester=requirement.semester,
							day=day_label,
							day_index=day_index,
							slot_index=slot_index,
							slot_label=slot_label,
							teacher_ids=teacher_ids,
							teacher_names=teacher_names,
							course_codes=course_codes,
							is_lunch_window=is_lunch,
							five_pm_policy=five_policy,
							five_pm_flag=five_flag,
							tags=tuple(sorted(tags)),
							course_instance_id=course_instance_id,
							course_code=instance.course_code if instance else requirement.course_code,
							course_name=instance.course_name if instance else requirement.course_code,
							session_type=session_type,
							session_number=session_number,
							teacher_id=teacher_id,
							teacher_name=teacher_name,
							staff_code=staff_code,
							room_id=room_assignment.get("room_id"),
							room_number=room_assignment.get("room_number"),
							block=room_assignment.get("block"),
							student_count=student_count,
							lecture_hours=instance.lecture_hours if instance else None,
							tutorial_hours=instance.tutorial_hours if instance else None,
							schedule_type="theory",
							group_name=group_name,
							group_index=group_index,
							day_pattern=day_pattern_label,
							is_co_scheduled=bool(bundle and bundle.is_paired and delivery_mode == "kutty_25x2"),
							capacity_info=capacity_info,
							partner_instance_id=getattr(requirement, "partner_instance_id", None),
							delivery_mode=delivery_mode,
							bundle_id=getattr(requirement, "bundle_id", None),
							bundle_group_id=getattr(requirement, "bundle_group_id", None),
							bundle_label=bundle_label,
							bundle_course_codes=bundle_course_codes,
							bundle_teacher_ids=bundle_teacher_ids,
							half_index=getattr(requirement, "half_index", None),
							half_minutes=getattr(requirement, "half_minutes", 50),
							half_time=half_time,
							partner_course_code=partner_instance.course_code if partner_instance else None,
							partner_teacher_id=partner_instance.teacher_id if partner_instance else None,
							partner_teacher_name=partner_instance.teacher_name if partner_instance else None,
							pairing_score=getattr(requirement, "pairing_score", 0),
							selection_mode=(
								"CHOOSE_BUNDLE"
								if bundle and bundle.is_paired
								else "CHOOSE_FACULTY"
							),
						)
						entries.append(entry)
		entries.sort(
			key=lambda entry: (
				entry.department,
				entry.semester,
				entry.group_id,
				entry.day_index,
				entry.slot_index,
				entry.course_instance_id or "",
			)
		)
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
			identifier = (
				f"{entry.bundle_id or entry.course_instance_id}_{entry.course_instance_id}_"
				f"{entry.day_index}_{entry.slot_index}_{entry.half_index or 0}"
				if entry.course_instance_id
				else f"{entry.group_id}_{entry.day_index}_{entry.slot_index}"
			)
			combined.append(
				CombinedScheduleEntry(
					entry_type="theory",
					department=entry.department,
					semester=entry.semester,
					group_id=entry.group_id,
					identifier=identifier,
					day=entry.day,
					label=entry.half_time or entry.slot_label,
					resource_id=entry.room_id or entry.block,
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
			course_id = entry.course_instance_id
			if not course_id:
				continue
			bucket = buffer.setdefault(
				course_id,
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

	def _get_course_session_sequence(self, course_instance_id: str) -> Tuple[str, ...]:
		if course_instance_id in self._course_slot_sequence_cache:
			return self._course_slot_sequence_cache[course_instance_id]
		instance = self._instance_lookup.get(course_instance_id)
		if not instance:
			self._course_slot_sequence_cache[course_instance_id] = ("Theory",)
			return self._course_slot_sequence_cache[course_instance_id]
		sequence: List[str] = []
		sequence.extend(["Lecture"] * max(instance.lecture_hours, 0))
		sequence.extend(["Tutorial"] * max(instance.tutorial_hours, 0))
		if not sequence:
			total = max(instance.total_hours(), 0)
			sequence = ["Theory"] * (total or 1)
		self._course_slot_sequence_cache[course_instance_id] = tuple(sequence)
		return self._course_slot_sequence_cache[course_instance_id]

	def _resolve_course_session_type(self, course_instance_id: str, session_number: int) -> str:
		sequence = self._get_course_session_sequence(course_instance_id)
		if not sequence:
			return "Theory"
		index = (max(session_number, 1) - 1) % len(sequence)
		return sequence[index]

	@staticmethod
	def _resolve_kutty_session_type(
		instance: Optional[NormalizedCourseInstance],
		session_number: int,
	) -> str:
		if instance is None:
			return "Theory Half"
		lecture_halves = max(0, instance.lecture_hours) * 2
		tutorial_halves = max(0, instance.tutorial_hours) * 2
		index = max(1, session_number)
		if index <= lecture_halves:
			return "Lecture Half"
		if index <= lecture_halves + tutorial_halves:
			return "Tutorial Half"
		return "Theory Half"

	def _format_bundle_label(
		self,
		instances: Sequence[NormalizedCourseInstance],
	) -> Optional[str]:
		if len(instances) != 2:
			return None
		parts = []
		for instance in instances:
			row = self._get_course_row(instance)
			staff = self._coalesce_str(row.get("staff_code"), instance.teacher_id) or instance.teacher_id
			parts.append(f"{instance.course_code} - {staff}")
		return " + ".join(parts)

	@staticmethod
	def _resolve_half_time(
		slot_label: str,
		half_index: Optional[int],
		half_minutes: int,
	) -> str:
		if half_index not in (1, 2) or half_minutes != 25:
			return slot_label
		match = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", slot_label)
		if not match:
			return f"{slot_label} ({'first' if half_index == 1 else 'second'} 25 min)"
		start = int(match.group(1)) * 60 + int(match.group(2))
		end = int(match.group(3)) * 60 + int(match.group(4))
		if end <= start:
			end += 12 * 60
		midpoint = start + 25
		left, right = (start, midpoint) if half_index == 1 else (midpoint, end)

		def _format(total: int) -> str:
			total %= 24 * 60
			return f"{total // 60}:{total % 60:02d}"

		return f"{_format(left)} - {_format(right)}"

	def _resolve_theory_room_variable(
		self,
		teacher_id: str,
		course_instance_id: Optional[str],
		day_index: int,
		slot_index: int,
		accessor: _SolutionAccessor,
	) -> Mapping[str, Any]:
		if not teacher_id or not course_instance_id:
			return {}
		teacher_bucket = self._theory_room_assignments.get(teacher_id)
		if not teacher_bucket:
			return {}
		course_bucket = teacher_bucket.get(course_instance_id)
		if not course_bucket:
			return {}
		day_bucket = course_bucket.get(day_index)
		if not day_bucket:
			return {}
		room_map = day_bucket.get(slot_index, {})
		for room_id, var in room_map.items():
			if accessor.bool_value(var):
				metadata = self._get_room_metadata(room_id)
				block = self._coalesce_str(metadata.get("block"), metadata.get("building"))
				room_number = self._coalesce_str(
					metadata.get("room_number"),
					metadata.get("room_no"),
					metadata.get("name"),
					room_id,
				)
				capacity = self._safe_int(
					metadata.get("room_max_cap")
					or metadata.get("capacity")
					or metadata.get("room_capacity")
					or metadata.get("max_capacity")
				)
				return {
					"room_id": str(room_id),
					"room_number": room_number,
					"block": block,
					"capacity": capacity,
				}
		return {}



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
