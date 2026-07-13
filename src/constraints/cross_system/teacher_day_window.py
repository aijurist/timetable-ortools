"""Teacher working-day window constraint.

Cross-department teachers (e.g., MA* courses) can otherwise end up scheduled on
both Monday and Saturday when departments use different 5-day patterns.

This constraint forces each teacher to choose exactly one continuous 5-day
window: Mon–Fri OR Tue–Sat.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping, Optional, Sequence

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..fixed_schedule_context import get_fixed_schedule_occupancy
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_course_timeslot_variables, iter_lab_session_variables, iter_theory_room_variables
from ...utils.normalization import normalize_teacher_id
from ...utils.course_rules import ignores_teacher_constraints
from ...utils.time_utils import DayNormalizer


@dataclass
class TeacherDayWindowStats:
	teachers_seen: int = 0
	teachers_constrained: int = 0
	teachers_forced_mon_fri: int = 0
	teachers_forced_tue_sat: int = 0
	forced_window_skipped: int = 0
	blocked_monday_vars: int = 0
	blocked_saturday_vars: int = 0
	forced_window_source: Optional[str] = None

	def to_details(self) -> Mapping[str, object]:
		return {
			"teachers_seen": self.teachers_seen,
			"teachers_constrained": self.teachers_constrained,
			"teachers_forced_mon_fri": self.teachers_forced_mon_fri,
			"teachers_forced_tue_sat": self.teachers_forced_tue_sat,
			"forced_window_skipped": self.forced_window_skipped,
			"blocked_monday_vars": self.blocked_monday_vars,
			"blocked_saturday_vars": self.blocked_saturday_vars,
			"forced_window_source": self.forced_window_source,
		}


class TeacherDayWindowConstraint(Constraint):
	"""Ensure each teacher uses exactly one 5-day window (Mon–Fri or Tue–Sat)."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("teacher_day_window")
		stats = TeacherDayWindowStats()
		forced_windows = dict(self._load_forced_windows(context, stats))
		fixed_occupancy = get_fixed_schedule_occupancy(context)
		for teacher_id, days in fixed_occupancy.teacher_days.items():
			forced_windows.setdefault(teacher_id, self._window_from_days(days))

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
			for _tid, course_id, _day_idx, _session, _room, _var in iter_lab_session_variables(
				context, teacher_id=teacher_id
			):
				if ignores_teacher_constraints(context.variables.lab.requirements.get(course_id)):
					continue
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

			forced = forced_windows.get(normalize_teacher_id(teacher_id))
			if forced == "mon_fri":
				context.model.Add(use_mf == 1)
				stats.teachers_forced_mon_fri += 1
			elif forced == "tue_sat":
				context.model.Add(use_ts == 1)
				stats.teachers_forced_tue_sat += 1
			elif forced is not None:
				stats.forced_window_skipped += 1

			# Labs
			for _tid, course_id, day_idx, _session_name, _room_id, var in iter_lab_session_variables(
				context,
				teacher_id=teacher_id,
			):
				if ignores_teacher_constraints(context.variables.lab.requirements.get(course_id)):
					continue
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
	def _normalize_day_label(value: object) -> str:
		label = str(value or "").strip()
		normalized = DayNormalizer.normalize_day_name(label)
		return normalized or label.lower()

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

	def _load_forced_windows(
		self,
		context: ConstraintContext,
		stats: TeacherDayWindowStats,
	) -> Mapping[str, str]:
		params = self.params or {}
		lab_csv = str(params.get("window_lab_csv_path") or "").strip()
		theory_csv = str(params.get("window_theory_csv_path") or "").strip()
		snapshot_path = (
			str(params.get("window_snapshot_path") or "").strip()
			or str(params.get("window_schedule_path") or "").strip()
			or str(params.get("window_schedule_json_path") or "").strip()
		)

		teacher_days: MutableMapping[str, set[str]] = {}

		if lab_csv or theory_csv:
			stats.forced_window_source = "csv"
			self._load_from_csv(context, lab_csv, theory_csv, teacher_days)
		elif snapshot_path:
			stats.forced_window_source = "json"
			self._load_from_json(context, snapshot_path, teacher_days)
		else:
			return {}

		forced: dict[str, str] = {}
		for teacher_id, days in teacher_days.items():
			has_mon = "monday" in days
			has_sat = "saturday" in days
			if has_mon and not has_sat:
				forced[teacher_id] = "mon_fri"
			elif has_sat and not has_mon:
				forced[teacher_id] = "tue_sat"
			else:
				forced[teacher_id] = "ambiguous"
		return forced

	@staticmethod
	def _window_from_days(days: Sequence[str]) -> str:
		day_set = {DayNormalizer.normalize_day_name(day) or str(day).strip().lower() for day in days}
		has_mon = "monday" in day_set
		has_sat = "saturday" in day_set
		if has_mon and not has_sat:
			return "mon_fri"
		if has_sat and not has_mon:
			return "tue_sat"
		return "ambiguous"

	def _load_from_csv(
		self,
		context: ConstraintContext,
		lab_path_text: str,
		theory_path_text: str,
		teacher_days: MutableMapping[str, set[str]],
	) -> None:
		for path_text in (lab_path_text, theory_path_text):
			if not path_text:
				continue
			path = self._resolve_path(Path(path_text))
			if not path.exists():
				continue
			with path.open("r", encoding="utf-8") as handle:
				reader = csv.DictReader(handle)
				for row in reader:
					teacher_id = str(row.get("teacher_id") or "").strip()
					day_label = self._normalize_day_label(row.get("day"))
					if not teacher_id or not day_label:
						continue
					teacher_days.setdefault(normalize_teacher_id(teacher_id), set()).add(day_label)

	def _load_from_json(
		self,
		context: ConstraintContext,
		snapshot_path_text: str,
		teacher_days: MutableMapping[str, set[str]],
	) -> None:
		path = self._resolve_path(Path(snapshot_path_text))
		if not path.exists():
			return
		try:
			payload = json.loads(path.read_text(encoding="utf-8"))
		except json.JSONDecodeError:
			return

		if "lab_entries" in payload or "theory_entries" in payload:
			for entry in payload.get("lab_entries") or ():
				self._collect_day_from_record(context, entry, True, teacher_days)
			for entry in payload.get("theory_entries") or ():
				self._collect_day_from_record(context, entry, False, teacher_days)
			return

		if "lab_assignments" in payload or "theory_assignments" in payload:
			for entry in payload.get("lab_assignments") or ():
				self._collect_day_from_record(context, entry, True, teacher_days)
			for entry in payload.get("theory_assignments") or ():
				self._collect_day_from_record(context, entry, False, teacher_days)
			return

	def _collect_day_from_record(
		self,
		context: ConstraintContext,
		record: Mapping[str, object],
		is_lab: bool,
		teacher_days: MutableMapping[str, set[str]],
	) -> None:
		teacher_id = str(record.get("teacher_id") or "").strip()
		course_id = str(record.get("course_instance_id") or "").strip()
		if not teacher_id:
			return
		day_label = self._normalize_day_label(record.get("day"))
		if not day_label:
			day_index = _safe_int(record.get("day_index"))
			if day_index is not None and course_id:
				if is_lab:
					patterns = context.variables.lab.day_patterns
				else:
					patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
				day_label = self._resolve_course_day_label(context, patterns, course_id, day_index)
		if not day_label:
			return
		teacher_days.setdefault(normalize_teacher_id(teacher_id), set()).add(day_label)

	@staticmethod
	def _resolve_path(candidate: Path) -> Path:
		if candidate.is_absolute():
			return candidate
		return (Path.cwd() / candidate).resolve()

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


def _safe_int(value: object) -> Optional[int]:
	if value is None:
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		try:
			return int(float(str(value)))
		except (TypeError, ValueError):
			return None
