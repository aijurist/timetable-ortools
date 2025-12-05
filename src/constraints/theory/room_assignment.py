"""Theory classroom assignment constraint covering block policies and room tiering."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_theory_room_variables, register_objective_penalty
from ...utils.time_utils import DayNormalizer


@dataclass(frozen=True)
class RoomInventory:
	block_capacity: Mapping[str, int]
	big_block_capacity: Mapping[str, int]
	small_block_capacity: Mapping[str, int]
	blocks: Tuple[str, ...]
	total_rooms: int
	rooms_by_block: Mapping[str, Tuple[Mapping[str, object], ...]]
	room_index: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True)
class CoursePolicy:
	allowed_blocks: Tuple[str, ...]
	primary_block: Optional[str]
	is_big_course: bool
	allowed_rooms: Tuple[str, ...]


class TheoryClassroomAssignmentConstraint(Constraint):
	"""Assign theory sessions to block buckets while honoring 140-capacity prioritisation."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		settings = dict(params or {})
		self._big_threshold = max(1, int(settings.get("big_capacity_threshold", 140)))
		self._overflow_penalty = max(0, int(settings.get("overflow_penalty", 5)))
		self._utilization_penalty = max(0, int(settings.get("utilization_penalty", 10)))
		self._default_blocks = self._normalise_block_list(settings.get("default_blocks") or ("A Block", "B Block", "C Block"))
		self._senior_blocks = self._normalise_block_list(settings.get("senior_blocks") or ("A Block", "B Block"))
		self._second_year_blocks = self._normalise_block_list(settings.get("second_year_blocks") or ("B Block", "C Block"))
		self._year_block_preferences = self._build_year_block_preferences(settings.get("year_block_preferences"))

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		inventory = self._build_inventory(context)
		theory_block = context.variables.theory
		if inventory.total_rooms == 0 or not getattr(theory_block, "course_requirements", {}):
			return self._result(ConstraintStatus.SKIPPED, {"reason": "no_theory_rooms"})

		course_policies = self._build_course_policies(theory_block.course_requirements, inventory)
		if not course_policies:
			return self._result(ConstraintStatus.SKIPPED, {"reason": "no_course_policies"})

		stats = self._assign_blocks(context, course_policies, inventory)
		status = ConstraintStatus.APPLIED if any(
			stats[key] for key in ("active_literals", "room_conflict_constraints", "penalties", "disabled_literals")
		) else ConstraintStatus.SKIPPED
		return self._result(status, {
			"rooms": inventory.total_rooms,
			"blocks": len(inventory.blocks),
			"enabled_literals": stats["active_literals"],
			"disabled_literals": stats["disabled_literals"],
			"room_conflict_constraints": stats["room_conflict_constraints"],
			"overflow_penalties": stats["penalties"],
		})

	def _assign_blocks(
		self,
		context: ConstraintContext,
		course_policies: Mapping[str, CoursePolicy],
		inventory: RoomInventory,
	) -> Mapping[str, int]:
		model = context.model
		theory_block = context.variables.theory
		room_lookup = inventory.room_index
		# Store (course_id, var) tuples to allow grouping by course code later
		room_slot_usage: MutableMapping[Tuple[str, str, int], list[Tuple[str, cp_model.IntVar]]] = defaultdict(list)
		stats = {
			"active_literals": 0,
			"disabled_literals": 0,
			"room_conflict_constraints": 0,
			"penalties": 0,
		}
		course_day_patterns = getattr(theory_block, "course_day_patterns", {}) or {}
		time_config = getattr(context.data.raw, "time", None)
		working_days = getattr(time_config, "working_days", tuple()) or tuple()
		default_day_pattern = self._canonical_day_pattern(working_days)
		if not default_day_pattern:
			fallback_range = range(len(working_days)) if working_days else (0,)
			default_day_pattern = tuple(f"day_{idx}" for idx in fallback_range)
		pattern_cache: Dict[str, Tuple[str, ...]] = {}
		day_key_cache: Dict[Tuple[str, int], str] = {}

		for _tid, course_id, day_idx, slot_idx, room_id, var in iter_theory_room_variables(context):
			policy = course_policies.get(course_id)
			room_meta = room_lookup.get(str(room_id))
			if (
				not policy
				or not policy.allowed_rooms
				or room_meta is None
				or str(room_id) not in policy.allowed_rooms
			):
				model.Add(var == 0)
				stats["disabled_literals"] += 1
				continue
			
			# Strict capacity check for large courses is handled in _build_course_policies via allowed_rooms
			# But we keep a safety check here if needed, though policy.allowed_rooms should cover it.
			
			stats["active_literals"] += 1
			day_key = self._resolve_day_key(
				course_id,
				day_idx,
				course_day_patterns,
				default_day_pattern,
				pattern_cache,
				day_key_cache,
			)
			room_slot_usage[(str(room_id), day_key, slot_idx)].append((course_id, var))
			block = room_meta.get("block") or room_meta.get("Block") or room_meta.get("building")
			block_label = self._normalise_block(block)
			if self._overflow_penalty and policy.primary_block and block_label != policy.primary_block:
				register_objective_penalty(
					context,
					var,
					weight=self._overflow_penalty,
					tag="room_spread:block_overflow",
				)
				stats["penalties"] += 1

		for (room_id, _day, _slot), usage_list in room_slot_usage.items():
			if len(usage_list) <= 1:
				continue

			room_meta = room_lookup.get(room_id, {})
			capacity = self._safe_int(room_meta.get("capacity"))
			
			# Determine co-scheduling limit based on capacity
			limit = 1
			if capacity is not None:
				if capacity >= 300:
					limit = 5
				elif capacity >= 170:
					limit = 3
				elif capacity >= 130:
					limit = 2
			
			if limit == 1:
				# Standard strict single assignment
				vars_only = [v for _, v in usage_list]
				model.Add(sum(vars_only) <= 1)
				stats["room_conflict_constraints"] += 1
			else:
				# Co-scheduling allowed for same course code
				# Group vars by course code
				by_code: DefaultDict[str, list[cp_model.IntVar]] = defaultdict(list)
				for cid, var in usage_list:
					# Try to get course code from requirements, fallback to parsing ID
					req = theory_block.course_requirements.get(cid)
					code = getattr(req, "course_code", None)
					if not code:
						code = cid.split('_')[0]
					by_code[code].append(var)
				
				# If multiple codes present, enforce mutual exclusion
				if len(by_code) > 1:
					active_indicators = []
					for code, vars_for_code in by_code.items():
						is_active = model.NewBoolVar(f"active_{room_id}_{_day}_{_slot}_{code}")
						active_indicators.append(is_active)
						# If active, sum <= limit. If not active, sum == 0.
						model.Add(sum(vars_for_code) <= limit * is_active)
						
						# Maximise usage: if active, prefer filling up to limit
						if self._utilization_penalty > 0:
							# Penalty = P * (limit * is_active - sum(vars_for_code))
							# Decomposed: P*limit*is_active (penalty) + P*sum(vars) (reward / negative penalty)
							register_objective_penalty(
								context,
								is_active,
								weight=limit * self._utilization_penalty,
								tag="room_utilization:active_cost"
							)
							for v in vars_for_code:
								register_objective_penalty(
									context,
									v,
									weight=-self._utilization_penalty,
									tag="room_utilization:fill_reward"
								)
					
					# Only one code can be active
					model.Add(sum(active_indicators) <= 1)
				else:
					# Only one code exists, just limit the count
					vars_only = [v for _, v in usage_list]
					model.Add(sum(vars_only) <= limit)
					
					# Maximise usage: if used, prefer filling up to limit
					if self._utilization_penalty > 0:
						room_used = model.NewBoolVar(f"used_{room_id}_{_day}_{_slot}")
						model.Add(sum(vars_only) > 0).OnlyEnforceIf(room_used)
						model.Add(sum(vars_only) == 0).OnlyEnforceIf(room_used.Not())
						
						register_objective_penalty(
							context,
							room_used,
							weight=limit * self._utilization_penalty,
							tag="room_utilization:active_cost"
						)
						for v in vars_only:
							register_objective_penalty(
								context,
								v,
								weight=-self._utilization_penalty,
								tag="room_utilization:fill_reward"
							)
				
				stats["room_conflict_constraints"] += 1

		return stats


	def _build_course_policies(
		self,
		course_requirements: Mapping[str, object],
		inventory: RoomInventory,
	) -> Mapping[str, CoursePolicy]:
		policies: Dict[str, CoursePolicy] = {}
		for course_id, requirement in course_requirements.items():
			semester = getattr(requirement, "semester", None)
			student_count = getattr(requirement, "student_count", 0) or 0
			allowed = self._resolve_allowed_blocks(semester, inventory)
			if not allowed:
				continue
			
			# Determine tier
			is_big = student_count >= self._big_threshold
			min_cap_needed = 0
			specific_tier_rooms = None

			if student_count > 210:
				min_cap_needed = student_count
				specific_tier_rooms = {"225"} # ANEW201
			elif student_count > 165:
				min_cap_needed = student_count
				specific_tier_rooms = {"221", "222"} # ANEW101, ANEW102
			elif student_count > 130:
				min_cap_needed = student_count
				specific_tier_rooms = {"223", "224", "220", "3"} # ANEW103, ANEW104, KSL02, A104/105
			elif student_count >= 115:
				min_cap_needed = 140 # Force large room for 120-student case
				specific_tier_rooms = {"223", "224", "220", "3"} # Same set as > 130
			
			primary = self._resolve_primary_block(semester, allowed)
			candidate_rooms: list[str] = []
			for block in allowed:
				for room in inventory.rooms_by_block.get(block, tuple()):
					room_id = str(room.get("room_id")) if isinstance(room, Mapping) else None
					if room_id:
						candidate_rooms.append(room_id)
			if not candidate_rooms:
				candidate_rooms = list(inventory.room_index.keys())
			
			filtered_rooms: Tuple[str, ...]
			if min_cap_needed > 0:
				# Strict filtering for large courses
				# For large courses, we ignore block restrictions if needed to find a room
				# Search ALL rooms in inventory, not just candidate_rooms (which are block-restricted)
				all_rooms = list(inventory.room_index.keys())
				sized = [
					room_id
					for room_id in all_rooms
					if self._safe_int(inventory.room_index.get(room_id, {}).get("capacity"))
					and self._safe_int(inventory.room_index.get(room_id, {}).get("capacity")) >= min_cap_needed
				]
				
				if specific_tier_rooms:
					tier_matches = [r for r in sized if r in specific_tier_rooms]
					if tier_matches:
						filtered_rooms = tuple(tier_matches)
					else:
						# Fallback if specific rooms don't fit capacity or are missing
						filtered_rooms = tuple(sized)
				else:
					filtered_rooms = tuple(sized)
			elif is_big:
				# Legacy big threshold check (>= 140 default)
				sized = tuple(
					room_id
					for room_id in candidate_rooms
					if self._safe_int(inventory.room_index.get(room_id, {}).get("capacity"))
					and self._safe_int(inventory.room_index.get(room_id, {}).get("capacity")) >= self._big_threshold
				)
				# STRICT: Do not fallback
				filtered_rooms = sized
			else:
				# Small courses: prefer small rooms, but allow large rooms for co-scheduling
				# We include:
				# 1. Candidate rooms (block-restricted) that are small (< big_threshold)
				# 2. ANY room that is large enough to support co-scheduling (>= 130), regardless of block
				
				all_rooms = list(inventory.room_index.keys())
				
				small_candidates = [
					room_id for room_id in candidate_rooms
					if self._safe_int(inventory.room_index.get(room_id, {}).get("capacity")) is None
					or self._safe_int(inventory.room_index.get(room_id, {}).get("capacity")) < self._big_threshold
				]
				
				large_co_schedulable = [
					room_id for room_id in all_rooms
					if self._safe_int(inventory.room_index.get(room_id, {}).get("capacity"))
					and self._safe_int(inventory.room_index.get(room_id, {}).get("capacity")) >= 130
				]
				
				filtered_rooms = tuple(set(small_candidates + large_co_schedulable))
			
			policies[course_id] = CoursePolicy(
				allowed_blocks=allowed,
				primary_block=primary,
				is_big_course=is_big,
				allowed_rooms=filtered_rooms,
			)
		return policies

	def _resolve_day_key(
		self,
		course_id: str,
		day_index: int,
		course_day_patterns: Mapping[str, Sequence[object]],
		default_day_pattern: Tuple[str, ...],
		pattern_cache: MutableMapping[str, Tuple[str, ...]],
		day_key_cache: MutableMapping[Tuple[str, int], str],
	) -> str:
		cache_key = (course_id, day_index)
		if cache_key in day_key_cache:
			return day_key_cache[cache_key]
		pattern = pattern_cache.get(course_id)
		if pattern is None:
			raw_pattern = course_day_patterns.get(course_id)
			pattern = self._canonical_day_pattern(raw_pattern) or default_day_pattern
			pattern_cache[course_id] = pattern
		if pattern:
			label = pattern[day_index % len(pattern)]
		else:
			label = f"day_{day_index}"
		day_label = DayNormalizer.normalize_day_name(label) or label
		day_key_cache[cache_key] = day_label
		return day_label

	def _canonical_day_pattern(self, raw_pattern: Optional[Iterable[object]]) -> Tuple[str, ...]:
		if not raw_pattern:
			return tuple()
		seen = set()
		ordered: list[str] = []
		for value in raw_pattern:
			if value is None:
				continue
			text = str(value).strip()
			if not text:
				continue
			label = DayNormalizer.normalize_day_name(text)
			if not label:
				label = text.lower()
			if not label or label in seen:
				continue
			seen.add(label)
			ordered.append(label)
		return tuple(ordered)

	def _build_inventory(self, context: ConstraintContext) -> RoomInventory:
		rooms_payload = getattr(context.data.raw, "rooms", None)
		room_registry = getattr(context.data.raw, "room_registry", None) or {}
		if not rooms_payload:
			return RoomInventory({}, {}, {}, tuple(), 0, {}, {})
		theory_room_ids = tuple(getattr(rooms_payload, "theory_room_ids", tuple()) or tuple())
		if not theory_room_ids:
			return RoomInventory({}, {}, {}, tuple(), 0, {}, {})

		block_capacity: Dict[str, int] = {}
		big_capacity: Dict[str, int] = {}
		small_capacity: Dict[str, int] = {}
		room_details: Dict[str, list[Mapping[str, object]]] = defaultdict(list)
		room_lookup: Dict[str, Mapping[str, object]] = {}
		total = 0

		for room_id in theory_room_ids:
			meta = room_registry.get(room_id)
			if not isinstance(meta, Mapping):
				continue
			block = self._normalise_block(meta.get("block") or meta.get("Block") or meta.get("building"))
			capacity = self._safe_int(
				meta.get("room_max_cap")
				or meta.get("capacity")
				or meta.get("room_capacity")
				or meta.get("max_capacity")
			)
			if capacity is None or capacity <= 0:
				continue
			total += 1
			block_capacity[block] = block_capacity.get(block, 0) + 1
			if capacity >= self._big_threshold:
				big_capacity[block] = big_capacity.get(block, 0) + 1
			else:
				small_capacity[block] = small_capacity.get(block, 0) + 1
			room_payload = {
				"room_id": str(room_id),
				"room_number": self._coalesce_room_number(meta, room_id),
				"capacity": capacity,
				"block": block,
				"metadata": dict(meta),
			}
			room_details[block].append(room_payload)
			room_lookup[str(room_id)] = room_payload

		for block, count in block_capacity.items():
			small_capacity.setdefault(block, max(0, count - big_capacity.get(block, 0)))
			big_capacity.setdefault(block, big_capacity.get(block, 0))

		return RoomInventory(
			block_capacity=block_capacity,
			big_block_capacity=big_capacity,
			small_block_capacity=small_capacity,
			blocks=tuple(block_capacity.keys()),
			total_rooms=total,
			rooms_by_block={block: tuple(details) for block, details in room_details.items()},
			room_index=room_lookup,
		)

	def _resolve_allowed_blocks(self, semester: Optional[int], inventory: RoomInventory) -> Tuple[str, ...]:
		if not inventory.blocks:
			return tuple()
		candidate = self._default_blocks
		if semester is not None:
			if semester >= 5:
				candidate = self._senior_blocks or candidate
			elif semester in (3, 4):
				candidate = self._second_year_blocks or candidate
		allowed = tuple(block for block in candidate if block in inventory.block_capacity)
		if allowed:
			return allowed
		return inventory.blocks

	def _resolve_primary_block(self, semester: Optional[int], allowed: Sequence[str]) -> Optional[str]:
		year = self._semester_to_year(semester)
		preference_order: list[Tuple[str, ...]] = []
		if year is not None:
			year_prefs = self._year_block_preferences.get(year)
			if year_prefs:
				preference_order.append(year_prefs)
		if semester is not None:
			if semester >= 5:
				preference_order.append(self._senior_blocks)
			elif semester in (3, 4):
				preference_order.append(self._second_year_blocks)
		for block_list in preference_order:
			block = self._first_available_block(block_list, allowed)
			if block:
				return block
		return None

	@staticmethod
	def _first_available_block(candidates: Sequence[str], allowed: Sequence[str]) -> Optional[str]:
		if not candidates or not allowed:
			return None
		allowed_set = set(allowed)
		for block in candidates:
			if block in allowed_set:
				return block
		return None

	def _result(self, status: str, details: Mapping[str, object]) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=dict(details),
		)

	@staticmethod
	def _normalise_block(value: object) -> str:
		if value is None:
			return "Unknown Block"
		text = str(value).strip()
		if not text:
			return "Unknown Block"
		upper = text.upper()
		mapping = {
			"A": "A Block",
			"A BLOCK": "A Block",
			"BLOCK A": "A Block",
			"ADMIN": "A Block",
			"ADMIN BLOCK": "A Block",
			"B": "B Block",
			"B BLOCK": "B Block",
			"BLOCK B": "B Block",
			"C": "C Block",
			"C BLOCK": "C Block",
			"BLOCK C": "C Block",
		}
		if upper in mapping:
			return mapping[upper]
		if upper.startswith("A"):
			return "A Block"
		if upper.startswith("B"):
			return "B Block"
		if upper.startswith("C"):
			return "C Block"
		return text.title()

	@staticmethod
	def _normalise_block_list(values: Iterable[object]) -> Tuple[str, ...]:
		seen = set()
		result = []
		for value in values:
			block = TheoryClassroomAssignmentConstraint._normalise_block(value)
			if block in seen:
				continue
			seen.add(block)
			result.append(block)
		return tuple(result)

	def _build_year_block_preferences(self, raw_preferences: Optional[Mapping[object, object]]) -> Mapping[int, Tuple[str, ...]]:
		defaults = {
			2: ("B Block",),
			3: ("A Block",),
			4: ("A Block",),
		}
		if not raw_preferences:
			return defaults
		preferences = dict(defaults)
		for year_key, blocks in raw_preferences.items():
			try:
				year = int(year_key)
			except (TypeError, ValueError):
				continue
			candidate_blocks: Tuple[str, ...]
			if isinstance(blocks, str):
				candidate_blocks = self._normalise_block_list((blocks,))
			else:
				candidate_blocks = self._normalise_block_list(blocks)
			if candidate_blocks:
				preferences[year] = candidate_blocks
		return preferences

	@staticmethod
	def _semester_to_year(semester: Optional[int]) -> Optional[int]:
		if semester is None:
			return None
		try:
			value = int(semester)
		except (TypeError, ValueError):
			return None
		if value <= 0:
			return None
		return (value + 1) // 2

	@staticmethod
	def _safe_int(value: object) -> Optional[int]:
		if value is None:
			return None
		try:
			return int(round(float(value)))
		except (TypeError, ValueError):
			return None

	@staticmethod
	def _coalesce_room_number(metadata: Mapping[str, object], room_id: object) -> str:
		candidates = ("room_number", "room_no", "name", "RoomNumber")
		for key in candidates:
			value = metadata.get(key) if isinstance(metadata, Mapping) else None
			if value:
				text = str(value).strip()
				if text:
					return text
		return str(room_id)

	@staticmethod
	def _slug(block: str) -> str:
		return block.lower().replace(" ", "_")


def build_theory_room_assignment_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> TheoryClassroomAssignmentConstraint:
	return TheoryClassroomAssignmentConstraint(metadata=metadata, params=params)


__all__ = [
	"TheoryClassroomAssignmentConstraint",
	"build_theory_room_assignment_constraint",
]
