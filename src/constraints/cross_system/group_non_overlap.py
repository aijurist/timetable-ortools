"""Prevent cross-group overlaps between lab and theory schedules."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
	build_presence_literal,
	iter_course_timeslot_variables,
	iter_lab_session_variables,
	resolve_day_pattern,
	resolve_group_slot_map,
)

GroupKey = Tuple[str, int]
LabSessionPresenceMap = Mapping[str, Mapping[int, Mapping[str, Tuple[cp_model.IntVar, ...]]]]
TheorySlotSessionMap = Mapping[int, Tuple[str, ...]]


class GroupNonOverlapConstraint(Constraint):
	"""Ensure distinct groups within a department-semester never overlap."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
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

		if getattr(theory_block, "bundle_specs", None):
			return self._apply_kutty(context)

		group_index = _group_ids_by_semester(theory_block.requirements)
		relevant_keys = {key: ids for key, ids in group_index.items() if len(ids) > 1}
		if not relevant_keys:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no dept-semester pairs with multiple groups"},
			)

		lab_sessions = _collect_group_lab_sessions(context)

		overlap_index = _build_theory_lab_overlap_index(context)
		theory_slot_count = len(theory_block.theory_slot_labels)
		if theory_slot_count == 0:
			return ConstraintApplicationResult(
				name=self.metadata.name,
				domain=self.metadata.category,
				priority=self.metadata.priority,
				enabled=True,
				status=ConstraintStatus.SKIPPED,
				details={"reason": "no configured theory slots"},
			)

		guard_clauses = 0
		activity_literals = 0
		protected_pairs = 0

		for key, group_ids in relevant_keys.items():
			dept, _semester = key
			day_count = _resolve_day_count(context, theory_block, group_ids, dept)
			if day_count == 0:
				continue

			for day_idx in range(day_count):
				for slot_idx in range(theory_slot_count):
					group_literals = []
					for group_id in group_ids:
						literal = _build_activity_literal(
							context.model,
							group_slot_map,
							lab_sessions,
							overlap_index,
							group_id,
							day_idx,
							slot_idx,
						)
						if literal is not None:
							group_literals.append(literal)
							activity_literals += 1

					if len(group_literals) > 1:
						context.model.AddAtMostOne(group_literals)
						guard_clauses += 1
						protected_pairs += len(group_literals)

		status = ConstraintStatus.APPLIED if guard_clauses else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"dept_semesters": len(relevant_keys),
				"guard_clauses": guard_clauses,
				"activity_literals": activity_literals,
				"protected_group_entries": protected_pairs,
			},
		)

	def _apply_kutty(self, context: ConstraintContext) -> ConstraintApplicationResult:
		"""Use teacher-guarded overlap for cohorts containing Kutty bundles.

		Once a cohort selects permanent staff bundles, a group-level busy flag is
		too coarse: one staff offering may run while other offerings from another
		group remain available.  All groups in that Kutty cohort may therefore
		overlap, while the teacher-overlap constraint continues to prevent a real
		staff collision.  Cohorts without a paired Kutty bundle retain the legacy
		group non-overlap protection.
		"""

		theory_block = context.variables.theory
		group_index = _group_ids_by_semester(theory_block.requirements)
		theory_activity = _collect_group_theory_activity(context)
		lab_activity = _collect_group_lab_sessions(context)
		overlap_index = _build_theory_lab_overlap_index(context)
		kutty_cohorts = {
			(bundle.key.department, int(bundle.key.semester))
			for bundle in theory_block.bundle_specs.values()
			if bundle.is_paired
		}

		clauses = 0
		allowed_bundle_pairs = 0
		teacher_guarded_cohorts = 0
		for (department, semester), group_ids in group_index.items():
			if len(group_ids) <= 1:
				continue
			if (department, semester) in kutty_cohorts:
				teacher_guarded_cohorts += 1
				allowed_bundle_pairs += len(group_ids) * (len(group_ids) - 1) // 2
				continue
			day_count = _resolve_day_count(context, theory_block, group_ids, department)
			for first_index, first_group in enumerate(group_ids):
				for second_group in group_ids[first_index + 1 :]:
					for day_idx in range(day_count):
						for slot_idx in range(len(theory_block.theory_slot_labels)):
							first_vars = _raw_group_activity(
								theory_activity, lab_activity, overlap_index, first_group, day_idx, slot_idx
							)
							second_vars = _raw_group_activity(
								theory_activity, lab_activity, overlap_index, second_group, day_idx, slot_idx
							)
							if not first_vars or not second_vars:
								continue

							first_presence = build_presence_literal(
								context.model,
								first_vars,
								f"kutty_group_presence_{first_group}_d{day_idx}_s{slot_idx}",
							)
							second_presence = build_presence_literal(
								context.model,
								second_vars,
								f"kutty_group_presence_{second_group}_d{day_idx}_s{slot_idx}",
							)
							if first_presence is not None and second_presence is not None:
								context.model.AddAtMostOne(first_presence, second_presence)
								clauses += 1

		status = ConstraintStatus.APPLIED if clauses else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"mode": "kutty_bundle_aware",
				"guard_clauses": clauses,
				"allowed_bundle_group_pairs": allowed_bundle_pairs,
				"teacher_guarded_cohorts": teacher_guarded_cohorts,
				"paired_group_policy": "allow_cohort_overlap_teacher_guarded",
			},
		)


