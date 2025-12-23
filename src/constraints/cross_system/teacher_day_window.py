"""Teacher working-day window constraint.

Cross-department teachers (e.g., MA* courses) can otherwise end up scheduled on
both Monday and Saturday when departments use different 5-day patterns.

This constraint forces each teacher to choose exactly one continuous 5-day
window: Mon–Fri OR Tue–Sat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_course_timeslot_variables, iter_lab_session_variables, iter_theory_room_variables
from ...utils.time_utils import DayNormalizer


@dataclass
class TeacherDayWindowStats:
	teachers_seen: int = 0
	teachers_constrained: int = 0
	blocked_monday_vars: int = 0
	blocked_saturday_vars: int = 0

	def to_details(self) -> Mapping[str, object]:
		return {
			"teachers_seen": self.teachers_seen,
			"teachers_constrained": self.teachers_constrained,
			"blocked_monday_vars": self.blocked_monday_vars,
			"blocked_saturday_vars": self.blocked_saturday_vars,
		}


class TeacherDayWindowConstraint(Constraint):
	"""Ensure each teacher uses exactly one 5-day window (Mon–Fri or Tue–Sat)."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("teacher_day_window")
		stats = TeacherDayWindowStats()

		lab_teachers = tuple(context.variables.lab.assignments.keys())
		theory_teachers = tuple(getattr(context.variables.theory, "assignments", {}).keys())
		theory_room_teachers = tuple(getattr(context.variables.theory, "room_assignments", {}).keys())
		teacher_ids = sorted(set(lab_teachers).union(theory_teachers).union(theory_room_teachers))
		stats.teachers_seen = len(teacher_ids)

		if not teacher_ids:
			logger.info("No teacher assignments present; skipping teacher day window")
			return self._build_result(stats, ConstraintStatus.SKIPPED)

		for teacher_id in teacher_ids:
			# If a teacher has no variables at all, skip.
			has_any = False
			for _ in iter_lab_session_variables(context, teacher_id=teacher_id):
				has_any = True
				break
			if not has_any:
				for _ in iter_course_timeslot_variables(context, teacher_id=teacher_id):
					has_any = True
					break
			if not has_any:
				for _ in iter_theory_room_variables(context, teacher_id=teacher_id):
					has_any = True
					break
			if not has_any:
				continue

			use_mf = context.model.NewBoolVar(f"teacher_{teacher_id}_use_mon_fri")
			use_ts = context.model.NewBoolVar(f"teacher_{teacher_id}_use_tue_sat")
			context.model.Add(use_mf + use_ts == 1)
			stats.teachers_constrained += 1

			# Labs
			for _tid, course_id, day_idx, _session_name, _room_id, var in iter_lab_session_variables(
				context,
				teacher_id=teacher_id,
			):
				day_label = self._resolve_course_day_label(
					context,
					context.variables.lab.day_patterns,
					course_id,
					day_idx,
				)
				self._apply_day_restriction(context, var, day_label, use_mf, use_ts, stats)

			# Theory course-slot variables (preferred, if present)
			theory_course_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
			for _tid, course_id, day_idx, _slot_idx, var in iter_course_timeslot_variables(
				context,
				teacher_id=teacher_id,
			):
				day_label = self._resolve_course_day_label(context, theory_course_patterns, course_id, day_idx)
				self._apply_day_restriction(context, var, day_label, use_mf, use_ts, stats)

			# Theory room variables (fallback / extra safety)
			for _tid, course_id, day_idx, _slot_idx, _room_id, var in iter_theory_room_variables(
				context,
				teacher_id=teacher_id,
			):
				day_label = self._resolve_course_day_label(context, theory_course_patterns, course_id, day_idx)
				self._apply_day_restriction(context, var, day_label, use_mf, use_ts, stats)

		status = ConstraintStatus.APPLIED if stats.teachers_constrained else ConstraintStatus.SKIPPED
		logger.info(
			"Teacher day window constrained=%d teachers; blocked monday=%d saturday=%d",
			stats.teachers_constrained,
			stats.blocked_monday_vars,
			stats.blocked_saturday_vars,
		)
		return self._build_result(stats, status)

	@staticmethod
	def _apply_day_restriction(
		context: ConstraintContext,
		var,
		day_label: str,
		use_mf,
		use_ts,
		stats: TeacherDayWindowStats,
	) -> None:
		# If the teacher chooses Mon–Fri, forbid Saturday.
		# If the teacher chooses Tue–Sat, forbid Monday.
		if day_label == "monday":
			context.model.Add(var == 0).OnlyEnforceIf(use_ts)
			stats.blocked_monday_vars += 1
		elif day_label == "saturday":
			context.model.Add(var == 0).OnlyEnforceIf(use_mf)
			stats.blocked_saturday_vars += 1

	@staticmethod
	def _resolve_course_day_label(
		context: ConstraintContext,
		day_patterns: Mapping[str, Sequence[str]],
		course_id: str,
		day_index: int,
	) -> str:
		pattern = day_patterns.get(course_id)
		label: Optional[str] = None
		if pattern and 0 <= day_index < len(pattern):
			label = pattern[day_index]
		else:
			working_days = getattr(getattr(context.config, "time", None), "working_days", ())
			if 0 <= day_index < len(working_days):
				label = working_days[day_index]
		normalized = DayNormalizer.normalize_day_name(label or "")
		return normalized or f"day_{day_index}"

	def _build_result(self, stats: TeacherDayWindowStats, status: str) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=stats.to_details(),
		)


def build_teacher_day_window_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TeacherDayWindowConstraint:
	return TeacherDayWindowConstraint(metadata=metadata, params=params)


__all__ = [
	"TeacherDayWindowConstraint",
	"build_teacher_day_window_constraint",
]
