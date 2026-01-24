"""Prevent teachers from being double-booked across lab and theory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal

ActivityMap = Mapping[str, Mapping[str, cp_model.IntVar]]


@dataclass(frozen=True)
class LabActivity:
	course_id: str
	course_code: str
	group_id: str
	practical_hours: int
	sessions: ActivityMap


@dataclass(frozen=True)
class TheoryActivity:
	course_id: str
	group_id: str
	slots: Mapping[str, Mapping[int, cp_model.IntVar]]


@dataclass(frozen=True)
class ActivityEntry:
	literal: cp_model.IntVar
	kind: str
	course_id: Optional[str] = None
	course_code: Optional[str] = None
	group_id: Optional[str] = None
	practical_hours: int = 0


class TeacherOverlapConstraint(Constraint):
	"""Ensure each teacher occupies at most one activity per time slot."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		theory_block = context.variables.theory
		theory_slot_count = len(theory_block.theory_slot_labels)
		if theory_slot_count == 0:
			return _skip(self.metadata, "no theory slots configured")

		teacher_lab = _build_teacher_lab_activity(context)
		teacher_theory = _build_teacher_theory_activity(context)
		teacher_ids = sorted(set(teacher_lab) | set(teacher_theory))
		if not teacher_ids:
			return _skip(self.metadata, "no teacher activity mappings found")

		slot_session_index = _build_theory_slot_session_index(context)
		working_days = tuple(getattr(context.data.raw.time, "working_days", tuple())) or ("monday",)

		clauses = 0
		activity_literals = 0
		teachers_with_activity = 0

		for teacher_id in teacher_ids:
			day_names = _collect_day_names(teacher_lab.get(teacher_id), teacher_theory.get(teacher_id))
			if not day_names:
				continue
			teachers_with_activity += 1
			ordered_days = _sort_day_names(day_names, working_days)

			for day_name in ordered_days:
				for slot_idx in range(theory_slot_count):
					entries = _collect_activity_entries(
						day_name,
						slot_idx,
						teacher_lab.get(teacher_id, tuple()),
						teacher_theory.get(teacher_id, tuple()),
						slot_session_index,
					)
					if len(entries) <= 1:
						continue

					dsa_labs = [e for e in entries if _is_dsa_override_activity(e)]
					others = [e for e in entries if not _is_dsa_override_activity(e)]

					if not others:
						continue

					if not dsa_labs:
						if _can_co_schedule(others):
							continue
						context.model.AddAtMostOne(e.literal for e in others)
						clauses += 1
						activity_literals += len(others)
						continue

					if len(others) > 1:
						if not _can_co_schedule(others):
							context.model.AddAtMostOne(e.literal for e in others)
							clauses += 1
							activity_literals += len(others)

					for dsa in dsa_labs:
						for other in others:
							context.model.AddImplication(dsa.literal, other.literal.Not())
							clauses += 1
							activity_literals += 2

		status = ConstraintStatus.APPLIED if clauses else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"teachers_considered": teachers_with_activity,
				"clauses_added": clauses,
				"activity_literals": activity_literals,
			},
		)


def _skip(metadata: ConstraintMetadata, reason: str) -> ConstraintApplicationResult:
	return ConstraintApplicationResult(
		name=metadata.name,
		domain=metadata.category,
		priority=metadata.priority,
		enabled=True,
		status=ConstraintStatus.SKIPPED,
		details={"reason": reason},
	)


def _build_teacher_lab_activity(context: ConstraintContext) -> Dict[str, Tuple[LabActivity, ...]]:
	lab_block = context.variables.lab
	assignments = lab_block.assignments
	teacher_courses = lab_block.teacher_courses
	day_patterns = lab_block.day_patterns
	requirements = lab_block.requirements
	model = context.model

	result: Dict[str, Tuple[LabActivity, ...]] = {}
	for teacher_id, course_ids in teacher_courses.items():
		teacher_assignments = assignments.get(teacher_id)
		if not teacher_assignments:
			continue
		entries = []
		for course_id in course_ids:
			day_map = teacher_assignments.get(course_id)
			if not day_map:
				continue
			requirement = requirements.get(course_id)
			if requirement is None:
				continue
			day_pattern = day_patterns.get(course_id, tuple())
			day_sessions: Dict[str, Dict[str, cp_model.IntVar]] = {}
			for day_idx, session_map in day_map.items():
				day_name = _safe_day_name(day_pattern, day_idx)
				session_literals: Dict[str, cp_model.IntVar] = {}
				for session_name, room_map in session_map.items():
					literal = build_presence_literal(
						model,
						tuple(room_map.values()),
						f"teacher_overlap_{teacher_id}_{course_id}_d{day_idx}_{session_name}",
					)
					if literal is not None:
						session_literals[session_name] = literal
				if session_literals:
					day_sessions[day_name] = session_literals
			if not day_sessions:
				continue
			entries.append(
				LabActivity(
					course_id=course_id,
					course_code=requirement.course_code,
					group_id=requirement.group_id,
					practical_hours=requirement.practical_hours,
					sessions=day_sessions,
				)
			)
		if entries:
			result[teacher_id] = tuple(entries)
	return result