def _group_ids_by_semester(
	requirements: Mapping[str, object]
) -> Dict[GroupKey, Tuple[str, ...]]:
	bucket: MutableMapping[GroupKey, list[str]] = defaultdict(list)
	for group_id, requirement in requirements.items():
		dept = getattr(requirement, "department", None)
		semester = getattr(requirement, "semester", None)
		if not dept or semester is None:
			continue
		bucket[(dept, int(semester))].append(group_id)
	return {key: tuple(ids) for key, ids in bucket.items()}


def _collect_group_lab_sessions(context: ConstraintContext) -> LabSessionPresenceMap:
	bucket: MutableMapping[str, MutableMapping[int, MutableMapping[str, list[cp_model.IntVar]]]] = defaultdict(
		lambda: defaultdict(lambda: defaultdict(list))
	)
	lookup = context.variables.lab.instance_group_lookup
	for _teacher_id, course_id, day_idx, session_name, _room_id, var in iter_lab_session_variables(context):
		group_id = lookup.get(course_id)
		if not group_id:
			continue
		bucket[group_id][day_idx][session_name].append(var)

	return {
		group_id: {
			day_idx: {session: tuple(vars_) for session, vars_ in day_map.items()}
			for day_idx, day_map in group_map.items()
		}
		for group_id, group_map in bucket.items()
	}


def _collect_group_theory_activity(
	context: ConstraintContext,
) -> Mapping[str, Mapping[int, Mapping[int, Tuple[cp_model.IntVar, ...]]]]:
	bucket: MutableMapping[str, MutableMapping[int, MutableMapping[int, list[cp_model.IntVar]]]] = defaultdict(
		lambda: defaultdict(lambda: defaultdict(list))
	)
	requirements = getattr(context.variables.theory, "course_requirements", {}) or {}
	for _teacher_id, course_id, day_idx, slot_idx, var in iter_course_timeslot_variables(context):
		requirement = requirements.get(course_id)
		group_id = getattr(requirement, "group_id", None)
		if group_id:
			bucket[group_id][day_idx][slot_idx].append(var)
	return {
		group_id: {
			day_idx: {
				slot_idx: _dedupe_literals(variables)
				for slot_idx, variables in slot_map.items()
			}
			for day_idx, slot_map in day_map.items()
		}
		for group_id, day_map in bucket.items()
	}


def _raw_group_activity(
	theory_activity: Mapping[str, Mapping[int, Mapping[int, Tuple[cp_model.IntVar, ...]]]],
	lab_activity: LabSessionPresenceMap,
	overlap_index: TheorySlotSessionMap,
	group_id: str,
	day_idx: int,
	slot_idx: int,
) -> Tuple[cp_model.IntVar, ...]:
	variables = list(theory_activity.get(group_id, {}).get(day_idx, {}).get(slot_idx, ()))
	day_sessions = lab_activity.get(group_id, {}).get(day_idx, {})
	for session_name in overlap_index.get(slot_idx, ()):
		variables.extend(day_sessions.get(session_name, ()))
	return _dedupe_literals(variables)


def _dedupe_literals(variables: Sequence[cp_model.IntVar]) -> Tuple[cp_model.IntVar, ...]:
	seen: set[int] = set()
	result = []
	for variable in variables:
		identity = variable.Index()
		if identity in seen:
			continue
		seen.add(identity)
		result.append(variable)
	return tuple(result)


def _build_theory_lab_overlap_index(context: ConstraintContext) -> TheorySlotSessionMap:
	time = context.data.raw.time
	mapping: MutableMapping[int, list[str]] = defaultdict(list)
	for session_name, slots in getattr(time, "lab_session_to_theory", {}).items():
		for slot in slots:
			mapping[int(slot)].append(session_name)
	return {slot: tuple(session_names) for slot, session_names in mapping.items()}


def _resolve_day_count(
	context: ConstraintContext,
	theory_block,
	group_ids: Sequence[str],
	department: str,
) -> int:
	counts = [len(theory_block.day_patterns.get(group_id, ())) for group_id in group_ids]
	day_count = max(counts) if counts else 0
	if day_count == 0:
		day_count = len(resolve_day_pattern(context, department))
	return day_count


def _build_activity_literal(
	model: cp_model.CpModel,
	group_slot_map: Mapping[str, Mapping[int, Mapping[int, cp_model.IntVar]]],
	lab_sessions: LabSessionPresenceMap,
	overlap_index: TheorySlotSessionMap,
	group_id: str,
	day_idx: int,
	slot_idx: int,
) -> Optional[cp_model.IntVar]:
	activity_vars = []
	day_map = group_slot_map.get(group_id, {})
	slot_map = day_map.get(day_idx, {})
	theory_var = slot_map.get(slot_idx)
	if theory_var is not None:
		activity_vars.append(theory_var)

	group_sessions = lab_sessions.get(group_id, {})
	day_sessions = group_sessions.get(day_idx, {})
	for session_name in overlap_index.get(slot_idx, ()):  # theory-aligned lab sessions
		vars_tuple = day_sessions.get(session_name)
		if vars_tuple:
			activity_vars.extend(vars_tuple)

	if not activity_vars:
		return None

	# Optimization: skip helper bool when only one variable
	if len(activity_vars) == 1:
		return activity_vars[0]

	literal = model.NewBoolVar(f"group_non_overlap_{group_id}_d{day_idx}_s{slot_idx}")
	activity_sum = sum(activity_vars)
	model.Add(activity_sum >= literal)
	model.Add(activity_sum <= len(activity_vars) * literal)
	return literal


def build_group_non_overlap_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> GroupNonOverlapConstraint:
	return GroupNonOverlapConstraint(metadata=metadata, params=params)


__all__ = ["GroupNonOverlapConstraint", "build_group_non_overlap_constraint"]
