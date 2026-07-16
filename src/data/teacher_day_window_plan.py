"""Deterministic global Mon-Fri/Tue-Sat teacher-window planning.

Department models are solved sequentially, so a free solver choice made inside
one department cannot be remembered by the next model.  This module computes
that choice once from every Semester-3 input file plus production locks and POP
availability.  The resulting map is then injected unchanged into every model.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from .pop_availability import normalize_day_label, normalize_teacher_id


MON_FRI = "mon_fri"
TUE_SAT = "tue_sat"


@dataclass(frozen=True)
class TeacherWindowAssignment:
	teacher_id: str
	day_pattern: Sequence[str]
	workload: int = 1
	department: str = ""


@dataclass(frozen=True)
class TeacherDayWindowPlan:
	forced_windows: Mapping[str, str]
	reasons: Mapping[str, str]
	mixed_pattern_teachers: tuple[str, ...]


def window_from_days(days: Iterable[object]) -> Optional[str]:
	"""Return the only boundary implied by *days*, or ``None`` if ambiguous."""

	normalized = {normalize_day_label(day) for day in days}
	has_monday = "monday" in normalized
	has_saturday = "saturday" in normalized
	if has_monday and not has_saturday:
		return MON_FRI
	if has_saturday and not has_monday:
		return TUE_SAT
	return None


def build_teacher_day_window_plan(
	assignments: Iterable[TeacherWindowAssignment],
	*,
	fixed_days: Mapping[str, Iterable[object]] | None = None,
	pop_days: Mapping[str, Iterable[object]] | None = None,
) -> TeacherDayWindowPlan:
	"""Choose one reproducible five-day window for every assigned teacher.

	Production locks have first priority because they are immutable.  A POP window
	that contains only one boundary day has second priority.  Otherwise the window
	containing the teacher's larger Semester-3 workload wins; ties deliberately use
	Mon-Fri so reruns do not depend on department solve order or a random seed.
	"""

	workloads: dict[str, dict[str, int]] = defaultdict(lambda: {MON_FRI: 0, TUE_SAT: 0})
	for assignment in assignments:
		teacher_id = normalize_teacher_id(assignment.teacher_id)
		window = window_from_days(assignment.day_pattern)
		if not teacher_id or window is None:
			continue
		try:
			weight = max(1, int(assignment.workload))
		except (TypeError, ValueError):
			weight = 1
		workloads[teacher_id][window] += weight

	normalized_fixed = _normalize_day_map(fixed_days or {})
	normalized_pop = _normalize_day_map(pop_days or {})
	forced_windows: dict[str, str] = {}
	reasons: dict[str, str] = {}
	mixed: list[str] = []

	for teacher_id in sorted(workloads, key=_teacher_sort_key):
		fixed = normalized_fixed.get(teacher_id, set())
		if "monday" in fixed and "saturday" in fixed:
			raise ValueError(
				f"Teacher {teacher_id} is present on both Monday and Saturday in production locks"
			)
		fixed_window = window_from_days(fixed)
		if fixed_window is not None:
			forced_windows[teacher_id] = fixed_window
			reasons[teacher_id] = "production_lock"
			continue

		pop_window = window_from_days(normalized_pop.get(teacher_id, set()))
		if pop_window is not None:
			forced_windows[teacher_id] = pop_window
			reasons[teacher_id] = "pop_boundary"
			continue

		mf_workload = workloads[teacher_id][MON_FRI]
		ts_workload = workloads[teacher_id][TUE_SAT]
		if mf_workload and ts_workload:
			mixed.append(teacher_id)
		if ts_workload > mf_workload:
			forced_windows[teacher_id] = TUE_SAT
		else:
			forced_windows[teacher_id] = MON_FRI
		reasons[teacher_id] = f"semester3_workload:{mf_workload}:{ts_workload}"

	return TeacherDayWindowPlan(
		forced_windows=forced_windows,
		reasons=reasons,
		mixed_pattern_teachers=tuple(mixed),
	)


def _normalize_day_map(
	day_map: Mapping[str, Iterable[object]],
) -> dict[str, set[str]]:
	normalized: dict[str, set[str]] = defaultdict(set)
	for raw_teacher_id, days in day_map.items():
		teacher_id = normalize_teacher_id(raw_teacher_id)
		if not teacher_id:
			continue
		for day in days:
			label = normalize_day_label(day)
			if label:
				normalized[teacher_id].add(label)
	return dict(normalized)


def _teacher_sort_key(teacher_id: str) -> tuple[int, object]:
	try:
		return 0, int(teacher_id)
	except ValueError:
		return 1, teacher_id


__all__ = [
	"MON_FRI",
	"TUE_SAT",
	"TeacherDayWindowPlan",
	"TeacherWindowAssignment",
	"build_teacher_day_window_plan",
	"window_from_days",
]
