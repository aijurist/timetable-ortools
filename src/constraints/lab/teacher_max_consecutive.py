"""Limit teacher lab assignments to avoid long consecutive streaks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model  # type: ignore[import]

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal, ensure_extra_bucket, register_objective_penalty


SessionMap = Mapping[str, cp_model.IntVar]


@dataclass
class TeacherConsecutiveStats:
	"""Aggregated diagnostics for teacher consecutive lab enforcement."""

	targeted_teachers: set[str] = field(default_factory=set)
	hard_constraints: int = 0
	soft_penalties: int = 0
	penalty_variables: int = 0
	course_clauses: int = 0
	cross_course_clauses: int = 0
	soft_teachers: set[str] = field(default_factory=set)
	hard_teachers: set[str] = field(default_factory=set)
	soft_departments: set[str] = field(default_factory=set)
	hard_departments: set[str] = field(default_factory=set)

	def as_details(self) -> Mapping[str, object]:
		return {
			"targeted_teachers": len(self.targeted_teachers),
			"hard_constraints": self.hard_constraints,
			"soft_penalties": self.soft_penalties,
			"penalty_variables": self.penalty_variables,
			"course_clauses": self.course_clauses,
			"cross_course_clauses": self.cross_course_clauses,
			"soft_teachers": tuple(sorted(self.soft_teachers)),
			"hard_teachers": tuple(sorted(self.hard_teachers)),
			"soft_departments": tuple(sorted(self.soft_departments)),
			"hard_departments": tuple(sorted(self.hard_departments)),
		}


class TeacherMaxConsecutiveLabConstraint(Constraint):
	"""Prevent teachers from having more than the configured consecutive lab sessions."""

	DEFAULT_MAX_CONSECUTIVE = 2
	DEFAULT_SOFT_DEPARTMENTS = ("Biotechnology",)
	DEFAULT_SOFT_PENALTY_WEIGHT = 5
	CACHE_KEY = "teacher_max_consecutive"

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("teacher_max_consecutive")
		lab_block = context.variables.lab
		assignments = lab_block.assignments
		if not assignments:
			logger.info("No lab assignments present; skipping teacher consecutive constraint")
			return self._result(ConstraintStatus.SKIPPED, {})

		session_order = tuple(lab_block.lab_session_names)
		if not session_order:
			logger.info("Lab session catalogue empty; skipping teacher consecutive constraint")
			return self._result(ConstraintStatus.SKIPPED, {})

		max_consecutive = max(1, int(self.params.get("max_consecutive_sessions", self.DEFAULT_MAX_CONSECUTIVE)))
		window = max_consecutive + 1
		if len(session_order) < window:
			logger.info(
				"Only %s lab sessions configured; insufficient to enforce a %s-session window",
				len(session_order),
				window,
			)
			return self._result(ConstraintStatus.SKIPPED, {})

		sequence_templates = tuple(
			session_order[index : index + window] for index in range(len(session_order) - window + 1)
		)

		soft_departments_param = self.params.get("soft_departments")
		if isinstance(soft_departments_param, Sequence):
			soft_departments = {
				str(value).strip().lower()
				for value in soft_departments_param
				if value is not None and str(value).strip()
			}
		else:
			soft_departments = {dept.lower() for dept in self.DEFAULT_SOFT_DEPARTMENTS}

		soft_penalty_weight = int(self.params.get("soft_penalty_weight", self.DEFAULT_SOFT_PENALTY_WEIGHT))

		course_literals, teacher_literals = self._build_presence_literals(context)
		if not course_literals:
			logger.info("Unable to resolve lab session literals; skipping teacher consecutive constraint")
			return self._result(ConstraintStatus.SKIPPED, {})

		teacher_departments = self._map_teacher_departments(lab_block.teacher_courses, lab_block.requirements)

		stats = TeacherConsecutiveStats()
		for teacher_id, course_map in course_literals.items():
			for course_id, day_map in course_map.items():
				requirement = lab_block.requirements.get(course_id)
				if not requirement:
					continue
				dept_name = (requirement.department or "").strip() or "__unknown__"
				is_soft = dept_name.lower() in soft_departments
				if is_soft:
					stats.soft_departments.add(dept_name)
				else:
					stats.hard_departments.add(dept_name)
				for day_idx, session_map in day_map.items():
					self._apply_sequences(
						context,
						sequence_templates,
						session_map,
						stats=stats,
						teacher_id=teacher_id,
						entity_id=course_id,
						scope="course",
						day_index=day_idx,
						is_soft=is_soft,
						penalty_weight=soft_penalty_weight,
					)

		for teacher_id, day_map in teacher_literals.items():
			dept_tokens = teacher_departments.get(teacher_id, set())
			is_soft = bool(dept_tokens and dept_tokens.issubset(soft_departments))
			for day_idx, session_map in day_map.items():
				self._apply_sequences(
					context,
					sequence_templates,
					session_map,
					stats=stats,
					teacher_id=teacher_id,
					entity_id="any",
					scope="cross",
					day_index=day_idx,
					is_soft=is_soft,
					penalty_weight=soft_penalty_weight,
				)

		status = ConstraintStatus.APPLIED if (stats.hard_constraints or stats.soft_penalties) else ConstraintStatus.SKIPPED
		details = dict(stats.as_details())
		details.update(
			{
				"window_length": window,
				"max_consecutive_sessions": max_consecutive,
				"configured_soft_departments": tuple(sorted(soft_departments)),
			}
		)
		return self._result(status, details)

	def _build_presence_literals(
		self,
		context: ConstraintContext,
		cache_key: str = "presence_literals",
	) -> Tuple[
		Mapping[str, Mapping[str, Mapping[int, SessionMap]]],
		Mapping[str, Mapping[int, SessionMap]],
	]:
		cache = ensure_extra_bucket(context, self.CACHE_KEY)
		if cache_key in cache:
			return cache[cache_key]

		model = context.model
		assignments = context.variables.lab.assignments
		course_literals: Dict[str, MutableMapping[str, MutableMapping[int, MutableMapping[str, cp_model.IntVar]]]] = {}
		teacher_terms: Dict[Tuple[str, int, str], list[cp_model.IntVar]] = {}

		for teacher_id, course_map in assignments.items():
			teacher_bucket = course_literals.setdefault(teacher_id, {})
			for course_id, day_map in course_map.items():
				day_bucket = teacher_bucket.setdefault(course_id, {})
				for day_idx, session_map in day_map.items():
					session_bucket = day_bucket.setdefault(day_idx, {})
					for session_name, room_map in session_map.items():
						literal = build_presence_literal(
							model,
							tuple(room_map.values()),
							f"lab_presence_{teacher_id}_{course_id}_d{day_idx}_{session_name}",
						)
						if literal is None:
							continue
						session_bucket[session_name] = literal
						teacher_terms.setdefault((teacher_id, day_idx, session_name), []).append(literal)

		teacher_literals: Dict[str, MutableMapping[int, MutableMapping[str, cp_model.IntVar]]] = {}
		for (teacher_id, day_idx, session_name), literals in teacher_terms.items():
			literal = build_presence_literal(
				model,
				tuple(literals),
				f"teacher_any_course_{teacher_id}_d{day_idx}_{session_name}",
			)
			if literal is None:
				continue
			day_bucket = teacher_literals.setdefault(teacher_id, {})
			day_bucket.setdefault(day_idx, {})[session_name] = literal

		cache[cache_key] = (course_literals, teacher_literals)
		return course_literals, teacher_literals

	@staticmethod
	def _map_teacher_departments(
		teacher_courses: Mapping[str, Sequence[str]],
		requirements: Mapping[str, object],
	) -> Mapping[str, set[str]]:
		mapping: Dict[str, set[str]] = {}
		for teacher_id, courses in teacher_courses.items():
			bucket: set[str] = set()
			for course_id in courses:
				requirement = requirements.get(course_id)
				if not requirement:
					continue
				dept = getattr(requirement, "department", None)
				if dept:
					bucket.add(str(dept).strip().lower())
			if bucket:
				mapping[teacher_id] = bucket
		return mapping

	def _apply_sequences(
		self,
		context: ConstraintContext,
		sequences: Sequence[Sequence[str]],
		session_map: Mapping[str, cp_model.IntVar],
		*,
		stats: TeacherConsecutiveStats,
		teacher_id: str,
		entity_id: str,
		scope: str,
		day_index: int,
		is_soft: bool,
		penalty_weight: int,
	) -> None:
		model = context.model
		applied = False
		for sequence in sequences:
			literals = [session_map.get(name) for name in sequence]
			if any(literal is None for literal in literals):
				continue
			sequence_literals = [literal for literal in literals if literal is not None]
			if not sequence_literals:
				continue
			sequence_label = "_".join(sequence)
			if is_soft:
				violation = model.NewBoolVar(
					f"teacher_consecutive_soft_{scope}_{teacher_id}_{entity_id}_d{day_index}_{sequence_label}"
				)
				model.Add(sum(sequence_literals) >= len(sequence)).OnlyEnforceIf(violation)
				model.Add(sum(sequence_literals) <= len(sequence) - 1).OnlyEnforceIf(violation.Not())
				register_objective_penalty(
					context,
					violation,
					weight=penalty_weight,
					tag=f"teacher_spread:max_consecutive:{scope}:{teacher_id}:{entity_id}:d{day_index}",
				)
				stats.soft_penalties += 1
				stats.penalty_variables += 1
				stats.soft_teachers.add(teacher_id)
			else:
				model.Add(sum(sequence_literals) <= len(sequence) - 1)
				stats.hard_constraints += 1
				stats.hard_teachers.add(teacher_id)
			applied = True
			if scope == "course":
				stats.course_clauses += 1
			else:
				stats.cross_course_clauses += 1

		if applied:
			stats.targeted_teachers.add(teacher_id)

	def _result(self, status: str, details: Mapping[str, object]) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=dict(details),
		)


def build_teacher_max_consecutive_lab_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TeacherMaxConsecutiveLabConstraint:
	return TeacherMaxConsecutiveLabConstraint(metadata=metadata, params=params or {})


__all__ = [
	"TeacherMaxConsecutiveLabConstraint",
	"build_teacher_max_consecutive_lab_constraint",
]