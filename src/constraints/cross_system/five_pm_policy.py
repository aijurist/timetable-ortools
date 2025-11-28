"""Unified 5pm policy constraint spanning lab and theory schedules."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import FrozenSet, Iterable, Mapping, MutableMapping, Optional, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
	build_presence_literal,
	iter_lab_session_variables,
	parse_department_token,
	register_objective_penalty,
	resolve_group_slot_map,
)

DepartmentToken = Tuple[str, Optional[int]]


@dataclass(frozen=True)
class PolicyBundle:
	hard_tokens: FrozenSet[DepartmentToken]
	soft_tokens: FrozenSet[DepartmentToken]
	blocked_theory_slots: Tuple[int, ...]
	blocked_lab_sessions: Tuple[str, ...]
	discouraged_theory_slots: Tuple[int, ...]
	discouraged_lab_sessions: Tuple[str, ...]

	@staticmethod
	def from_sources(
		payload: Optional[Mapping[str, Mapping[str, object]]],
		params: Mapping[str, object],
	) -> "PolicyBundle":
		hard_section = payload.get("hard", {}) if isinstance(payload, Mapping) else {}
		soft_section = payload.get("soft", {}) if isinstance(payload, Mapping) else {}

		hard_departments = params.get("hard_departments", hard_section.get("departments", ()))
		soft_departments = params.get("soft_departments", soft_section.get("departments", ()))

		blocked_theory_slots = _coerce_int_sequence(
			params.get("blocked_theory_slots", hard_section.get("blocked_theory_slots", ()))
		)
		blocked_lab_sessions = _coerce_str_sequence(
			params.get("blocked_lab_sessions", hard_section.get("blocked_lab_sessions", ()))
		)
		discouraged_theory_slots = _coerce_int_sequence(
			params.get("discouraged_theory_slots", soft_section.get("discouraged_theory_slots", ()))
		)
		discouraged_lab_sessions = _coerce_str_sequence(
			params.get("discouraged_lab_sessions", soft_section.get("discouraged_lab_sessions", ()))
		)

		return PolicyBundle(
			hard_tokens=frozenset(_normalize_department_tokens(hard_departments)),
			soft_tokens=frozenset(_normalize_department_tokens(soft_departments)),
			blocked_theory_slots=blocked_theory_slots,
			blocked_lab_sessions=blocked_lab_sessions,
			discouraged_theory_slots=discouraged_theory_slots,
			discouraged_lab_sessions=discouraged_lab_sessions,
		)

	@property
	def has_policies(self) -> bool:
		return bool(self.hard_tokens or self.soft_tokens)

	def severity(self, department: str, semester: Optional[int]) -> Optional[str]:
		if _matches_token(self.hard_tokens, department, semester):
			return "hard"
		if _matches_token(self.soft_tokens, department, semester):
			return "soft"
		return None


class FivePmPolicyConstraint(Constraint):
	"""Block or penalize late sessions based on department policy severity."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		default_weight = max(1, int(round(max(self.metadata.weight, 0.1) * 10)))
		weight_override = self.params.get("soft_penalty_weight") if self.params else None
		if weight_override is not None:
			try:
				default_weight = int(weight_override)
			except (TypeError, ValueError):
				default_weight = max(1, default_weight)
		self._penalty_weight = max(1, default_weight)

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		departments = getattr(getattr(context.data, "raw", None), "departments", None)
		payload = getattr(departments, "five_pm_constraints", None)
		policy = PolicyBundle.from_sources(payload, self.params or {})
		if not policy.has_policies:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no configured departments"},
			)

		model = context.model
		theory_block = context.variables.theory
		group_slot_map = resolve_group_slot_map(context)
		if not group_slot_map:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no theory groups available"},
			)
		lab_block = context.variables.lab
		lab_sessions = (
			_index_lab_sessions(context)
			if (policy.blocked_lab_sessions or policy.discouraged_lab_sessions)
			else {}
		)

		hard_theory_clauses = 0
		hard_lab_clauses = 0
		penalty_terms = 0

		if policy.blocked_theory_slots:
			for group_id, requirement in theory_block.requirements.items():
				if policy.severity(requirement.department, requirement.semester) != "hard":
					continue
				day_map = group_slot_map.get(group_id, {})
				for day_idx, slot_vars in day_map.items():
					for slot_idx in policy.blocked_theory_slots:
						var = slot_vars.get(slot_idx)
						if var is None:
							continue
						model.Add(var == 0)
						hard_theory_clauses += 1

		if policy.blocked_lab_sessions:
			for course_id, requirement in lab_block.requirements.items():
				if policy.severity(requirement.department, requirement.semester) != "hard":
					continue
				course_map = lab_sessions.get(course_id)
				if not course_map:
					continue
				for day_idx, vars_dict in course_map.items():
					for session_name in policy.blocked_lab_sessions:
						room_vars = vars_dict.get(session_name)
						if not room_vars:
							continue
						model.Add(sum(room_vars) == 0)
						hard_lab_clauses += 1

		if policy.discouraged_theory_slots:
			for group_id, requirement in theory_block.requirements.items():
				if policy.severity(requirement.department, requirement.semester) != "soft":
					continue
				day_map = group_slot_map.get(group_id, {})
				for day_idx, slot_vars in day_map.items():
					for slot_idx in policy.discouraged_theory_slots:
						var = slot_vars.get(slot_idx)
						if var is None:
							continue
						register_objective_penalty(
							context,
							var,
							self._penalty_weight,
							tag=f"theory:{group_id}:d{day_idx}:s{slot_idx}",
						)
						penalty_terms += 1

		if policy.discouraged_lab_sessions:
			for course_id, requirement in lab_block.requirements.items():
				if policy.severity(requirement.department, requirement.semester) != "soft":
					continue
				course_map = lab_sessions.get(course_id)
				if not course_map:
					continue
				for session_name in policy.discouraged_lab_sessions:
					for day_idx, vars_dict in course_map.items():
						room_vars = vars_dict.get(session_name)
						if not room_vars:
							continue
						literal = build_presence_literal(
							model,
							room_vars,
							f"fivepm_soft_lab_{course_id}_d{day_idx}_{session_name}",
						)
						if literal is None:
							continue
						register_objective_penalty(
							context,
							literal,
							self._penalty_weight,
							tag=f"lab:{course_id}:{session_name}",
						)
						penalty_terms += 1

		status = (
			ConstraintStatus.APPLIED
			if (hard_theory_clauses or hard_lab_clauses or penalty_terms)
			else ConstraintStatus.SKIPPED
		)
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"hard_theory_clauses": hard_theory_clauses,
				"hard_lab_clauses": hard_lab_clauses,
				"penalty_terms": penalty_terms,
				"hard_departments": len(policy.hard_tokens),
				"soft_departments": len(policy.soft_tokens),
			},
		)


