"""Lab course requirement constraints with capacity and block priorities."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import FrozenSet, List, Mapping, MutableMapping, Optional, Sequence

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
	build_presence_literal,
	ensure_extra_bucket,
	iter_lab_session_variables,
	register_objective_penalty,
)


@dataclass(frozen=True)
class RoomCategoryIndex:
	small_35: FrozenSet[str]
	large_70_plus: FrozenSet[str]
	large_140: FrozenSet[str]
	kj_block_small: FrozenSet[str]
	techlounge_small: FrozenSet[str]
	all_lab_rooms: FrozenSet[str]
	capacity_lookup: Mapping[str, int]
	block_lookup: Mapping[str, str]


@dataclass
class RequirementStats:
	constrained_courses: int = 0
	strategy_courses: int = 0
	fallback_courses: int = 0
	techlounge_blocks: int = 0
	block_preferences: int = 0
	missing_courses: List[str] = field(default_factory=list)

	def as_details(self) -> Mapping[str, object]:
		return {
			"courses": self.constrained_courses,
			"strategy_courses": self.strategy_courses,
			"fallback_courses": self.fallback_courses,
			"techlounge_blocks": self.techlounge_blocks,
			"block_preferences": self.block_preferences,
			"missing_courses": tuple(self.missing_courses),
		}


@dataclass
class AssignmentBundle:
	all_vars: List[cp_model.IntVar]
	small_vars: List[cp_model.IntVar]
	large_vars: List[cp_model.IntVar]
	large_140_vars: List[cp_model.IntVar]
	kj_vars: List[cp_model.IntVar]
	techlounge_vars: List[cp_model.IntVar]
	non_kj_small_vars: List[cp_model.IntVar]

	@classmethod
	def empty(cls) -> "AssignmentBundle":
		return cls([], [], [], [], [], [], [])

	@property
	def has_any(self) -> bool:
		return bool(self.all_vars)

	@property
	def has_dual_capacity(self) -> bool:
		return bool(self.small_vars and self.large_vars)


class LabCourseRequirementConstraint(Constraint):
	"""Mirror legacy course-level lab requirements with capacity priorities."""

	_PRIORITY_DEPARTMENTS = frozenset(
		replace.lower()
		for replace in (
			"computer science & engineering",
			"computer science and engineering",
			"information technology",
		)
	)
	_BLOCK_PRIORITY_DEPARTMENTS = frozenset(
		replace.lower()
		for replace in (
			"artificial intelligence & machine learning",
			"artificial intelligence and machine learning",
			"artificial intelligence & data science",
			"artificial intelligence and data science",
			"computer science & design",
			"computer science and design",
		)
	)
	_TECHLOUNGE_RESTRICTED = _BLOCK_PRIORITY_DEPARTMENTS

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("course_requirements")
		stats = RequirementStats()
		room_index = self._get_room_index(context)
		lab_block = context.variables.lab

		for course_id, requirement in lab_block.requirements.items():
			assignments = list(iter_lab_session_variables(context, course_instance_id=course_id))
			if not assignments:
				stats.missing_courses.append(course_id)
				logger.warning("No lab assignment variables produced for %s", course_id)
				continue

			bundle = self._categorise_assignments(assignments, room_index)
			if not bundle.has_any:
				stats.missing_courses.append(course_id)
				logger.warning("Lab course %s has zero valid assignment vars", course_id)
				continue

			self._apply_department_block_rules(context, requirement.department, bundle, stats)
			self._apply_course_requirement(context, requirement, bundle, stats)
			stats.constrained_courses += 1

		status = ConstraintStatus.APPLIED if stats.constrained_courses else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=stats.as_details(),
		)

	def _apply_course_requirement(
		self,
		context: ConstraintContext,
		requirement,
		bundle: AssignmentBundle,
		stats: RequirementStats,
	) -> None:
		model = context.model
		student_count = max(0, int(requirement.student_count or 0))
		base_sessions = max(1, int(requirement.required_sessions or 0))
		practical_hours = max(0, int(requirement.practical_hours or 0))
		total_sum = sum(bundle.all_vars)
		dept_label = (requirement.department or "").strip().lower()

		# Handle large courses (100+ students, typically 140)
		# Priority 1: Schedule in 140-capacity labs
		if student_count >= 100:
			if bundle.large_140_vars:
				# Enforce use of 140-capacity rooms
				model.Add(sum(bundle.large_140_vars) == total_sum)
			
			# For 140 students in 140 capacity room, we don't need batching
			# We just need the base required sessions
			model.Add(total_sum == base_sessions)
			return

		if student_count == 35 and bundle.small_vars:
			model.Add(sum(bundle.small_vars) == total_sum)
			if bundle.large_vars:
				model.Add(sum(bundle.large_vars) == 0)
			model.Add(total_sum == base_sessions)
			return

		if student_count <= 35:
			unbatched_limit = self._unbatched_limit(base_sessions, practical_hours)
			model.Add(total_sum == unbatched_limit)
			return

		batched_target, unbatched_target = self._strategy_targets(base_sessions, student_count, practical_hours)

		if not bundle.small_vars or not bundle.large_vars:
			stats.fallback_courses += 1
			if bundle.small_vars:
				model.Add(total_sum == batched_target)
			else:
				model.Add(total_sum == unbatched_target)
			return

		strategy = model.NewBoolVar(f"{requirement.course_instance_id}_use_small_labs")
		model.Add(sum(bundle.small_vars) == total_sum).OnlyEnforceIf(strategy)
		model.Add(sum(bundle.large_vars) == 0).OnlyEnforceIf(strategy)
		model.Add(sum(bundle.large_vars) == total_sum).OnlyEnforceIf(strategy.Not())
		model.Add(sum(bundle.small_vars) == 0).OnlyEnforceIf(strategy.Not())
		model.Add(total_sum == batched_target).OnlyEnforceIf(strategy)
		model.Add(total_sum == unbatched_target).OnlyEnforceIf(strategy.Not())
		stats.strategy_courses += 1

		prefer_large, weight = self._capacity_preference_weight(dept_label, practical_hours)
		if weight > 0:
			tag = f"lab_balance:course:{requirement.course_instance_id}:capacity"
			literal = strategy if prefer_large else strategy.Not()
			register_objective_penalty(context, literal, weight, tag=tag)

		if dept_label in self._BLOCK_PRIORITY_DEPARTMENTS:
			non_kj_literal = build_presence_literal(
				model,
				bundle.non_kj_small_vars,
				f"non_kj_{requirement.course_instance_id}",
			)
			if non_kj_literal is not None and bundle.kj_vars:
				register_objective_penalty(
					context,
					non_kj_literal,
					self._block_penalty_weight(),
					tag=f"room_spread:block:{requirement.course_instance_id}",
				)
				stats.block_preferences += 1

	def _apply_department_block_rules(
		self,
		context: ConstraintContext,
		department: str,
		bundle: AssignmentBundle,
		stats: RequirementStats,
	) -> None:
		dept_label = (department or "").strip().lower()
		if dept_label in self._TECHLOUNGE_RESTRICTED and bundle.techlounge_vars:
			context.model.Add(sum(bundle.techlounge_vars) == 0)
			stats.techlounge_blocks += 1

	def _strategy_targets(
		self,
		base_sessions: int,
		student_count: int,
		practical_hours: int,
	) -> tuple[int, int]:
		batched_multiplier = max(1, math.ceil(student_count / 35))
		batched_sessions = base_sessions * batched_multiplier
		# Coverage should always satisfy the required practical hours.
		# `base_sessions` is derived upstream as ceil(practical_hours / 2).
		# When batching is used, each batch needs the full `base_sessions`.
		return batched_sessions, base_sessions

	@staticmethod
	def _unbatched_limit(base_sessions: int, practical_hours: int) -> int:
		# Do not cap below required sessions. Historically, caps assumed
		# practical_hours in {2,4,6}, but newer inputs can be 8+.
		return base_sessions

	def _capacity_preference_weight(self, department: str, practical_hours: int) -> tuple[bool, int]:
		dept_key = department.lower()
		priority_hours = practical_hours >= 4
		if practical_hours >= 6:
			return True, 1300 if dept_key in self._PRIORITY_DEPARTMENTS else 1000
		if priority_hours:
			return True, 1300 if dept_key in self._PRIORITY_DEPARTMENTS else 200
		if dept_key in self._PRIORITY_DEPARTMENTS:
			return True, 150
		return False, 100

	def _block_penalty_weight(self) -> int:
		weight = self.params.get("block_priority_weight") if isinstance(self.params, Mapping) else None
		try:
			return max(1, int(weight)) if weight is not None else 400
		except (TypeError, ValueError):
			return 400

	def _categorise_assignments(
		self,
		assignments: Sequence[tuple[str, str, int, str, str, cp_model.IntVar]],
		room_index: RoomCategoryIndex,
	) -> AssignmentBundle:
		bundle = AssignmentBundle.empty()
		for _teacher_id, _course_id, _day_idx, _session_name, room_id, var in assignments:
			room_key = str(room_id)
			bundle.all_vars.append(var)
			if room_key in room_index.small_35:
				bundle.small_vars.append(var)
				if room_key in room_index.kj_block_small:
					bundle.kj_vars.append(var)
				else:
					bundle.non_kj_small_vars.append(var)
				if room_key in room_index.techlounge_small:
					bundle.techlounge_vars.append(var)
			else:
				bundle.large_vars.append(var)
				if room_key in room_index.large_140:
					bundle.large_140_vars.append(var)
		return bundle

	def _get_room_index(self, context: ConstraintContext) -> RoomCategoryIndex:
		bucket = ensure_extra_bucket(context, "lab_room_index")
		index = bucket.get("categories")
		if isinstance(index, RoomCategoryIndex):
			return index
		registry = getattr(getattr(context.data, "raw", None), "room_registry", {}) or {}
		# Include every room that actually received a lab decision variable, even
		# when the room registry has ``is_lab=0``.  Explicit core/computer mappings
		# can legitimately route a course to such a room (for example B126); omitting
		# it here misclassifies a 35-seat mapped lab as a large room and incorrectly
		# reduces a two-batch course to one session.
		lab_room_ids = {str(room_id) for room_id in context.variables.lab.room_ids}
		for teacher_map in context.variables.lab.assignments.values():
			for day_map in teacher_map.values():
				for session_map in day_map.values():
					for room_map in session_map.values():
						lab_room_ids.update(str(room_id) for room_id in room_map)
		small: set[str] = set()
		large: set[str] = set()
		large_140: set[str] = set()
		kj_small: set[str] = set()
		tech_small: set[str] = set()
		capacity_lookup: MutableMapping[str, int] = {}
		block_lookup: MutableMapping[str, str] = {}

		for room_id in lab_room_ids:
			room_key = str(room_id)
			room_info = registry.get(room_key, {})
			capacity = self._extract_capacity(room_info)
			block = str(room_info.get("block") or "").strip()
			capacity_lookup[room_key] = capacity or 0
			block_lookup[room_key] = block
			if capacity and capacity >= 70:
				large.add(room_key)
				if capacity >= 140:
					large_140.add(room_key)
			if capacity and capacity <= 40:
				small.add(room_key)
				block_lower = block.lower()
				if block_lower.startswith("k"):
					kj_small.add(room_key)
				elif block_lower.startswith("j"):
					kj_small.add(room_key)
				if "tech" in block_lower:
					tech_small.add(room_key)
		index = RoomCategoryIndex(
			small_35=frozenset(small),
			large_70_plus=frozenset(large),
			large_140=frozenset(large_140),
			kj_block_small=frozenset(kj_small),
			techlounge_small=frozenset(tech_small),
			all_lab_rooms=frozenset(lab_room_ids),
			capacity_lookup=dict(capacity_lookup),
			block_lookup=dict(block_lookup),
		)
		bucket["categories"] = index
		return index

	@staticmethod
	def _extract_capacity(room_info: Mapping[str, object]) -> Optional[int]:
		for key in ("room_max_cap", "room_capacity", "capacity", "max_cap"):
			value = room_info.get(key)
			if value in (None, ""):
				continue
			try:
				return int(float(value))
			except (TypeError, ValueError):
				continue
		return None


def build_lab_session_coverage_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> LabCourseRequirementConstraint:
	"""Factory helper used by the registry."""

	return LabCourseRequirementConstraint(metadata=metadata, params=params)


__all__ = [
	"LabCourseRequirementConstraint",
	"build_lab_session_coverage_constraint",
]
