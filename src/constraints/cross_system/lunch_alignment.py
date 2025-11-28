"""Cross-system lunch alignment covering both lab and theory schedules."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal, parse_department_token, resolve_group_slot_map

DepartmentToken = Tuple[str, Optional[int]]


def _normalize_department_tokens(tokens: Iterable[object]) -> Tuple[DepartmentToken, ...]:
	resolved = []
	for token in tokens or ():
		dept, semester = parse_department_token(str(token))
		if dept:
			resolved.append((dept, semester))
	return tuple(resolved)


def _matches_department(tokens: Sequence[DepartmentToken], department: str, semester: Optional[int]) -> bool:
	if not tokens:
		return False
	needle = (department, semester)
	return needle in tokens or (department, None) in tokens


@dataclass(frozen=True)
class NaturalLunchPattern:
	lab_session: str
	required_theory_slots: Tuple[int, ...]
	description: str = ""


DEFAULT_PATTERNS: Tuple[NaturalLunchPattern, ...] = (
	NaturalLunchPattern(lab_session="L3", required_theory_slots=(6,), description="L3 + slot 6"),
	NaturalLunchPattern(lab_session="L4", required_theory_slots=(4,), description="slot 4 + L4"),
)


@dataclass(frozen=True)
class LunchAlignmentConfig:
	fallback_window: Tuple[int, ...]
	minimum_free_slots: int
	traditional_slots: Tuple[int, ...]
	min_traditional_free_slots: int
	natural_patterns: Tuple[NaturalLunchPattern, ...]
	flexible_tokens: Tuple[DepartmentToken, ...]

	@staticmethod
	def from_context(context: ConstraintContext, params: Optional[Mapping[str, object]]) -> "LunchAlignmentConfig":
		params = params or {}
		departments = getattr(context.data.raw, "departments", None)
		default_window: Tuple[int, ...] = tuple(int(slot) for slot in params.get("lunch_slot_window", ()))
		if not default_window and departments is not None:
			default_window = tuple(getattr(departments, "lunch_slot_windows", {}).get("__default__", ()))
		if not default_window:
			default_window = (3, 4, 5)
		minimum_free = max(1, int(params.get("minimum_free_slots", 1)))
		traditional_slots = tuple(int(slot) for slot in params.get("traditional_slots", default_window)) or default_window
		min_traditional = max(1, int(params.get("min_traditional_free_slots", 1)))
		patterns_payload = params.get("natural_patterns", ())
		patterns = []
		for payload in patterns_payload or ():
			lab_session = str(payload.get("lab_session", "")).strip()
			if not lab_session:
				continue
			required = tuple(int(slot) for slot in payload.get("required_theory_slots", ()))
			if not required:
				required = (6,)
			patterns.append(
				NaturalLunchPattern(
					lab_session=lab_session,
					required_theory_slots=required,
					description=str(payload.get("description", "")),
				)
			)
		natural_patterns = tuple(patterns) if patterns else DEFAULT_PATTERNS
		flexible_tokens = list(params.get("flexible_departments", ()))
		if departments is not None:
			flexible_tokens.extend(getattr(departments, "flexible_lunch_departments", ()) or [])
		return LunchAlignmentConfig(
			fallback_window=default_window,
			minimum_free_slots=minimum_free,
			traditional_slots=traditional_slots,
			min_traditional_free_slots=min_traditional,
			natural_patterns=natural_patterns,
			flexible_tokens=_normalize_department_tokens(flexible_tokens),
		)

	def is_flexible(self, department: str, semester: Optional[int]) -> bool:
		return _matches_department(self.flexible_tokens, department, semester)


def _build_group_lab_session_map(lab_block) -> Dict[str, Dict[int, Dict[str, Tuple[cp_model.IntVar, ...]]]]:
	mapping: MutableMapping[str, MutableMapping[int, MutableMapping[str, list[cp_model.IntVar]]]] = defaultdict(
		lambda: defaultdict(lambda: defaultdict(list))
	)
	assignments = getattr(lab_block, "assignments", {}) or {}
	group_lookup = getattr(lab_block, "instance_group_lookup", {}) or {}
	for teacher_map in assignments.values():
		for course_id, day_map in teacher_map.items():
			group_id = group_lookup.get(course_id)
			if not group_id:
				continue
			for day_idx, session_map in day_map.items():
				for session_name, room_map in session_map.items():
					mapping[group_id][day_idx][session_name].extend(room_map.values())
	result: Dict[str, Dict[int, Dict[str, Tuple[cp_model.IntVar, ...]]]] = {}
	for group_id, day_map in mapping.items():
		result[group_id] = {
			day_idx: {session: tuple(vars_list) for session, vars_list in session_map.items()}
			for day_idx, session_map in day_map.items()
		}
	return result


class LunchAlignmentConstraint(Constraint):
	"""Coordinate lunch windows across lab and theory for every department."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		self._natural_literal_cache: Dict[str, cp_model.IntVar] = {}

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		config = LunchAlignmentConfig.from_context(context, self.params)
		theory_block = context.variables.theory
		group_slot_map = resolve_group_slot_map(context)
		lab_block = context.variables.lab
		if not theory_block.requirements or not group_slot_map:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no theory requirements"},
			)

		lab_sessions_by_group = _build_group_lab_session_map(lab_block)
		lab_overlap_cache: Dict[int, Tuple[str, ...]] = {}

		standard_groups = 0
		flexible_groups = 0
		theory_guards = 0
		lab_guards = 0
		flexible_guards = 0

		for group_id, requirement in theory_block.requirements.items():
			window = tuple(requirement.lunch_slot_window or config.fallback_window)
			if not window:
				continue
			day_map = group_slot_map.get(group_id)
			if not day_map:
				continue
			if config.is_flexible(requirement.department, requirement.semester):
				flexible_groups += 1
				flexible_guards += self._apply_flexible_lunch(
					context.model,
					config,
					group_id,
					day_map,
					lab_sessions_by_group.get(group_id, {}),
				)
			else:
				standard_groups += 1
				theory_delta, lab_delta = self._apply_standard_lunch(
					context.model,
					config,
					group_id,
					day_map,
					window,
					lab_sessions_by_group.get(group_id, {}),
					lab_overlap_cache,
					context.data.raw.time.lab_session_to_theory,
				)
				theory_guards += theory_delta
				lab_guards += lab_delta

		status = (
			ConstraintStatus.APPLIED
			if (theory_guards or lab_guards or flexible_guards)
			else ConstraintStatus.SKIPPED
		)
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"standard_groups": standard_groups,
				"flexible_groups": flexible_groups,
				"theory_clauses": theory_guards,
				"lab_clauses": lab_guards,
				"flexible_clauses": flexible_guards,
			},
		)

	def _apply_standard_lunch(
		self,
		model: cp_model.CpModel,
		config: LunchAlignmentConfig,
		group_id: str,
		day_map: Mapping[int, Mapping[int, cp_model.IntVar]],
		window: Tuple[int, ...],
		lab_sessions: Mapping[int, Mapping[str, Tuple[cp_model.IntVar, ...]]],
		lab_overlap_cache: Dict[int, Tuple[str, ...]],
		lab_session_to_theory: Mapping[str, Sequence[int]],
	) -> Tuple[int, int]:
		theory_clauses = 0
		lab_clauses = 0

		for day_idx, slot_map in day_map.items():
			slot_literals: list[cp_model.IntVar] = []
			day_sessions = lab_sessions.get(day_idx, {})
			session_literals: Dict[str, cp_model.IntVar] = {}
			for session_name, vars_tuple in day_sessions.items():
				literal = build_presence_literal(
					model,
					vars_tuple,
					f"lunch_lab_{group_id}_d{day_idx}_{session_name}",
				)
				if literal is not None:
					session_literals[session_name] = literal

			for slot in window:
				slot_literal = model.NewBoolVar(f"lunch_slot_{group_id}_d{day_idx}_s{slot}")
				slot_literals.append(slot_literal)
				slot_var = slot_map.get(slot)
				if slot_var is not None:
					model.Add(slot_var == 0).OnlyEnforceIf(slot_literal)
					theory_clauses += 1
				sessions_for_slot = self._lab_sessions_for_slot(slot, lab_overlap_cache, lab_session_to_theory)
				for session_name in sessions_for_slot:
					session_literal = session_literals.get(session_name)
					if session_literal is None:
						continue
					model.Add(session_literal == 0).OnlyEnforceIf(slot_literal)
					lab_clauses += 1

			if slot_literals:
				required_free = min(config.minimum_free_slots, len(slot_literals))
				model.Add(sum(slot_literals) == required_free)
				theory_clauses += 1

		return theory_clauses, lab_clauses

	def _apply_flexible_lunch(
		self,
		model: cp_model.CpModel,
		config: LunchAlignmentConfig,
		group_id: str,
		day_map: Mapping[int, Mapping[int, cp_model.IntVar]],
		lab_sessions: Mapping[int, Mapping[str, Tuple[cp_model.IntVar, ...]]],
	) -> int:
		clauses = 0
		for day_idx, slot_map in day_map.items():
			window = config.traditional_slots
			lunch_vars = [slot_map.get(slot) for slot in window if slot_map.get(slot) is not None]
			lunch_vars = [var for var in lunch_vars if var is not None]
			satisfaction_literals = []
			if lunch_vars:
				required_free = min(config.min_traditional_free_slots, len(lunch_vars))
				max_active = max(0, len(lunch_vars) - required_free)
				literal = model.NewBoolVar(f"flex_lunch_trad_{group_id}_d{day_idx}")
				model.Add(sum(lunch_vars) <= max_active).OnlyEnforceIf(literal)
				model.Add(sum(lunch_vars) >= max_active + 1).OnlyEnforceIf(literal.Not())
				satisfaction_literals.append(literal)

			day_sessions = lab_sessions.get(day_idx, {})
			for pattern in config.natural_patterns:
				literal = self._build_natural_literal(
					model,
					pattern,
					group_id,
					day_idx,
					slot_map,
					day_sessions,
				)
				if literal is not None:
					satisfaction_literals.append(literal)

			if satisfaction_literals:
				model.AddBoolOr(satisfaction_literals)
				clauses += 1
		return clauses

	def _build_natural_literal(
		self,
		model: cp_model.CpModel,
		pattern: NaturalLunchPattern,
		group_id: str,
		day_idx: int,
		slot_map: Mapping[int, cp_model.IntVar],
		day_sessions: Mapping[str, Tuple[cp_model.IntVar, ...]],
	) -> Optional[cp_model.IntVar]:
		session_vars = day_sessions.get(pattern.lab_session)
		if not session_vars:
			return None
		lab_literal = build_presence_literal(
			model,
			session_vars,
			f"flex_lunch_{group_id}_d{day_idx}_{pattern.lab_session}",
		)
		if lab_literal is None:
			return None
		theory_vars = [slot_map.get(slot) for slot in pattern.required_theory_slots]
		if any(var is None for var in theory_vars):
			return None
		literals = [var for var in theory_vars if var is not None]
		if not literals:
			return lab_literal
		pattern_literal = model.NewBoolVar(
			f"flex_lunch_nat_{group_id}_d{day_idx}_{pattern.lab_session}"
		)
		model.AddBoolAnd([lab_literal, *literals]).OnlyEnforceIf(pattern_literal)
		negations = [lab_literal.Not(), *[var.Not() for var in literals]]
		model.AddBoolOr(negations).OnlyEnforceIf(pattern_literal.Not())
		return pattern_literal

	@staticmethod
	def _lab_sessions_for_slot(
		slot: int,
		cache: MutableMapping[int, Tuple[str, ...]],
		lab_session_to_theory: Mapping[str, Sequence[int]],
	) -> Tuple[str, ...]:
		if slot not in cache:
			cache[slot] = tuple(
				session
				for session, slots in lab_session_to_theory.items()
				if slot in slots
			)
		return cache[slot]


def build_lunch_alignment_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> LunchAlignmentConstraint:
	return LunchAlignmentConstraint(metadata=metadata, params=params)


__all__ = ["LunchAlignmentConstraint", "build_lunch_alignment_constraint"]
