"""Lunch window constraints for theory scheduling."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal, parse_department_token

DepartmentToken = Tuple[str, Optional[int]]


def _normalize_department_tokens(tokens: Iterable[str]) -> Set[DepartmentToken]:
	normalized: Set[DepartmentToken] = set()
	for token in tokens or ():
		dept, semester = parse_department_token(str(token))
		if dept:
			normalized.add((dept, semester))
	return normalized


def _matches_department(token_set: Set[DepartmentToken], department: str, semester: Optional[int]) -> bool:
	if not token_set:
		return False
	return (department, semester) in token_set or (department, None) in token_set


@dataclass(frozen=True)
class LunchBreakConfig:
	fallback_window: Tuple[int, ...] = (3, 4, 5)
	minimum_free_slots: int = 1
	flexible_departments: Tuple[str, ...] = tuple()

	@staticmethod
	def from_params(params: Optional[Mapping[str, object]]) -> "LunchBreakConfig":
		if not params:
			return LunchBreakConfig()
		window = tuple(int(slot) for slot in params.get("fallback_window", (3, 4, 5))) or (3, 4, 5)
		min_free = max(1, int(params.get("minimum_free_slots", 1)))
		flexible = tuple(str(token) for token in params.get("flexible_departments", ()))
		return LunchBreakConfig(
			fallback_window=window,
			minimum_free_slots=min_free,
			flexible_departments=flexible,
		)


class TheoryLunchBreakConstraint(Constraint):
	"""Ensure non-flexible departments preserve an explicit lunch break window."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		self._config = LunchBreakConfig.from_params(params)

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		theory_block = context.variables.theory
		departments = getattr(context.data.raw, "departments", None)
		flexible_tokens = list(self._config.flexible_departments)
		if departments is not None:
			flexible_tokens.extend(getattr(departments, "flexible_lunch_departments", ()) or [])
		flexible_index = _normalize_department_tokens(flexible_tokens)

		clauses = 0
		groups_guarded = set()
		flexible_skipped = 0

		for group_id, requirement in theory_block.requirements.items():
			if _matches_department(flexible_index, requirement.department, requirement.semester):
				flexible_skipped += 1
				continue

			window = tuple(requirement.lunch_slot_window or self._config.fallback_window)
			if not window:
				continue

			day_map = theory_block.group_timeslots.get(group_id, {})
			for day_idx, slot_map in day_map.items():
				slot_vars = [
					slot_map.get(slot)
					for slot in window
					if slot_map.get(slot) is not None
				]
				if not slot_vars:
					continue
				required_free = min(self._config.minimum_free_slots, len(slot_vars))
				max_active = len(slot_vars) - required_free
				model.Add(sum(slot_vars) <= max_active)
				clauses += 1
				groups_guarded.add(group_id)

		status = ConstraintStatus.APPLIED if clauses else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"groups": len(groups_guarded),
				"clauses": clauses,
				"flexible_skipped": flexible_skipped,
			},
		)


@dataclass(frozen=True)
class NaturalLunchPattern:
	lab_session: str
	required_theory_slots: Tuple[int, ...] = (6,)
	description: str = ""


DEFAULT_NATURAL_PATTERNS: Tuple[NaturalLunchPattern, ...] = (
	NaturalLunchPattern(lab_session="L3", required_theory_slots=(6,), description="L3 lab plus theory slot 6"),
	NaturalLunchPattern(lab_session="L4", required_theory_slots=(4,), description="Theory slot 4 plus L4 lab"),
)


@dataclass(frozen=True)
class FlexibleLunchConfig:
	traditional_slots: Tuple[int, ...] = (3, 4, 5)
	min_traditional_free_slots: int = 1
	natural_patterns: Tuple[NaturalLunchPattern, ...] = DEFAULT_NATURAL_PATTERNS
	eligible_departments: Tuple[str, ...] = tuple()

	@staticmethod
	def from_params(params: Optional[Mapping[str, object]]) -> "FlexibleLunchConfig":
		if not params:
			return FlexibleLunchConfig()
		traditional = tuple(int(slot) for slot in params.get("traditional_slots", (3, 4, 5))) or (3, 4, 5)
		min_free = max(1, int(params.get("min_traditional_free_slots", 1)))
		patterns_payload = params.get("natural_patterns", ())
		patterns_list: list[NaturalLunchPattern] = []
		for payload in patterns_payload:
			lab_session = str(payload.get("lab_session", "")).strip()
			if not lab_session:
				continue
			required_slots = tuple(int(slot) for slot in payload.get("required_theory_slots", ())) or (6,)
			patterns_list.append(
				NaturalLunchPattern(
					lab_session=lab_session,
					required_theory_slots=required_slots,
					description=str(payload.get("description", "")),
				)
			)
		pattern_tuple = tuple(patterns_list) if patterns_list else DEFAULT_NATURAL_PATTERNS
		eligible = tuple(str(token) for token in params.get("eligible_departments", ()))
		return FlexibleLunchConfig(
			traditional_slots=traditional,
			min_traditional_free_slots=min_free,
			natural_patterns=pattern_tuple,
			eligible_departments=eligible,
		)


