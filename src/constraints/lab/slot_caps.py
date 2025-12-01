"""Lab slot limit constraints for core, computing, and semester aggregates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model  # type: ignore[import]

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal, ensure_extra_bucket, register_objective_penalty


SlotKey = Tuple[int, str]
CourseSlotLiterals = Dict[str, Dict[int, Dict[str, cp_model.IntVar]]]
GroupSlotLiterals = Dict[str, Dict[SlotKey, cp_model.IntVar]]
GroupCourseMap = Mapping[str, Tuple[str, ...]]


@dataclass
class CoreGroupSlotStats:
	targeted_groups: int = 0
	penalty_variables: int = 0
	targeted_group_ids: list[str] = field(default_factory=list)

	def as_details(self) -> Mapping[str, object]:
		return {
			"targeted_groups": self.targeted_groups,
			"penalty_variables": self.penalty_variables,
			"core_groups": tuple(self.targeted_group_ids),
		}


@dataclass
class ComputingGroupSlotStats:
	constrained_groups: int = 0
	group_ids: list[str] = field(default_factory=list)

	def as_details(self) -> Mapping[str, object]:
		return {
			"constrained_groups": self.constrained_groups,
			"groups": tuple(self.group_ids),
		}


@dataclass
class SemesterSlotStats:
	constrained_semesters: int = 0
	semesters: list[str] = field(default_factory=list)

	def as_details(self) -> Mapping[str, object]:
		return {
			"constrained_semesters": self.constrained_semesters,
			"semesters": tuple(self.semesters),
		}


class CoreLabGroupSlotCapConstraint(Constraint):
	"""Softly cap unique lab slots for groups containing core lab instances."""

	DEFAULT_SLOT_LIMIT = 8
	DEFAULT_PENALTY_WEIGHT = 200

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("core_group_slot_cap")
		group_slots = _get_group_slot_literals(context)
		if not group_slots:
			logger.info("No group slot literals available; skipping core group slot cap")
			return _result(self.metadata, ConstraintStatus.SKIPPED, details={})

		group_courses = _get_group_course_map(context)
		core_course_ids = _get_core_course_ids(context)
		if not core_course_ids:
			logger.info("No core lab mappings resolved; skipping core group slot cap")
			return _result(self.metadata, ConstraintStatus.SKIPPED, details={})

		stats = CoreGroupSlotStats()
		limit = max(0, int(self.params.get("slot_limit", self.DEFAULT_SLOT_LIMIT)))
		penalty_weight = max(0, int(self.params.get("penalty_weight", self.DEFAULT_PENALTY_WEIGHT)))

		for group_id, slot_literals in group_slots.items():
			courses = group_courses.get(group_id, ())
			if not courses:
				continue
			core_courses = tuple(course_id for course_id in courses if course_id in core_course_ids)
			if not core_courses:
				continue
			if not slot_literals:
				continue

			stats.targeted_groups += 1
			stats.targeted_group_ids.append(group_id)

			total_slots = context.model.NewIntVar(0, len(slot_literals), f"{group_id}_core_slots")
			context.model.Add(total_slots == sum(slot_literals.values()))

			if penalty_weight <= 0:
				continue

			excess = context.model.NewIntVar(0, max(len(slot_literals) - limit, 0), f"{group_id}_core_slot_excess")
			context.model.AddMaxEquality(excess, [total_slots - limit, 0])
			register_objective_penalty(
				context,
				excess,
				penalty_weight,
				tag=f"lab_balance:core_group:{group_id}",
			)
			stats.penalty_variables += 1

		status = ConstraintStatus.APPLIED if stats.targeted_groups else ConstraintStatus.SKIPPED
		return _result(self.metadata, status, stats.as_details())


class ComputingGroupSlotCapConstraint(Constraint):
	"""Hard cap on lab slots for configured computing departments."""

	DEFAULT_SLOT_LIMIT = 6
	DEFAULT_DEPARTMENTS = (
		"Computer Science & Engineering",
		"Computer Science & Engineering (Cyber Security)",
		"Computer Science & Business Systems",
		"Computer Science & Design",
		"Information Technology",
		"Artificial Intelligence & Data Science",
		"Artificial Intelligence & Machine Learning",
	)

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("computing_group_slot_cap")
		group_slots = _get_group_slot_literals(context)
		if not group_slots:
			logger.info("No group slot literals available; skipping computing slot cap")
			return _result(self.metadata, ConstraintStatus.SKIPPED, details={})

		group_info = _get_group_info_map(context)

		departments = self.params.get("departments")
		if isinstance(departments, Sequence):
			dept_set = {str(value).strip().lower() for value in departments if value}
		else:
			dept_set = {dept.lower() for dept in self.DEFAULT_DEPARTMENTS}
		limit = max(0, int(self.params.get("slot_limit", self.DEFAULT_SLOT_LIMIT)))

		stats = ComputingGroupSlotStats()
		for group_id, slot_literals in group_slots.items():
			if not slot_literals:
				continue
			dept, _ = group_info.get(group_id, (None, None))
			if not dept or dept.strip().lower() not in dept_set:
				continue

			context.model.Add(sum(slot_literals.values()) <= limit)
			stats.constrained_groups += 1
			stats.group_ids.append(group_id)

		status = ConstraintStatus.APPLIED if stats.constrained_groups else ConstraintStatus.SKIPPED
		return _result(self.metadata, status, stats.as_details())


class SemesterLabSlotCapConstraint(Constraint):
	"""Hard cap on unique lab slots per (department, semester) for non-core labs."""

	DEFAULT_SLOT_LIMIT = 18

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("semester_slot_cap")
		course_slot_literals = _get_course_slot_literals(context)
		if not course_slot_literals:
			logger.info("No lab course slot literals available; skipping semester slot cap")
			return _result(self.metadata, ConstraintStatus.SKIPPED, details={})

		lab_requirements = context.variables.lab.requirements
		core_course_ids = _get_core_course_ids(context)
		limit = max(0, int(self.params.get("slot_limit", self.DEFAULT_SLOT_LIMIT)))

		semester_slots: Dict[Tuple[str, int], Dict[SlotKey, Sequence[cp_model.IntVar]]] = defaultdict(lambda: defaultdict(list))
		for course_id, day_map in course_slot_literals.items():
			if course_id in core_course_ids:
				continue
			requirement = lab_requirements.get(course_id)
			if not requirement:
				continue
			dept = requirement.department or ""
			semester = int(requirement.semester or 0)
			key = (dept, semester)
			for day_idx, session_map in day_map.items():
				for session_name, literal in session_map.items():
					semester_slots[key][(day_idx, session_name)].append(literal)

		stats = SemesterSlotStats()
		for (dept, semester), slot_map in semester_slots.items():
			if not slot_map:
				continue

			literal_map: Dict[SlotKey, cp_model.IntVar] = {}
			for (day_idx, session_name), literals in slot_map.items():
				literal = build_presence_literal(
					context.model,
					tuple(literals),
					f"semester_slot_{dept}_{semester}_d{day_idx}_{session_name}",
				)
				if literal is not None:
					literal_map[(day_idx, session_name)] = literal

			if not literal_map:
				continue

			context.model.Add(sum(literal_map.values()) <= limit)
			stats.constrained_semesters += 1
			stats.semesters.append(f"{dept} S{semester}")

		status = ConstraintStatus.APPLIED if stats.constrained_semesters else ConstraintStatus.SKIPPED
		return _result(self.metadata, status, stats.as_details())


# ---------------------------------------------------------------------------
# Helper utilities shared by the slot cap constraints
# ---------------------------------------------------------------------------

def _result(metadata: ConstraintMetadata, status: str, details: Mapping[str, object]) -> ConstraintApplicationResult:
	return ConstraintApplicationResult(
		name=metadata.name,
		domain=metadata.category,
		priority=metadata.priority,
		enabled=True,
		status=status,
		details=dict(details),
	)


def _get_slot_cache(context: ConstraintContext) -> MutableMapping[str, object]:
	return ensure_extra_bucket(context, "lab_slot_caps")


def _get_course_slot_literals(context: ConstraintContext) -> CourseSlotLiterals:
	cache = _get_slot_cache(context)
	literals = cache.get("course_slot_literals")
	if literals is not None:
		return literals  # type: ignore[return-value]

	model = context.model
	assignments = context.variables.lab.assignments
	course_literals: CourseSlotLiterals = {}

	for teacher_courses in assignments.values():
		for course_id, day_map in teacher_courses.items():
			course_entry = course_literals.setdefault(course_id, {})
			for day_idx, session_map in day_map.items():
				day_entry = course_entry.setdefault(day_idx, {})
				for session_name, room_map in session_map.items():
					literal = build_presence_literal(
						model,
						tuple(room_map.values()),
						f"course_slot_{course_id}_d{day_idx}_{session_name}",
					)
					if literal is not None:
						day_entry[session_name] = literal

	cache["course_slot_literals"] = course_literals
	return course_literals


def _get_group_course_map(context: ConstraintContext) -> GroupCourseMap:
	cache = _get_slot_cache(context)
	mapping = cache.get("group_courses")
	if mapping is not None:
		return mapping  # type: ignore[return-value]

	lookup = getattr(context.variables.lab, "instance_group_lookup", {}) or {}
	courses = context.variables.lab.requirements
	group_courses: Dict[str, Tuple[str, ...]] = {}

	temporary: Dict[str, list[str]] = defaultdict(list)
	for course_id in courses.keys():
		group_id = lookup.get(course_id)
		if group_id:
			temporary[group_id].append(course_id)

	for group_id, items in temporary.items():
		group_courses[group_id] = tuple(sorted(items))

	cache["group_courses"] = group_courses
	return group_courses


def _get_group_slot_literals(context: ConstraintContext) -> GroupSlotLiterals:
	cache = _get_slot_cache(context)
	literals = cache.get("group_slot_literals")
	if literals is not None:
		return literals  # type: ignore[return-value]

	course_literals = _get_course_slot_literals(context)
	group_courses = _get_group_course_map(context)
	model = context.model
	group_slot_literals: GroupSlotLiterals = {}

	for group_id, course_ids in group_courses.items():
		slot_terms: Dict[SlotKey, list[cp_model.IntVar]] = defaultdict(list)
		for course_id in course_ids:
			day_map = course_literals.get(course_id, {})
			for day_idx, session_map in day_map.items():
				for session_name, literal in session_map.items():
					slot_terms[(day_idx, session_name)].append(literal)

		literal_map: Dict[SlotKey, cp_model.IntVar] = {}
		for (day_idx, session_name), literals in slot_terms.items():
			literal = build_presence_literal(
				model,
				tuple(literals),
				f"group_slot_{group_id}_d{day_idx}_{session_name}",
			)
			if literal is not None:
				literal_map[(day_idx, session_name)] = literal

		if literal_map:
			group_slot_literals[group_id] = literal_map

	cache["group_slot_literals"] = group_slot_literals
	return group_slot_literals


def _get_group_info_map(context: ConstraintContext) -> Mapping[str, Tuple[Optional[str], Optional[int]]]:
	cache = _get_slot_cache(context)
	info = cache.get("group_info")
	if info is not None:
		return info  # type: ignore[return-value]

	result: Dict[str, Tuple[Optional[str], Optional[int]]] = {}
	preprocessing = getattr(context.data, "preprocessing", None)
	groups_source = getattr(preprocessing, "groups", None)
	if isinstance(groups_source, Mapping):
		for cohort_groups in groups_source.values():
			for group in cohort_groups:
				result[group.group_id] = (group.key.department, group.key.semester)

	if not result:
		lookup = getattr(context.variables.lab, "instance_group_lookup", {}) or {}
		for course_id, requirement in context.variables.lab.requirements.items():
			group_id = lookup.get(course_id)
			if group_id and group_id not in result:
				result[group_id] = (requirement.department, requirement.semester)

	cache["group_info"] = result
	return result


def _get_core_course_codes(context: ConstraintContext) -> frozenset[str]:
	cache = _get_slot_cache(context)
	codes = cache.get("core_course_codes")
	if codes is not None:
		return codes  # type: ignore[return-value]

	core_df = getattr(context.data.raw, "core_lab_mapping_df", None)
	if core_df is None or getattr(core_df, "empty", True):
		resolved = frozenset()
	else:
		resolved = frozenset(
			str(code).strip()
			for code in core_df.get("course_code", tuple())
			if isinstance(code, str) and code.strip()
		)

	cache["core_course_codes"] = resolved
	return resolved


def _get_core_course_ids(context: ConstraintContext) -> frozenset[str]:
	cache = _get_slot_cache(context)
	course_ids = cache.get("core_course_ids")
	if course_ids is not None:
		return course_ids  # type: ignore[return-value]

	codes = _get_core_course_codes(context)
	if not codes:
		resolved = frozenset()
	else:
		resolved = frozenset(
			course_id
			for course_id, requirement in context.variables.lab.requirements.items()
			if str(requirement.course_code).strip() in codes
		)

	cache["core_course_ids"] = resolved
	return resolved


# ---------------------------------------------------------------------------
# Constraint factories used by the registry
# ---------------------------------------------------------------------------

def build_core_lab_group_slot_cap_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> CoreLabGroupSlotCapConstraint:
	return CoreLabGroupSlotCapConstraint(metadata=metadata, params=params or {})


def build_computing_group_slot_cap_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> ComputingGroupSlotCapConstraint:
	return ComputingGroupSlotCapConstraint(metadata=metadata, params=params or {})


def build_semester_lab_slot_cap_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> SemesterLabSlotCapConstraint:
	return SemesterLabSlotCapConstraint(metadata=metadata, params=params or {})


__all__ = [
	"build_core_lab_group_slot_cap_constraint",
	"build_computing_group_slot_cap_constraint",
	"build_semester_lab_slot_cap_constraint",
	"CoreLabGroupSlotCapConstraint",
	"ComputingGroupSlotCapConstraint",
	"SemesterLabSlotCapConstraint",
]
