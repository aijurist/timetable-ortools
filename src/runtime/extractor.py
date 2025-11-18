"""Schedule extraction utilities bridging solver output to viewer-friendly payloads."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

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
							)
							entries.append(entry)
		return tuple(entries)

	def _build_theory_entries(self, accessor: _SolutionAccessor) -> Tuple[TheoryScheduleEntry, ...]:
		entries: List[TheoryScheduleEntry] = []
		for group_id, day_map in self._theory_vars.group_timeslots.items():
			requirement = self._theory_vars.requirements.get(group_id)
			group = self._group_lookup.get(group_id)
			if not requirement or not group:
				continue
			day_pattern = self._theory_vars.day_patterns.get(group_id, self._time.working_days)
			teacher_names = tuple(self._teacher_lookup.get(tid, tid) for tid in group.teacher_ids)
			for day_index, slot_map in day_map.items():
				day_label = day_pattern[day_index % len(day_pattern)] if day_pattern else str(day_index)
				for slot_index, var in slot_map.items():
					if not accessor.bool_value(var):
						continue
					slot_label = self._time.theory_slots[slot_index] if slot_index < len(self._time.theory_slots) else f"slot_{slot_index}"
					is_lunch = self._is_lunch_slot(requirement.department, slot_index)
					five_policy, five_flag = self._theory_five_pm(requirement.department, requirement.semester, slot_index)
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
			instance_ids = self._group_course_map.get(entry.group_id, tuple())
			for instance_id in instance_ids:
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

	base_dir = Path.cwd()
	config_manager = ConfigManager(base_dir=base_dir)
	config = config_manager.load()
	data_loader = DataLoader(config, base_dir=base_dir)
	res = data_loader.load()

	pre = DataPreprocessor(config)
	output = pre.build_extended_container(data=res)
	
	
	builder = ModelBuilder(config=config)
	constraint_model = builder.build(data=output)
	runner = SolverRunner(config=config)
	final_res = runner.solve(constraint_model)
	extractor = ScheduleExtractor(data=output, constraint_model=constraint_model)
	schedule = extractor.export(final_res, output_dir=base_dir / "output" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S"), write_csv=True)