"""Enforce consecutive lab sessions for targeted course codes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import build_presence_literal


def _normalise_code(value: Optional[str]) -> str:
	return str(value or "").strip().upper()


@dataclass(frozen=True)
class ConsecutiveBatchConfig:
	"""Payload describing which courses require consecutive lab batches."""

	course_codes: Tuple[str, ...]
	preferred_pairs: Tuple[Tuple[str, str], ...]
	min_practical_hours: int
	min_student_count: int

	@staticmethod
	def from_params(params: Optional[Mapping[str, object]]) -> "ConsecutiveBatchConfig":
		params = params or {}
		code_bucket = []
		seen = set()
		for raw_code in params.get("course_codes", tuple()):
			normalised = _normalise_code(raw_code)
			if not normalised or normalised in seen:
				continue
			seen.add(normalised)
			code_bucket.append(normalised)
		pairs_payload = params.get("preferred_pairs") or (
			("L1", "L2"),
			("L3", "L4"),
			("L5", "L6"),
		)
		pairs: list[Tuple[str, str]] = []
		for entry in pairs_payload:
			if not isinstance(entry, Sequence) or len(entry) != 2:
				continue
			first = _normalise_code(entry[0])
			second = _normalise_code(entry[1])
			if first and second:
				pairs.append((first, second))
		if not pairs:
			pairs = [("L1", "L2")]
		min_hours = max(1, int(params.get("min_practical_hours", 4)))
		min_students = max(1, int(params.get("min_student_count", 36)))
		return ConsecutiveBatchConfig(
			course_codes=tuple(code_bucket),
			preferred_pairs=tuple(pairs),
			min_practical_hours=min_hours,
			min_student_count=min_students,
		)


@dataclass
class ConsecutiveBatchStats:
	targeted_courses: set[str] = field(default_factory=set)
	constraints_added: int = 0
	skipped_courses: int = 0

	def as_details(self) -> Mapping[str, object]:
		return {
			"targeted_courses": tuple(sorted(self.targeted_courses)),
			"constraints_added": self.constraints_added,
			"skipped_courses": self.skipped_courses,
		}


class ConsecutiveBatchLabConstraint(Constraint):
	"""Ensure configured course codes occupy paired lab sessions per day."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		config = ConsecutiveBatchConfig.from_params(self.params)
		if not config.course_codes:
			return self._skip("no course codes configured")

		lab_block = context.variables.lab
		assignments = lab_block.assignments
		if not assignments:
			return self._skip("no lab assignments present")

		stats = ConsecutiveBatchStats()
		model = context.model

		for teacher_id, course_map in assignments.items():
			for course_id, day_map in course_map.items():
				requirement = lab_block.requirements.get(course_id)
				if requirement is None:
					continue
				course_code = _normalise_code(requirement.course_code)
				if course_code not in config.course_codes:
					continue
				should_enforce = (
					requirement.practical_hours >= config.min_practical_hours
					or requirement.student_count >= config.min_student_count
				)
				if not should_enforce:
					stats.skipped_courses += 1
					continue
				stats.targeted_courses.add(course_code)

				for day_idx, session_map in day_map.items():
					self._apply_day_pairs(
						model,
						course_id,
						day_idx,
						session_map,
						config.preferred_pairs,
						stats,
					)

		status = ConstraintStatus.APPLIED if stats.constraints_added else ConstraintStatus.SKIPPED
		details = stats.as_details()
		details.update(
			{
				"min_practical_hours": config.min_practical_hours,
				"min_student_count": config.min_student_count,
				"preferred_pairs": config.preferred_pairs,
			}
		)
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=details,
		)

	def _apply_day_pairs(
		self,
		model: cp_model.CpModel,
		course_id: str,
		day_idx: int,
		session_map: Mapping[str, Mapping[str, cp_model.IntVar]],
		pairs: Sequence[Tuple[str, str]],
		stats: ConsecutiveBatchStats,
	) -> None:
		allowed_sessions = {session for pair in pairs for session in pair}
		# Targeted courses may use only complete configured pairs.  Previously an
		# L3 placement (or a lone L1/L5 when its partner map was empty) escaped all
		# equalities and silently violated the consecutive-batch requirement.
		for session_name, room_map in session_map.items():
			if session_name in allowed_sessions or not room_map:
				continue
			literal = build_presence_literal(
				model,
				tuple(room_map.values()),
				f"consec_{course_id}_d{day_idx}_{session_name}_blocked",
			)
			if literal is not None:
				model.Add(literal == 0)
				stats.constraints_added += 1

		for first_session, second_session in pairs:
			first_rooms = session_map.get(first_session)
			second_rooms = session_map.get(second_session)
			if not first_rooms and not second_rooms:
				continue
			literal_first = (
				build_presence_literal(
					model,
					tuple(first_rooms.values()),
					f"consec_{course_id}_d{day_idx}_{first_session}",
				)
				if first_rooms
				else None
			)
			literal_second = (
				build_presence_literal(
					model,
					tuple(second_rooms.values()),
					f"consec_{course_id}_d{day_idx}_{second_session}",
				)
				if second_rooms
				else None
			)
			if literal_first is not None and literal_second is not None:
				model.Add(literal_first == literal_second)
			elif literal_first is not None:
				model.Add(literal_first == 0)
			elif literal_second is not None:
				model.Add(literal_second == 0)
			else:
				continue
			stats.constraints_added += 1

	def _skip(self, reason: str) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=ConstraintStatus.SKIPPED,
			details={"reason": reason},
		)


def build_consecutive_batch_lab_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> ConsecutiveBatchLabConstraint:
	return ConsecutiveBatchLabConstraint(metadata=metadata, params=params)


__all__ = [
	"ConsecutiveBatchLabConstraint",
	"build_consecutive_batch_lab_constraint",
]