def _build_teacher_theory_activity(context: ConstraintContext) -> Dict[str, Tuple[TheoryActivity, ...]]:
	theory_block = context.variables.theory
	assignments = getattr(theory_block, "assignments", {}) or {}
	course_requirements = getattr(theory_block, "course_requirements", {}) or {}
	course_patterns = getattr(theory_block, "course_day_patterns", {}) or {}
	result: Dict[str, Tuple[TheoryActivity, ...]] = {}
	for teacher_id, course_map in assignments.items():
		entries = []
		for course_id, day_map in course_map.items():
			requirement = course_requirements.get(course_id)
			if not requirement:
				continue
			pattern = course_patterns.get(course_id, tuple())
			day_slots: Dict[str, Dict[int, cp_model.IntVar]] = {}
			for day_idx, slot_map in day_map.items():
				if not slot_map:
					continue
				day_name = _safe_day_name(pattern, day_idx)
				day_slots[day_name] = dict(slot_map)
			if day_slots:
				entries.append(
					TheoryActivity(
						course_id=course_id,
						group_id=requirement.group_id,
						slots=day_slots,
					)
				)
		if entries:
			result[teacher_id] = tuple(entries)
	return result


def _build_theory_slot_session_index(context: ConstraintContext) -> Dict[int, Tuple[str, ...]]:
	time = context.data.raw.time
	mapping: MutableMapping[int, set[str]] = {}
	lab_session_to_theory = getattr(time, "lab_session_to_theory", {}) or {}
	for session_name, theory_slots in lab_session_to_theory.items():
		for slot_idx in theory_slots:
			try:
				index = int(slot_idx)
			except (TypeError, ValueError):  # pragma: no cover - defensive guard
				continue
			mapping.setdefault(index, set()).add(str(session_name))
	return {idx: tuple(sorted(session_names)) for idx, session_names in mapping.items()}


def _collect_day_names(
	lab_entries: Optional[Tuple[LabActivity, ...]],
	theory_entries: Optional[Tuple[TheoryActivity, ...]],
) -> set[str]:
	day_names: set[str] = set()
	if lab_entries:
		for entry in lab_entries:
			day_names.update(entry.sessions.keys())
	if theory_entries:
		for entry in theory_entries:
			day_names.update(entry.slots.keys())
	return day_names


def _sort_day_names(day_names: Iterable[str], working_days: Sequence[str]) -> Tuple[str, ...]:
	priority = {day: idx for idx, day in enumerate(working_days)}
	return tuple(sorted(day_names, key=lambda name: (priority.get(name, len(priority)), name)))


def _safe_day_name(pattern: Sequence[str], day_idx: int) -> str:
	if 0 <= day_idx < len(pattern):
		return pattern[day_idx]
	return f"day_{day_idx}"


def _collect_activity_entries(
	day_name: str,
	slot_idx: int,
	lab_entries: Tuple[LabActivity, ...],
	theory_entries: Tuple[TheoryActivity, ...],
	slot_session_index: Mapping[int, Tuple[str, ...]],
) -> Tuple[ActivityEntry, ...]:
	entries: list[ActivityEntry] = []
	for entry in theory_entries:
		slot_map = entry.slots.get(day_name)
		if slot_map:
			slot_literal = slot_map.get(slot_idx)
			if slot_literal is not None:
				entries.append(
					ActivityEntry(
						literal=slot_literal,
						kind="theory",
						course_id=entry.course_id,
						group_id=entry.group_id,
					)
				)

	lab_sessions = slot_session_index.get(slot_idx, tuple())
	if lab_sessions:
		for entry in lab_entries:
			session_map = entry.sessions.get(day_name)
			if not session_map:
				continue
			for session_name in lab_sessions:
				literal = session_map.get(session_name)
				if literal is not None:
					entries.append(
						ActivityEntry(
							literal=literal,
							kind="lab",
							course_id=entry.course_id,
							course_code=entry.course_code,
							group_id=entry.group_id,
							practical_hours=entry.practical_hours,
						),
					)
	return tuple(entries)


def _can_co_schedule(entries: Sequence[ActivityEntry]) -> bool:
	if len(entries) != 2:
		return False
	lab_entries = [entry for entry in entries if entry.kind == "lab"]
	if len(lab_entries) != 2:
		return False
	first, second = lab_entries
	if not first.group_id or not second.group_id:
		return False
	if first.group_id != second.group_id:
		return False
	if not first.course_code or not second.course_code:
		return False
	if first.course_code != second.course_code:
		return False
	# CRITICAL: Must be the SAME course instance (not just same code)
	# Otherwise different instances of the same course (e.g., for different batches)
	# would be incorrectly allowed to overlap
	if first.course_id != second.course_id:
		return False
	return first.practical_hours >= 4 and second.practical_hours >= 4


def _is_dsa_override_activity(entry: ActivityEntry) -> bool:
	if entry.kind != "lab":
		return False
	code = str(entry.course_code or "").strip().upper()
	return code in {"CS23231", "CB23231"}

def build_teacher_overlap_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TeacherOverlapConstraint:
	return TeacherOverlapConstraint(metadata=metadata, params=params)


__all__ = [
	"TeacherOverlapConstraint",
	"build_teacher_overlap_constraint",
]