def _build_group_lab_session_map(lab_block) -> Dict[str, Dict[int, Dict[str, Tuple[cp_model.IntVar, ...]]]]:
	mapping: Dict[str, Dict[int, Dict[str, list[cp_model.IntVar]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
	assignments = getattr(lab_block, "assignments", {}) or {}
	group_lookup = getattr(lab_block, "instance_group_lookup", {}) or {}
	for teacher_map in assignments.values():
		for course_instance_id, day_map in teacher_map.items():
			group_id = group_lookup.get(course_instance_id)
			if not group_id:
				continue
			for day_idx, session_map in day_map.items():
				for session_name, room_map in session_map.items():
					bucket = mapping[group_id][day_idx][session_name]
					bucket.extend(room_map.values())
	return {
		group: {
			day: {session: tuple(vars_list) for session, vars_list in session_map.items()}
			for day, session_map in day_map.items()
		}
		for group, day_map in mapping.items()
	}


class FlexibleLunchConstraint(Constraint):
	"""Guarantee flexible departments obtain either a classic or natural lunch break."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		self._config = FlexibleLunchConfig.from_params(params)

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		theory_block = context.variables.theory
		lab_block = context.variables.lab
		departments = getattr(context.data.raw, "departments", None)
		eligible_tokens = list(self._config.eligible_departments)
		if departments is not None:
			eligible_tokens.extend(getattr(departments, "flexible_lunch_departments", ()) or [])
		eligible_index = _normalize_department_tokens(eligible_tokens)
		if not eligible_index:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no eligible departments"},
			)

		lab_sessions_by_group = _build_group_lab_session_map(lab_block)
		clauses = 0
		guarded_groups = set()

		for group_id, requirement in theory_block.requirements.items():
			if not _matches_department(eligible_index, requirement.department, requirement.semester):
				continue
			window = tuple(requirement.lunch_slot_window or self._config.traditional_slots)
			day_map = theory_block.group_timeslots.get(group_id, {})
			for day_idx, slot_map in day_map.items():
				lunch_vars = [slot_map.get(slot) for slot in window if slot_map.get(slot) is not None]
				lunch_vars = [var for var in lunch_vars if var is not None]
				satisfaction_literals = []

				if lunch_vars and self._config.min_traditional_free_slots > 0:
					required_free = min(self._config.min_traditional_free_slots, len(lunch_vars))
					max_active = len(lunch_vars) - required_free
					traditional_literal = model.NewBoolVar(f"flex_lunch_trad_{group_id}_d{day_idx}")
					model.Add(sum(lunch_vars) <= max_active).OnlyEnforceIf(traditional_literal)
					model.Add(sum(lunch_vars) >= max_active + 1).OnlyEnforceIf(traditional_literal.Not())
					satisfaction_literals.append(traditional_literal)

				day_lab_sessions = lab_sessions_by_group.get(group_id, {}).get(day_idx, {})
				for pattern in self._config.natural_patterns:
					literal = self._build_natural_literal(
						model,
						pattern,
						group_id,
						day_idx,
						slot_map,
						day_lab_sessions,
					)
					if literal is not None:
						satisfaction_literals.append(literal)

				if satisfaction_literals:
					model.AddBoolOr(satisfaction_literals)
					clauses += 1
					guarded_groups.add(group_id)

		status = ConstraintStatus.APPLIED if clauses else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"groups": len(guarded_groups),
				"clauses": clauses,
				"natural_patterns": len(self._config.natural_patterns),
			},
		)

	def _build_natural_literal(
		self,
		model: cp_model.CpModel,
		pattern: NaturalLunchPattern,
		group_id: str,
		day_idx: int,
		slot_map: Mapping[int, cp_model.IntVar],
		day_lab_sessions: Mapping[str, Sequence[cp_model.IntVar]],
	) -> Optional[cp_model.IntVar]:
		session_vars = day_lab_sessions.get(pattern.lab_session)
		if not session_vars:
			return None
		lab_literal = build_presence_literal(
			model,
			tuple(session_vars),
			f"flex_lunch_{group_id}_d{day_idx}_{pattern.lab_session}",
		)
		if lab_literal is None:
			return None
		theory_vars = [slot_map.get(slot) for slot in pattern.required_theory_slots]
		if any(var is None for var in theory_vars):
			return None
		theory_literals = [var for var in theory_vars if var is not None]
		if not theory_literals:
			return lab_literal
		pattern_literal = model.NewBoolVar(f"flex_lunch_nat_{group_id}_d{day_idx}_{pattern.lab_session}")
		model.AddBoolAnd([lab_literal, *theory_literals]).OnlyEnforceIf(pattern_literal)
		negations = [lab_literal.Not(), *[var.Not() for var in theory_literals]]
		model.AddBoolOr(negations).OnlyEnforceIf(pattern_literal.Not())
		return pattern_literal


def build_theory_lunch_break_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TheoryLunchBreakConstraint:
	return TheoryLunchBreakConstraint(metadata=metadata, params=params)


def build_flexible_lunch_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> FlexibleLunchConstraint:
	return FlexibleLunchConstraint(metadata=metadata, params=params)


__all__ = [
	"TheoryLunchBreakConstraint",
	"FlexibleLunchConstraint",
	"build_theory_lunch_break_constraint",
	"build_flexible_lunch_constraint",
]
