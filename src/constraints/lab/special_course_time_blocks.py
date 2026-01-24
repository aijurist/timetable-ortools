"""Special-case time/day blocks for specific lab course codes.

This module is meant for small, explicit rules requested by stakeholders that
should be enforced as hard constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Set

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_lab_session_variables
from ...utils.time_utils import DayNormalizer


@dataclass
class SpecialCourseTimeBlockStats:
	checked_variables: int = 0
	blocked_by_day: int = 0
	blocked_by_time: int = 0
	missing_requirements: int = 0
	unknown_sessions: int = 0
	rules_applied: int = 0

	def to_details(self) -> Mapping[str, object]:
		return {
			"checked_variables": self.checked_variables,
			"blocked_by_day": self.blocked_by_day,
			"blocked_by_time": self.blocked_by_time,
			"missing_requirements": self.missing_requirements,
			"unknown_sessions": self.unknown_sessions,
			"rules_applied": self.rules_applied,
		}


@dataclass(frozen=True)
class SpecialCourseTimeBlockRule:
	course_codes: Set[str]
	blocked_days: Set[str]
	allowed_days: Optional[Set[str]]
	blocked_slot_indices: Set[int]

	def matches_course(self, course_code: str) -> bool:
		return course_code in self.course_codes

	def blocks_day(self, day_label: str) -> bool:
		if self.allowed_days is not None and day_label not in self.allowed_days:
			return True
		return bool(self.blocked_days) and day_label in self.blocked_days


class SpecialCourseTimeBlocksConstraint(Constraint):
	"""Block specific lab course codes from specific days/times."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("special_course_time_blocks")
		stats = SpecialCourseTimeBlockStats()

		params = self.params or {}
		rules = self._parse_rules(context, params)
		if not rules:
			logger.info("No rules configured; skipping special course time blocks")
			return self._build_result(stats, ConstraintStatus.SKIPPED)

		stats.rules_applied = len(rules)
		logger.info(
			"Special course time blocks configured rule_count=%d",
			len(rules),
		)

		lab_block = context.variables.lab
		requirements = lab_block.requirements

		lab_sessions = getattr(getattr(context.config, "time", None), "lab_sessions", {}) or {}

		for teacher_id, course_id, day_index, session_name, room_id, variable in iter_lab_session_variables(context):
			stats.checked_variables += 1
			req = requirements.get(course_id)
			if req is None:
				stats.missing_requirements += 1
				continue
			course_code = (req.course_code or "").strip()
			course_code_upper = course_code.upper()
			
			rule = next((r for r in rules if r.matches_course(course_code_upper)), None)
			if rule is None:
				continue



			day_label = self._resolve_day_label(context, lab_block.day_patterns, course_id, day_index)
			if rule.blocks_day(day_label):
				context.model.Add(variable == 0)
				stats.blocked_by_day += 1
				continue

			if rule.blocked_slot_indices:
				session_slots = lab_sessions.get(session_name)
				if not session_slots:
					stats.unknown_sessions += 1
					continue
				try:
					slot_indices = {int(idx) for idx in session_slots}
				except (TypeError, ValueError):
					stats.unknown_sessions += 1
					continue
				if slot_indices.intersection(rule.blocked_slot_indices):
					context.model.Add(variable == 0)
					stats.blocked_by_time += 1



		status = ConstraintStatus.APPLIED if (stats.blocked_by_day or stats.blocked_by_time) else ConstraintStatus.SKIPPED
		logger.info(
			"Special course time blocks checked=%d blocked_day=%d blocked_time=%d",
			stats.checked_variables,
			stats.blocked_by_day,
			stats.blocked_by_time,
		)
		return self._build_result(stats, status)

	@staticmethod
	def _normalize_days(days: Sequence[object]) -> Set[str]:
		normalized: Set[str] = set()
		for day in days:
			label = DayNormalizer.normalize_day_name(str(day or "").strip())
			if label:
				normalized.add(label)
		return normalized

	@classmethod
	def _parse_rules(
		cls,
		context: ConstraintContext,
		params: Mapping[str, object],
	) -> list[SpecialCourseTimeBlockRule]:
		def build_rule(raw: Mapping[str, Any]) -> Optional[SpecialCourseTimeBlockRule]:
			course_codes = {
				str(code).strip().upper()
				for code in (raw.get("course_codes") or [])
				if str(code).strip()
			}
			if not course_codes:
				return None

			blocked_days = cls._normalize_days(raw.get("blocked_days") or [])
			allowed_days_raw = cls._normalize_days(raw.get("allowed_days") or [])
			allowed_days: Optional[Set[str]] = allowed_days_raw if allowed_days_raw else None
			blocked_slot_indices = cls._resolve_blocked_slot_indices(context, raw)
			
			return SpecialCourseTimeBlockRule(
				course_codes=course_codes,
				blocked_days=blocked_days,
				allowed_days=allowed_days,
				blocked_slot_indices=blocked_slot_indices,
			)

		rules: list[SpecialCourseTimeBlockRule] = []
		raw_rules = params.get("rules")
		if isinstance(raw_rules, list):
			for item in raw_rules:
				if isinstance(item, Mapping):
					rule = build_rule(item)
					if rule is not None:
						rules.append(rule)
			return rules

		# Backward-compatible single-rule config
		single = build_rule(params) if isinstance(params, Mapping) else None
		if single is not None:
			rules.append(single)
		return rules

	@staticmethod
	def _resolve_blocked_slot_indices(context: ConstraintContext, params: Mapping[str, object]) -> Set[int]:
		indices: Set[int] = set()

		raw_indices = params.get("blocked_lab_slot_indices") or []
		for value in raw_indices:
			try:
				indices.add(int(value))
			except (TypeError, ValueError):
				continue

		labels = params.get("blocked_lab_slot_labels") or []
		if labels:
			lab_slots = list(getattr(getattr(context.config, "time", None), "lab_slots", []) or [])
			label_set = {str(label).strip() for label in labels if str(label).strip()}
			for idx, slot_label in enumerate(lab_slots):
				if str(slot_label).strip() in label_set:
					indices.add(idx)

		return indices

	def _resolve_day_label(
		self,
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
		if normalized:
			return normalized
		return f"day_{day_index}"

	def _build_result(self, stats: SpecialCourseTimeBlockStats, status: str) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=stats.to_details(),
		)


def build_special_course_time_blocks_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> SpecialCourseTimeBlocksConstraint:
	return SpecialCourseTimeBlocksConstraint(metadata=metadata, params=params)


__all__ = [
	"SpecialCourseTimeBlocksConstraint",
	"build_special_course_time_blocks_constraint",
]