def _normalize_department_tokens(tokens: Iterable[object]) -> Tuple[DepartmentToken, ...]:
	resolved: list[DepartmentToken] = []
	for token in tokens or ():  # type: ignore[arg-type]
		dept, semester = parse_department_token(str(token))
		if dept:
			resolved.append((dept, semester))
	return tuple(resolved)


def _matches_token(tokens: FrozenSet[DepartmentToken], department: str, semester: Optional[int]) -> bool:
	return (department, semester) in tokens or (department, None) in tokens


def _coerce_int_sequence(values: Optional[Iterable[object]]) -> Tuple[int, ...]:
	seen = set()
	result = []
	for value in values or ():
		try:
			number = int(value)
		except (TypeError, ValueError):
			continue
		if number in seen:
			continue
		seen.add(number)
		result.append(number)
	return tuple(result)


def _coerce_str_sequence(values: Optional[Iterable[object]]) -> Tuple[str, ...]:
	seen = set()
	result = []
	for value in values or ():
		text = str(value).strip()
		if not text or text in seen:
			continue
		seen.add(text)
		result.append(text)
	return tuple(result)


def _index_lab_sessions(
	context: ConstraintContext,
) -> Mapping[str, Mapping[int, Mapping[str, Tuple[cp_model.IntVar, ...]]]]:
	mapping: MutableMapping[str, MutableMapping[int, MutableMapping[str, list[cp_model.IntVar]]]] = defaultdict(
		lambda: defaultdict(lambda: defaultdict(list))
	)
	for _, course_id, day_idx, session_name, _room_id, var in iter_lab_session_variables(context):
		mapping[course_id][day_idx][session_name].append(var)
	return {
		course_id: {
			day_idx: {session: tuple(vars_list) for session, vars_list in day_map.items()}
			for day_idx, day_map in course_map.items()
		}
		for course_id, course_map in mapping.items()
	}


def build_five_pm_policy_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> FivePmPolicyConstraint:
	return FivePmPolicyConstraint(metadata=metadata, params=params)


__all__ = [
	"FivePmPolicyConstraint",
	"build_five_pm_policy_constraint",
]
