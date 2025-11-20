"""Helper utilities shared by constraint implementations."""

from __future__ import annotations

from typing import Iterator, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..data.schemas import LabSessionDetail
from .context import ConstraintContext


LabSessionVarTuple = Tuple[str, str, int, str, str, cp_model.IntVar]
GroupSlotVarTuple = Tuple[str, int, int, cp_model.IntVar]


def iter_lab_session_variables(
	context: ConstraintContext,
	*,
	teacher_id: Optional[str] = None,
	course_instance_id: Optional[str] = None,
) -> Iterator[LabSessionVarTuple]:
	"""Yield lab assignment variables for optional teacher/course filters."""

	lab_block = context.variables.lab
	teachers = (teacher_id,) if teacher_id else tuple(lab_block.assignments.keys())
	for tid in teachers:
		teacher_assignments = lab_block.assignments.get(tid)
		if not teacher_assignments:
			continue
		course_ids = (course_instance_id,) if course_instance_id else tuple(teacher_assignments.keys())
		for cid in course_ids:
			day_map = teacher_assignments.get(cid)
			if not day_map:
				continue
			for day_index, session_map in day_map.items():
				for session_name, room_map in session_map.items():
					for room_id, var in room_map.items():
						yield tid, cid, day_index, session_name, room_id, var


def iter_group_timeslot_variables(
	context: ConstraintContext,
	*,
	group_id: Optional[str] = None,
) -> Iterator[GroupSlotVarTuple]:
	"""Yield theory group/slot variables with optional filtering."""

	theory_block = context.variables.theory
	group_ids = (group_id,) if group_id else tuple(theory_block.group_timeslots.keys())
	for gid in group_ids:
		day_map = theory_block.group_timeslots.get(gid)
		if not day_map:
			continue
		for day_index, slot_map in day_map.items():
			for slot_index, var in slot_map.items():
				yield gid, day_index, slot_index, var


def get_lab_session_detail(context: ConstraintContext, session_name: str) -> LabSessionDetail:
	"""Return the configured :class:`LabSessionDetail` for a label."""

	sessions = context.data.raw.time.lab_sessions
	try:
		return sessions[session_name]
	except KeyError as exc:  # pragma: no cover - defensive guard
		raise KeyError(f"Unknown lab session '{session_name}'") from exc


def get_room_attributes(
	context: ConstraintContext,
	room_id: str,
	*,
	default: Optional[Mapping[str, object]] = None,
) -> Optional[Mapping[str, object]]:
	"""Lookup room metadata from the preprocessing registry."""

	registry = getattr(context.data.raw, "room_registry", None) or {}
	return registry.get(str(room_id), default)


def resolve_day_pattern(context: ConstraintContext, department: str) -> Tuple[str, ...]:
	"""Resolve the day pattern for the provided department with fallbacks."""

	departments = context.data.raw.departments
	patterns: Mapping[str, Tuple[str, ...]] = getattr(departments, "day_patterns", {})
	pattern = patterns.get(department) or patterns.get("__default__")
	if pattern:
		return tuple(pattern)
	return tuple(context.data.raw.time.working_days)


def ensure_extra_bucket(context: ConstraintContext, bucket: str) -> MutableMapping[str, object]:
	"""Return a mutable mapping stored under ``context.extra[bucket]``."""

	if bucket not in context.extra:
		context.extra[bucket] = {}
	return context.extra[bucket]  # type: ignore[return-value]


def register_objective_penalty(
	context: ConstraintContext,
	variable: cp_model.IntVar,
	weight: int = 1,
	*,
	tag: Optional[str] = None,
) -> None:
	"""Register a weighted penalty term to be minimised in the global objective."""

	if weight == 0:
		return
	objective_bucket = ensure_extra_bucket(context, "objective")
	penalties = objective_bucket.setdefault("penalties", [])  # type: ignore[assignment]
	penalties.append((int(weight), variable, tag or ""))


def build_presence_literal(
	model: cp_model.CpModel,
	variables: Sequence[cp_model.IntVar],
	name: str,
) -> Optional[cp_model.IntVar]:
	"""Return a boolean literal that is true when any variable in ``variables`` is active."""

	bucket = tuple(var for var in variables if var is not None)
	if not bucket:
		return None
	if len(bucket) == 1:
		return bucket[0]
	literal = model.NewBoolVar(name)
	model.Add(sum(bucket) >= 1).OnlyEnforceIf(literal)
	model.Add(sum(bucket) == 0).OnlyEnforceIf(literal.Not())
	return literal


def parse_department_token(token: str) -> Tuple[str, Optional[int]]:
	"""Split ``Department_S5`` style tokens into (department, semester)."""

	if not token:
		return "", None
	value = str(token).strip()
	if "_S" in value:
		dept, _, suffix = value.partition("_S")
		try:
			return dept.strip(), int(suffix)
		except ValueError:
			return dept.strip(), None
	return value, None


__all__ = [
	"iter_lab_session_variables",
	"iter_group_timeslot_variables",
	"get_lab_session_detail",
	"get_room_attributes",
	"resolve_day_pattern",
	"ensure_extra_bucket",
	"build_presence_literal",
	"parse_department_token",
	"register_objective_penalty",
]
