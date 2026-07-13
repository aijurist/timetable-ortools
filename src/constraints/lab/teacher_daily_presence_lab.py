"""Teacher daily presence constraints for lab sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model  # type: ignore[import]

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..fixed_schedule_context import get_fixed_schedule_occupancy, resolve_day_label
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal, iter_lab_session_variables
from ...utils.normalization import normalize_teacher_id
from ...utils.course_rules import ignores_teacher_constraints


TeacherDaySessionLiterals = Mapping[str, Mapping[str, Mapping[str, cp_model.IntVar]]]


@dataclass
class TeacherDailyPresenceStats:
	"""Diagnostics captured while enforcing teacher daily presence rules."""

	teachers_targeted: set[str] = field(default_factory=set)
	daily_cap_days: int = 0
	early_late_blocks: int = 0
	triple_window_blocks: int = 0
	constrained_days: int = 0

	def as_details(self) -> Mapping[str, object]:
		return {
			"targeted_teachers": len(self.teachers_targeted),
			"daily_cap_days": self.daily_cap_days,
			"early_late_blocks": self.early_late_blocks,
			"triple_window_blocks": self.triple_window_blocks,
			"constrained_days": self.constrained_days,
		}


class TeacherDailyPresenceLabConstraint(Constraint):
	"""Prevent excessively long lab days for teachers."""

	DEFAULT_MAX_DAILY_LABS = 2
	DEFAULT_EARLY_SESSIONS = ("L1",)
	DEFAULT_BUFFER_SESSIONS = ("L5",)
	DEFAULT_LATE_SESSIONS = ("L6",)
	CACHE_KEY = "teacher_daily_presence_lab"

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("teacher_daily_presence_lab")
		session_literals = self._collect_teacher_day_literals(context)
		if not session_literals:
			logger.info("No lab assignments available; skipping teacher daily presence constraint")
			return self._result(ConstraintStatus.SKIPPED, {})

		max_daily_labs = max(1, int(self.params.get("max_daily_sessions", self.DEFAULT_MAX_DAILY_LABS)))
		early_sessions = self._normalise_label_sequence(
			self.params.get("early_sessions"), self.DEFAULT_EARLY_SESSIONS
		)
		buffer_sessions = self._normalise_label_sequence(
			self.params.get("buffer_sessions"), self.DEFAULT_BUFFER_SESSIONS
		)
		late_sessions = self._normalise_label_sequence(
			self.params.get("late_sessions"), self.DEFAULT_LATE_SESSIONS
		)

		stats = TeacherDailyPresenceStats()
		model = context.model

		for teacher_id, day_map in session_literals.items():
			for day_label, session_map in day_map.items():
				if not session_map:
					continue

				stats.teachers_targeted.add(teacher_id)
				stats.constrained_days += 1

				# Hard limit on the number of lab sessions per day
				daily_sessions = tuple(session_map.values())
				model.Add(sum(daily_sessions) <= max_daily_labs)
				stats.daily_cap_days += 1

				early_literal = self._build_group_literal(
					model,
					session_map,
					early_sessions,
					f"teacher_{teacher_id}_{self._safe_name(day_label)}_early_lab",
				)
				late_literal = self._build_group_literal(
					model,
					session_map,
					late_sessions,
					f"teacher_{teacher_id}_{self._safe_name(day_label)}_late_lab",
				)
				buffer_literal = self._build_group_literal(
					model,
					session_map,
					buffer_sessions,
					f"teacher_{teacher_id}_{self._safe_name(day_label)}_buffer_lab",
				)

				if early_literal is not None and late_literal is not None:
					model.Add(early_literal + late_literal <= 1)
					stats.early_late_blocks += 1

				if (
					early_literal is not None
					and buffer_literal is not None
					and late_literal is not None
				):
					model.Add(late_literal == 0).OnlyEnforceIf([early_literal, buffer_literal])
					stats.triple_window_blocks += 1

		status = (
			ConstraintStatus.APPLIED
			if stats.daily_cap_days or stats.early_late_blocks or stats.triple_window_blocks
			else ConstraintStatus.SKIPPED
		)
		details = stats.as_details()
		details.update(
			{
				"max_daily_sessions": max_daily_labs,
				"early_sessions": tuple(early_sessions),
				"buffer_sessions": tuple(buffer_sessions),
				"late_sessions": tuple(late_sessions),
			}
		)
		return self._result(status, details)

	def _collect_teacher_day_literals(self, context: ConstraintContext) -> TeacherDaySessionLiterals:
		cache = context.extra.setdefault(self.CACHE_KEY, {})  # type: ignore[assignment]
		cached = cache.get("teacher_day_literals")
		if cached is not None:
			return cached  # type: ignore[return-value]

		terms: Dict[Tuple[str, str, str], list[cp_model.IntVar]] = {}
		for teacher_id, course_id, day_index, session_name, _, variable in iter_lab_session_variables(context):
			if ignores_teacher_constraints(context.variables.lab.requirements.get(course_id)):
				continue
			day_label = resolve_day_label(
				context,
				day_index_value=day_index,
				course_id=course_id,
				is_lab=True,
			)
			key = (normalize_teacher_id(teacher_id), day_label, session_name)
			terms.setdefault(key, []).append(variable)

		model = context.model
		fixed_occupancy = get_fixed_schedule_occupancy(context)
		current_teachers = {teacher_id for teacher_id, _day_label, _session_name in terms}
		for teacher_id, day_map in fixed_occupancy.lab_teacher_sessions.items():
			if teacher_id not in current_teachers:
				continue
			for day_label, sessions in day_map.items():
				for session_name in sessions:
					fixed_literal = model.NewBoolVar(
						f"fixed_teacher_lab_presence_{teacher_id}_{self._safe_name(day_label)}_{self._safe_name(session_name)}"
					)
					model.Add(fixed_literal == 1)
					terms.setdefault((teacher_id, day_label, session_name), []).append(fixed_literal)

		result: Dict[str, Dict[str, Dict[str, cp_model.IntVar]]] = {}
		for (teacher_id, day_label, session_name), variables in terms.items():
			literal = build_presence_literal(
				model,
				tuple(variables),
				f"teacher_{teacher_id}_{self._safe_name(day_label)}_{self._safe_name(session_name)}_presence",
			)
			if literal is None:
				continue
			day_bucket = result.setdefault(teacher_id, {})
			day_bucket.setdefault(day_label, {})[session_name] = literal

		cache["teacher_day_literals"] = result
		return result

	@staticmethod
	def _build_group_literal(
		model: cp_model.CpModel,
		session_map: Mapping[str, cp_model.IntVar],
		labels: Sequence[str],
		name: str,
	) -> Optional[cp_model.IntVar]:
		bucket = [session_map[label] for label in labels if label in session_map]
		if not bucket:
			return None
		if len(bucket) == 1:
			return bucket[0]
		return build_presence_literal(model, tuple(bucket), name)

	@staticmethod
	def _normalise_label_sequence(
		value: Optional[Sequence[str] | Sequence[object]],
		fallback: Sequence[str],
	) -> Tuple[str, ...]:
		if not value:
			return tuple(fallback)
		return tuple(str(label).strip() for label in value if str(label).strip()) or tuple(fallback)

	@staticmethod
	def _safe_name(value: object) -> str:
		return "".join(ch if ch.isalnum() else "_" for ch in str(value or "value")).strip("_") or "value"

	def _result(self, status: str, details: Mapping[str, object]) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=dict(details),
		)


def build_teacher_daily_presence_lab_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TeacherDailyPresenceLabConstraint:
	return TeacherDailyPresenceLabConstraint(metadata=metadata, params=params or {})


__all__ = [
	"TeacherDailyPresenceLabConstraint",
	"build_teacher_daily_presence_lab_constraint",
]
