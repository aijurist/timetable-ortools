"""Cross-system lunch alignment covering both lab and theory schedules."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
	build_presence_literal,
	parse_department_token,
	register_objective_penalty,
	resolve_group_slot_map,
)

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

DEFAULT_SOFT_SPLIT_LAB_SESSION_PAIRS: Tuple[Tuple[str, str], ...] = (
	("L2", "L3"),
	("L3", "L4"),
)


@dataclass(frozen=True)
class LunchAlignmentConfig:
	fallback_window: Tuple[int, ...]
	minimum_free_slots: int
	traditional_slots: Tuple[int, ...]
	min_traditional_free_slots: int
	natural_patterns: Tuple[NaturalLunchPattern, ...]
	flexible_tokens: Tuple[DepartmentToken, ...]
	soft_tokens: Tuple[DepartmentToken, ...]
	soft_semesters: Tuple[int, ...]
	hard_overrides: Tuple[str, ...]
	penalty_weight: int
	soft_split_lab_session_pairs: Tuple[Tuple[str, str], ...]

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
		soft_tokens = list(params.get("soft_departments", ()))
		soft_semesters = tuple(int(s) for s in params.get("soft_semesters", ()))
		hard_overrides = tuple(str(d) for d in params.get("hard_overrides", ()))
		penalty_weight = int(params.get("penalty_weight", 10))
		split_pair_payload = params.get(
			"soft_split_lab_session_pairs",
			params.get("split_lab_session_pairs", DEFAULT_SOFT_SPLIT_LAB_SESSION_PAIRS),
		)
		split_pairs = []
		for pair in split_pair_payload or ():
			if isinstance(pair, str):
				parts = [part.strip() for part in pair.replace("->", ",").split(",") if part.strip()]
			else:
				parts = [str(part).strip() for part in pair if str(part).strip()]
			if len(parts) >= 2:
				split_pairs.append((parts[0], parts[1]))
		return LunchAlignmentConfig(
			fallback_window=default_window,
			minimum_free_slots=minimum_free,
			traditional_slots=traditional_slots,
			min_traditional_free_slots=min_traditional,
			natural_patterns=natural_patterns,
			flexible_tokens=_normalize_department_tokens(flexible_tokens),
			soft_tokens=_normalize_department_tokens(soft_tokens),
			soft_semesters=soft_semesters,
			hard_overrides=hard_overrides,
			penalty_weight=penalty_weight,
			soft_split_lab_session_pairs=tuple(split_pairs) or DEFAULT_SOFT_SPLIT_LAB_SESSION_PAIRS,
		)

	def is_flexible(self, department: str, semester: Optional[int]) -> bool:
		return _matches_department(self.flexible_tokens, department, semester)

	def is_soft(self, department: str, semester: Optional[int]) -> bool:
		if department in self.hard_overrides:
			return False
		if self.soft_tokens and _matches_department(self.soft_tokens, department, semester):
			return True
		if semester is not None and semester in self.soft_semesters:
			return True
		return False


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


def _build_group_course_lab_session_map(
	lab_block,
) -> Dict[str, Dict[str, Dict[int, Dict[str, Dict[str, Tuple[cp_model.IntVar, ...]]]]]]:
	mapping: MutableMapping[
		str,
		MutableMapping[
			str,
			MutableMapping[int, MutableMapping[str, MutableMapping[str, list[cp_model.IntVar]]]],
		],
	] = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))))
	assignments = getattr(lab_block, "assignments", {}) or {}
	group_lookup = getattr(lab_block, "instance_group_lookup", {}) or {}
	requirements = getattr(lab_block, "requirements", {}) or {}
	for teacher_map in assignments.values():
		for course_id, day_map in teacher_map.items():
			requirement = requirements.get(course_id)
			group_id = group_lookup.get(course_id) or getattr(requirement, "group_id", None)
			course_code = getattr(requirement, "course_code", None) or str(course_id)
			if not group_id or not course_code:
				continue
			for day_idx, session_map in day_map.items():
				for session_name, room_map in session_map.items():
					mapping[group_id][course_code][day_idx][session_name][str(course_id)].extend(room_map.values())
	result: Dict[str, Dict[str, Dict[int, Dict[str, Dict[str, Tuple[cp_model.IntVar, ...]]]]]] = {}
	for group_id, course_map in mapping.items():
		result[group_id] = {
			course_code: {
				day_idx: {
					session: {
						instance_id: tuple(vars_list)
						for instance_id, vars_list in instance_map.items()
					}
					for session, instance_map in session_map.items()
				}
				for day_idx, session_map in day_map.items()
			}
			for course_code, day_map in course_map.items()
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
		course_lab_sessions_by_group = _build_group_course_lab_session_map(lab_block)
		lab_overlap_cache: Dict[int, Tuple[str, ...]] = {}

		standard_groups = 0
		flexible_groups = 0
		soft_groups = 0
		theory_guards = 0
		lab_guards = 0
		flexible_guards = 0
		soft_penalties = 0

		dept_sem_groups: Dict[Tuple[str, Optional[int]], list[str]] = defaultdict(list)
		group_windows: Dict[Tuple[str, Optional[int]], Tuple[int, ...]] = {}
		for group_id, requirement in theory_block.requirements.items():
			dept = getattr(requirement, "department", None)
			semester = getattr(requirement, "semester", None)
			if not dept:
				continue
			key = (dept, semester if semester is None else int(semester))
			dept_sem_groups[key].append(group_id)
			window = tuple(requirement.lunch_slot_window or config.fallback_window)
			if window:
				group_windows[key] = window

		working_days = tuple(getattr(context.data.raw.time, "working_days", tuple()))

		for key, group_ids in dept_sem_groups.items():
			dept, semester = key
			window = group_windows.get(key, config.fallback_window)
			if not window:
				continue
			if config.is_flexible(dept, semester):
				for group_id in group_ids:
					day_map = group_slot_map.get(group_id)
					if not day_map:
						continue
					flexible_groups += 1
					flexible_guards += self._apply_flexible_lunch(
						context.model,
						config,
						group_id,
						day_map,
						lab_sessions_by_group.get(group_id, {}),
					)
			elif config.is_soft(dept, semester):
				cohort_group_ids = tuple(group_ids)
				soft_groups += len(cohort_group_ids)
				soft_penalties += self._apply_soft_lunch(
					context,
					config,
					key,
					cohort_group_ids,
					group_slot_map,
					lab_sessions_by_group,
					course_lab_sessions_by_group,
					lab_overlap_cache,
					context.data.raw.time.lab_session_to_theory,
					working_days,
					window,
				)
			else:
				cohort_group_ids = tuple(group_ids)
				theory_delta, lab_delta = self._apply_standard_lunch(
					context.model,
					config,
					key,
					cohort_group_ids,
					group_slot_map,
					lab_sessions_by_group,
					lab_overlap_cache,
					context.data.raw.time.lab_session_to_theory,
					working_days,
					window,
				)
				standard_groups += len(cohort_group_ids)
				theory_guards += theory_delta
				lab_guards += lab_delta

		status = (
			ConstraintStatus.APPLIED
			if (theory_guards or lab_guards or flexible_guards or soft_penalties)
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
				"soft_groups": soft_groups,
				"soft_penalties": soft_penalties,
			},
		)

	def _apply_standard_lunch(
		self,
		model: cp_model.CpModel,
		config: LunchAlignmentConfig,
		cohort_key: Tuple[str, Optional[int]],
		group_ids: Sequence[str],
		group_slot_map: Mapping[str, Mapping[int, Mapping[int, cp_model.IntVar]]],
		lab_sessions: Mapping[str, Mapping[int, Mapping[str, Tuple[cp_model.IntVar, ...]]]],
		lab_overlap_cache: Dict[int, Tuple[str, ...]],
		lab_session_to_theory: Mapping[str, Sequence[int]],
		working_days: Sequence[str],
		window: Tuple[int, ...],
	) -> Tuple[int, int]:
		cohort_label = self._cohort_label(*cohort_key)
		theory_clauses = 0
		lab_clauses = 0
		session_literal_cache: Dict[Tuple[str, int, str], cp_model.IntVar] = {}

		day_indices: set[int] = set()
		for group_id in group_ids:
			day_indices.update(group_slot_map.get(group_id, {}).keys())
			day_indices.update(lab_sessions.get(group_id, {}).keys())
		if not day_indices:
			day_indices = set(range(len(working_days))) if working_days else {0}

		for day_idx in sorted(day_indices):
			slot_literals: list[cp_model.IntVar] = []
			for slot in window:
				slot_literal = model.NewBoolVar(f"lunch_free_{cohort_label}_d{day_idx}_s{slot}")
				slot_literals.append(slot_literal)
				slot_busy_terms: list[cp_model.IntVar] = []

				for group_id in group_ids:
					day_map = group_slot_map.get(group_id, {})
					slot_map = day_map.get(day_idx, {}) if isinstance(day_map, Mapping) else {}
					slot_var = slot_map.get(slot) if isinstance(slot_map, Mapping) else None
					if slot_var is not None:
						slot_busy_terms.append(slot_var)
					group_day_sessions = lab_sessions.get(group_id, {}).get(day_idx, {})
					for session_name in self._lab_sessions_for_slot(slot, lab_overlap_cache, lab_session_to_theory):
						vars_tuple = group_day_sessions.get(session_name)
						if not vars_tuple:
							continue
						cache_key = (group_id, day_idx, session_name)
						literal = session_literal_cache.get(cache_key)
						if literal is None:
							literal = build_presence_literal(
								model,
								vars_tuple,
								f"lunch_lab_{group_id}_d{day_idx}_{session_name}",
							)
							if literal is None:
								continue
							session_literal_cache[cache_key] = literal
							lab_clauses += 1
						slot_busy_terms.append(literal)

				if slot_busy_terms:
					busy_literal = build_presence_literal(
						model,
						tuple(slot_busy_terms),
						f"lunch_busy_{cohort_label}_d{day_idx}_s{slot}",
					)
					if busy_literal is not None:
						model.Add(slot_literal + busy_literal == 1)
						theory_clauses += 1

			if slot_literals:
				required_free = min(config.minimum_free_slots, len(slot_literals))
				model.Add(sum(slot_literals) >= required_free)
				theory_clauses += 1

		return theory_clauses, lab_clauses

	def _apply_soft_lunch(
		self,
		context: ConstraintContext,
		config: LunchAlignmentConfig,
		cohort_key: Tuple[str, Optional[int]],
		group_ids: Sequence[str],
		group_slot_map: Mapping[str, Mapping[int, Mapping[int, cp_model.IntVar]]],
		lab_sessions: Mapping[str, Mapping[int, Mapping[str, Tuple[cp_model.IntVar, ...]]]],
		course_lab_sessions: Mapping[str, Mapping[str, Mapping[int, Mapping[str, Mapping[str, Tuple[cp_model.IntVar, ...]]]]]],
		lab_overlap_cache: Dict[int, Tuple[str, ...]],
		lab_session_to_theory: Mapping[str, Sequence[int]],
		working_days: Sequence[str],
		window: Tuple[int, ...],
	) -> int:
		model = context.model
		cohort_label = self._cohort_label(*cohort_key)
		penalties = 0
		session_literal_cache: Dict[Tuple[str, int, str], cp_model.IntVar] = {}

		for group_id in group_ids:
			day_indices: set[int] = set()
			day_indices.update(group_slot_map.get(group_id, {}).keys())
			day_indices.update(lab_sessions.get(group_id, {}).keys())
			if not day_indices:
				day_indices = set(range(len(working_days))) if working_days else {0}

			for day_idx in sorted(day_indices):
				free_literals: list[cp_model.IntVar] = []
				free_constants = 0
				for slot in window:
					slot_busy_terms: list[cp_model.IntVar] = []
					day_map = group_slot_map.get(group_id, {})
					slot_map = day_map.get(day_idx, {}) if isinstance(day_map, Mapping) else {}
					slot_var = slot_map.get(slot) if isinstance(slot_map, Mapping) else None
					if slot_var is not None:
						slot_busy_terms.append(slot_var)
					group_day_sessions = lab_sessions.get(group_id, {}).get(day_idx, {})
					for session_name in self._lab_sessions_for_slot(slot, lab_overlap_cache, lab_session_to_theory):
						vars_tuple = group_day_sessions.get(session_name)
						if not vars_tuple:
							continue
						cache_key = (group_id, day_idx, session_name)
						literal = session_literal_cache.get(cache_key)
						if literal is None:
							literal = build_presence_literal(
								model,
								vars_tuple,
								f"soft_lunch_lab_{group_id}_d{day_idx}_{session_name}",
							)
							if literal is None:
								continue
							session_literal_cache[cache_key] = literal
						slot_busy_terms.append(literal)
					if slot_busy_terms:
						busy_literal = build_presence_literal(
							model,
							slot_busy_terms,
							f"soft_lunch_busy_{group_id}_d{day_idx}_s{slot}",
						)
						if busy_literal is None:
							free_constants += 1
							continue
						free_literal = model.NewBoolVar(f"soft_lunch_free_{group_id}_d{day_idx}_s{slot}")
						model.Add(free_literal + busy_literal == 1)
						free_literals.append(free_literal)
					else:
						free_constants += 1

				required_free = min(config.minimum_free_slots, len(window))
				if required_free <= 0 or free_constants >= required_free:
					continue

				needed_free_literals = required_free - free_constants
				common_lunch_literal = model.NewBoolVar(f"soft_lunch_common_{group_id}_d{day_idx}")
				model.Add(sum(free_literals) >= needed_free_literals).OnlyEnforceIf(common_lunch_literal)
				model.Add(sum(free_literals) <= needed_free_literals - 1).OnlyEnforceIf(common_lunch_literal.Not())

				satisfaction_literals = [common_lunch_literal]
				split_literal = self._build_soft_split_lab_lunch_literal(
					model,
					config,
					group_id,
					day_idx,
					course_lab_sessions.get(group_id, {}),
				)
				if split_literal is not None:
					satisfaction_literals.append(split_literal)

				satisfied_literal = build_presence_literal(
					model,
					tuple(satisfaction_literals),
					f"soft_lunch_satisfied_{group_id}_d{day_idx}",
				)
				if satisfied_literal is None:
					continue

				violation_literal = model.NewBoolVar(f"soft_lunch_violation_{group_id}_d{day_idx}")
				model.Add(violation_literal + satisfied_literal == 1)
				register_objective_penalty(
					context,
					violation_literal,
					weight=config.penalty_weight,
					tag="lunch:soft",
				)
				penalties += 1

		return penalties

	def _build_soft_split_lab_lunch_literal(
		self,
		model: cp_model.CpModel,
		config: LunchAlignmentConfig,
		group_id: str,
		day_idx: int,
		course_lab_sessions: Mapping[str, Mapping[int, Mapping[str, Mapping[str, Tuple[cp_model.IntVar, ...]]]]],
	) -> Optional[cp_model.IntVar]:
		pair_literals: list[cp_model.IntVar] = []
		instance_session_cache: Dict[Tuple[str, str, str], cp_model.IntVar] = {}

		for course_code, day_map in course_lab_sessions.items():
			session_map = day_map.get(day_idx, {}) if isinstance(day_map, Mapping) else {}
			if not session_map:
				continue
			for first_session, second_session in config.soft_split_lab_session_pairs:
				first_instances = session_map.get(first_session, {})
				second_instances = session_map.get(second_session, {})
				if not first_instances or not second_instances:
					continue
				for first_instance, first_vars in first_instances.items():
					first_literal = self._course_instance_session_literal(
						model,
						instance_session_cache,
						group_id,
						day_idx,
						course_code,
						first_instance,
						first_session,
						first_vars,
					)
					if first_literal is None:
						continue
					for second_instance, second_vars in second_instances.items():
						if first_instance == second_instance:
							continue
						second_literal = self._course_instance_session_literal(
							model,
							instance_session_cache,
							group_id,
							day_idx,
							course_code,
							second_instance,
							second_session,
							second_vars,
						)
						if second_literal is None:
							continue
						pair_literal = model.NewBoolVar(
							"soft_lunch_split_"
							f"{self._safe_name(group_id)}_d{day_idx}_"
							f"{self._safe_name(course_code)}_"
							f"{self._safe_name(first_instance)}_{self._safe_name(first_session)}_"
							f"{self._safe_name(second_instance)}_{self._safe_name(second_session)}"
						)
						model.AddBoolAnd([first_literal, second_literal]).OnlyEnforceIf(pair_literal)
						model.AddBoolOr([first_literal.Not(), second_literal.Not()]).OnlyEnforceIf(
							pair_literal.Not()
						)
						pair_literals.append(pair_literal)

		return build_presence_literal(
			model,
			tuple(pair_literals),
			f"soft_lunch_split_satisfied_{self._safe_name(group_id)}_d{day_idx}",
		)

	def _course_instance_session_literal(
		self,
		model: cp_model.CpModel,
		cache: MutableMapping[Tuple[str, str, str], cp_model.IntVar],
		group_id: str,
		day_idx: int,
		course_code: str,
		instance_id: str,
		session_name: str,
		vars_tuple: Tuple[cp_model.IntVar, ...],
	) -> Optional[cp_model.IntVar]:
		cache_key = (course_code, instance_id, session_name)
		literal = cache.get(cache_key)
		if literal is not None:
			return literal
		literal = build_presence_literal(
			model,
			vars_tuple,
			"soft_lunch_split_inst_"
			f"{self._safe_name(group_id)}_d{day_idx}_"
			f"{self._safe_name(course_code)}_"
			f"{self._safe_name(instance_id)}_{self._safe_name(session_name)}",
		)
		if literal is not None:
			cache[cache_key] = literal
		return literal

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

	@staticmethod
	def _cohort_label(department: str, semester: Optional[int]) -> str:
		label = (department or "unknown").replace(" ", "_")
		if semester is None:
			return label
		return f"{label}_S{semester}"

	@staticmethod
	def _safe_name(value: object) -> str:
		text = str(value or "unknown")
		cleaned = "".join(ch if ch.isalnum() else "_" for ch in text)
		return cleaned.strip("_") or "unknown"


def build_lunch_alignment_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> LunchAlignmentConstraint:
	return LunchAlignmentConstraint(metadata=metadata, params=params)


__all__ = ["LunchAlignmentConstraint", "build_lunch_alignment_constraint"]
