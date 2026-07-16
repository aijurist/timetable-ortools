"""Bundled theory constraint for section-based cohorts (2nd year).

Two theory courses of an eligible cohort may share a single 50-minute slot, split
25min + 25min ("bundling"). The solver decides which courses pair, subject to:

* courses with different teachers may pair; unequal theory loads share as many
  25-minute halves as possible and leave the longer course a full-slot remainder;
* a bundled course needs twice as many slot appearances (the 8-half-slot rule);
* a bundled pair is co-scheduled (same day/slot) and shares one room;
* pairing is maximum-cardinality over the feasible course graph (so an even
  section has no singleton whenever a perfect matching exists);
* among maximum-cardinality matchings, courses with equal or near-equal theory
  loads are preferred.

Cohort-level exclusivity (a bundled pair counting as one occupancy) is enforced in
:mod:`group_non_overlap`, which reads the pairing variables this constraint stores
under ``context.extra["bundles"]``. This constraint therefore runs early (low
priority number) so those variables exist before group non-overlap is applied.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
	bundle_eligible_cohorts,
	is_bundle_eligible,
	iter_course_timeslot_variables,
	iter_theory_room_variables,
	register_objective_penalty,
)
from ...data.pop_availability import normalize_teacher_id

CohortKey = Tuple[str, Optional[int], Optional[int]]
SlotKey = Tuple[int, int]
CourseCodePair = Tuple[str, str]


def _sanitize(value: object) -> str:
	return re.sub(r"[^0-9A-Za-z]+", "_", str(value)).strip("_") or "x"


def _same_teacher_id(first: object, second: object) -> bool:
	return normalize_teacher_id(first) == normalize_teacher_id(second)


def _maximum_matching_size(vertex_count: int, edges: Mapping[Tuple[int, int], object]) -> int:
	"""Return the exact maximum-cardinality matching size for a small section graph.

	Second-year sections have only a handful of theory offerings, so a memoized
	bit-mask search is both faster and more deterministic than starting a nested
	CP-SAT solve while the main model is being built.  The result is used only as a
	hard cardinality target; the main solver still chooses *which* maximum matching
	fits rooms, staff availability, POP windows, and the fixed schedule.
	"""

	if vertex_count < 2 or not edges:
		return 0
	adjacency = [0] * vertex_count
	for raw_a, raw_b in edges:
		a, b = int(raw_a), int(raw_b)
		if a == b or a < 0 or b < 0 or a >= vertex_count or b >= vertex_count:
			continue
		adjacency[a] |= 1 << b
		adjacency[b] |= 1 << a

	cache: Dict[int, int] = {0: 0}

	def solve(mask: int) -> int:
		cached = cache.get(mask)
		if cached is not None:
			return cached
		first_bit = mask & -mask
		first = first_bit.bit_length() - 1
		rest = mask ^ first_bit
		best = solve(rest)  # leave ``first`` unmatched when the graph requires it
		partners = adjacency[first] & rest
		while partners:
			partner_bit = partners & -partners
			best = max(best, 1 + solve(rest ^ partner_bit))
			partners ^= partner_bit
		cache[mask] = best
		return best

	return solve((1 << vertex_count) - 1)


def _configured_forced_course_pairs(
	payload: object,
	*,
	department: object,
	section_id: object,
) -> Optional[Tuple[CourseCodePair, ...]]:
	"""Return the audited course-code pairs for one department section, if any."""

	if not isinstance(payload, Mapping):
		return None
	department_key = str(department or "").strip().casefold()
	department_payload = next(
		(
			value
			for key, value in payload.items()
			if str(key or "").strip().casefold() == department_key
		),
		None,
	)
	if department_payload is None:
		return None
	if isinstance(department_payload, Mapping):
		section_key = str(section_id)
		raw_pairs = department_payload.get(section_key)
		if raw_pairs is None:
			raw_pairs = department_payload.get("*")
	else:
		raw_pairs = department_payload
	if raw_pairs is None:
		return None

	result: List[CourseCodePair] = []
	for raw_pair in raw_pairs:
		if not isinstance(raw_pair, (list, tuple)) or len(raw_pair) != 2:
			raise ValueError(
				f"Invalid certified Kutty pair for {department!r}/section {section_id!r}: "
				f"{raw_pair!r}"
			)
		left = str(raw_pair[0]).strip().upper()
		right = str(raw_pair[1]).strip().upper()
		if not left or not right or left == right:
			raise ValueError(
				f"Invalid certified Kutty course codes for {department!r}/section "
				f"{section_id!r}: {raw_pair!r}"
			)
		result.append((left, right))
	return tuple(result)


def _resolve_forced_pair_edges(
	courses: List[Tuple[str, object]],
	pair_vars: Mapping[Tuple[int, int], object],
	configured_pairs: Tuple[CourseCodePair, ...],
	*,
	cohort_key: CohortKey,
) -> frozenset[Tuple[int, int]]:
	"""Map audited course-code pairs to candidate graph edges and reject data drift."""

	indices_by_code: Dict[str, List[int]] = defaultdict(list)
	for index, (_course_id, requirement) in enumerate(courses):
		code = str(getattr(requirement, "course_code", "")).strip().upper()
		indices_by_code[code].append(index)

	selected: set[Tuple[int, int]] = set()
	used_indices: set[int] = set()
	for left_code, right_code in configured_pairs:
		left_indices = indices_by_code.get(left_code, [])
		right_indices = indices_by_code.get(right_code, [])
		if len(left_indices) != 1 or len(right_indices) != 1:
			raise ValueError(
				f"Certified Kutty pair {left_code}+{right_code} does not uniquely match "
				f"cohort {cohort_key!r}"
			)
		left, right = left_indices[0], right_indices[0]
		if left in used_indices or right in used_indices:
			raise ValueError(
				f"Certified Kutty pair reuses a course in cohort {cohort_key!r}: "
				f"{left_code}+{right_code}"
			)
		edge = (left, right) if left < right else (right, left)
		if edge not in pair_vars:
			raise ValueError(
				f"Certified Kutty pair is not staff/load compatible in cohort "
				f"{cohort_key!r}: {left_code}+{right_code}"
			)
		selected.add(edge)
		used_indices.update((left, right))
	return frozenset(selected)


def _forced_solo_indices_for_odd_cohort(
	courses: List[Tuple[str, object]],
	*,
	course_codes: object = (),
	course_prefixes: object = (),
) -> frozenset[int]:
	"""Choose the configured subject that must remain full-slot in an odd cohort.

	The course stays inside the bundled-theory coverage owner; only its pairing edges
	are removed.  This is important because excluding it from ``cohort_courses`` would
	also bypass the ordinary theory coverage constraint for bundle-eligible cohorts.
	"""

	if len(courses) % 2 == 0:
		return frozenset()
	explicit_codes = {
		str(code).strip().upper()
		for code in (course_codes or ())
		if str(code).strip()
	}
	prefixes = tuple(
		str(prefix).strip().upper()
		for prefix in (course_prefixes or ())
		if str(prefix).strip()
	)
	candidates: List[Tuple[int, str, str, int]] = []
	for index, (course_id, requirement) in enumerate(courses):
		code = str(getattr(requirement, "course_code", "")).strip().upper()
		if code in explicit_codes:
			candidates.append((0, code, str(course_id), index))
		elif prefixes and code.startswith(prefixes):
			candidates.append((1, code, str(course_id), index))
	if not candidates:
		return frozenset()
	# Exact-code exceptions (for example CSBS CB23331) outrank prefix matches.
	return frozenset({min(candidates)[3]})


class BundledTheoryConstraint(Constraint):
	"""Create bundle decision variables and their coupling constraints."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		theory_block = context.variables.theory
		if not bundle_eligible_cohorts(context.config):
			return self._skip("no eligible cohorts configured")

		force_maximal = bool(self.params.get("force_maximal_pairing", True))
		solo_penalty = int(self.params.get("solo_penalty_weight", 10) or 0)
		load_gap_penalty = int(self.params.get("pair_load_gap_penalty_weight", 5) or 0)
		enforce_shared_room = bool(self.params.get("enforce_shared_room", True))
		hint_pairing = bool(self.params.get("hint_maximal_pairing", True))
		# Partial (per-slot) pairing: two courses of UNEQUAL required hours may still
		# bundle their overlapping hours (min of the two); the longer course's extra
		# hour(s) schedule solo. Off by default -> only equal-hour pairs bundle.
		allow_partial = bool(self.params.get("allow_partial_pairing", False))
		odd_solo_codes = self.params.get("odd_cohort_forced_solo_course_codes", ())
		odd_solo_prefixes = self.params.get("odd_cohort_forced_solo_course_prefixes", ())
		forced_pairs_payload = self.params.get("forced_course_pairs_by_department", {})

		# Combined lab-block courses are individual (never bundled) — exclude their codes.
		combined_cfg = getattr(getattr(context.config, "model", None), "combined_lab_courses", {}) or {}
		combined_codes = frozenset(
			str(c).strip().upper() for c in combined_cfg.get("course_codes", ()) if str(c).strip()
		)

		# Group eligible theory courses by cohort. For section-based cohorts the cohort is a
		# single SECTION (department, semester, section_id); pairing happens inside a section.
		cohort_courses: Dict[CohortKey, List[Tuple[str, object]]] = defaultdict(list)
		for course_id, requirement in theory_block.course_requirements.items():
			department = getattr(requirement, "department", None)
			semester = getattr(requirement, "semester", None)
			section_id = getattr(requirement, "section_id", None)
			if str(getattr(requirement, "course_code", "")).strip().upper() in combined_codes:
				continue
			if is_bundle_eligible(context.config, department, semester):
				cohort_courses[
					(department, int(semester) if semester is not None else None, section_id)
				].append((course_id, requirement))

		bundles_store: Dict[CohortKey, Dict[str, object]] = {}
		total_pairs = 0
		total_courses = 0
		cohorts_done = 0
		forced_pair_count = 0
		forced_singleton_count = 0
		configured_singleton_count = 0
		certified_pair_count = 0

		for cohort_key, courses in cohort_courses.items():
			if len(courses) < 2:
				continue
			forced_solo_indices = _forced_solo_indices_for_odd_cohort(
				courses,
				course_codes=odd_solo_codes,
				course_prefixes=odd_solo_prefixes,
			)
			configured_singleton_count += len(forced_solo_indices)

			# Per-course theory slot literal at each (day, slot).
			course_slot_map: Dict[str, Dict[SlotKey, cp_model.IntVar]] = {}
			for course_id, _requirement in courses:
				slot_map: Dict[SlotKey, cp_model.IntVar] = {}
				for _tid, _cid, day_idx, slot_idx, var in iter_course_timeslot_variables(
					context, course_instance_id=course_id
				):
					slot_map[(day_idx, slot_idx)] = var
				course_slot_map[course_id] = slot_map

			solo: Dict[str, cp_model.IntVar] = {
				course_id: model.NewBoolVar(f"bundle_solo_{_sanitize(course_id)}")
				for course_id, _ in courses
			}

			# Candidate pairs: different teacher, and (unless partial pairing is enabled)
			# equal required hours. ``pair_share`` records how many hours each pair bundles
			# together (min of the two courses' hours); the coupling below uses it.
			pair_vars: Dict[Tuple[int, int], cp_model.IntVar] = {}
			pair_share: Dict[Tuple[int, int], int] = {}
			for a in range(len(courses)):
				cid_a, req_a = courses[a]
				base_a = int(getattr(req_a, "required_slots", 0))
				for b in range(a + 1, len(courses)):
					if a in forced_solo_indices or b in forced_solo_indices:
						continue
					cid_b, req_b = courses[b]
					base_b = int(getattr(req_b, "required_slots", 0))
					if base_a <= 0 or base_b <= 0:
						continue
					if not allow_partial and base_a != base_b:
						continue
					if _same_teacher_id(
						getattr(req_a, "teacher_id", ""),
						getattr(req_b, "teacher_id", ""),
					):
						continue
					pair_vars[(a, b)] = model.NewBoolVar(
						f"bundle_pair_{_sanitize(cid_a)}__{_sanitize(cid_b)}"
					)
					pair_share[(a, b)] = min(base_a, base_b)

			configured_pairs = _configured_forced_course_pairs(
				forced_pairs_payload,
				department=cohort_key[0],
				section_id=cohort_key[2],
			)
			if configured_pairs is not None:
				forced_edges = _resolve_forced_pair_edges(
					courses,
					pair_vars,
					configured_pairs,
					cohort_key=cohort_key,
				)
				maximum_pairs = _maximum_matching_size(len(courses), pair_vars)
				if len(forced_edges) != maximum_pairs:
					raise ValueError(
						f"Certified Kutty pairs cover {len(forced_edges)} edges but cohort "
						f"{cohort_key!r} requires {maximum_pairs} maximum pairs"
					)
				for edge, pair_var in pair_vars.items():
					model.Add(pair_var == int(edge in forced_edges))
				certified_pair_count += len(forced_edges)

			# Role: each course is either solo or in exactly one pair.
			for i, (course_id, _req) in enumerate(courses):
				involved = [pv for (a, b), pv in pair_vars.items() if a == i or b == i]
				model.Add(sum(involved) + solo[course_id] == 1)

			# Maximum-cardinality pairing over the actual candidate graph.  This is
			# deliberately graph-based rather than bucket-based: with partial pairing,
			# a 2+1 theory course may validly pair with a 3+1 theory course.  The old
			# per-hour-bucket parity equations incorrectly forced both to remain solo.
			if force_maximal:
				maximum_pairs = _maximum_matching_size(len(courses), pair_vars)
				model.Add(sum(pair_vars.values()) == maximum_pairs)
				forced_pair_count += maximum_pairs
				forced_singleton_count += len(courses) - 2 * maximum_pairs

			# Coverage tied to pairing: solo -> required_slots; paired -> required_slots
			# plus the bundled (shared) hours. For an equal-hour pair the shared count is
			# ``base`` so paired coverage is 2*base (the original 8-half-slot rule); for a
			# partial pair the shorter course contributes its full hours as shared while the
			# longer course keeps (base - shared) solo hours.
			for i, (course_id, req) in enumerate(courses):
				slot_vars = list(course_slot_map[course_id].values())
				if not slot_vars:
					continue
				base = int(getattr(req, "required_slots", 0))
				if base <= 0:
					continue
				share_terms = [
					pair_share[(a, b)] * pv
					for (a, b), pv in pair_vars.items()
					if a == i or b == i
				]
				# course i is in at most one pair, so sum(share_terms) is that pair's
				# shared count when paired, else 0.
				model.Add(sum(slot_vars) == base + sum(share_terms))

			# Co-scheduling + shared room per candidate pair.
			for (a, b), pv in pair_vars.items():
				cid_a, req_a = courses[a]
				cid_b, req_b = courses[b]
				base_a = int(getattr(req_a, "required_slots", 0))
				base_b = int(getattr(req_b, "required_slots", 0))
				if allow_partial and base_a != base_b:
					# Unequal pair: the shorter course sits entirely inside the longer
					# course's slots (shared 25+25 cells); the longer course's extra hours
					# fall outside, scheduled solo.
					short_id, long_id = (cid_a, cid_b) if base_a < base_b else (cid_b, cid_a)
					self._link_subset(model, course_slot_map[short_id], course_slot_map[long_id], pv)
					if enforce_shared_room:
						self._link_shared_room_subset(context, short_id, long_id, pv)
				else:
					self._link_co_schedule(model, course_slot_map[cid_a], course_slot_map[cid_b], pv)
					if enforce_shared_room:
						self._link_shared_room(context, cid_a, cid_b, pv)

			# Hint a greedy maximal pairing so the solver STARTS bundled and only un-bundles
			# where feasibility forces it (soft mode won't otherwise reach heavy bundling
			# within a time budget). Cheap and safe: hints never make a model infeasible.
			if hint_pairing:
				self._hint_maximal_pairing(model, courses, pair_vars, solo, allow_partial)

			# Objective: prefer fewer solos (harmless alongside force_maximal).
			if solo_penalty:
				for index, (course_id, _requirement) in enumerate(courses):
					if index in forced_solo_indices:
						continue
					register_objective_penalty(
						context, solo[course_id], weight=solo_penalty, tag="bundled_theory"
					)
			# Once cardinality is fixed, prefer equal/near-equal L+T loads.  This is a
			# quality tie-break only: it can never reduce the number of paired courses.
			if load_gap_penalty:
				for (a, b), pair_var in pair_vars.items():
					base_a = int(getattr(courses[a][1], "required_slots", 0))
					base_b = int(getattr(courses[b][1], "required_slots", 0))
					gap = abs(base_a - base_b)
					if gap:
						register_objective_penalty(
							context,
							pair_var,
							weight=gap * load_gap_penalty,
							tag="bundled_theory_pair_quality",
						)

			# Store each pair with the SHORTER course first: group_non_overlap uses the
			# first course's presence to mark the shared (bundled) cell, and the shorter
			# course is present only at shared cells. For equal pairs either order is fine.
			def _short_first(a: int, b: int) -> Tuple[str, str]:
				base_a = int(getattr(courses[a][1], "required_slots", 0))
				base_b = int(getattr(courses[b][1], "required_slots", 0))
				return (courses[a][0], courses[b][0]) if base_a <= base_b else (courses[b][0], courses[a][0])

			bundles_store[cohort_key] = {
				"courses": [course_id for course_id, _ in courses],
				"solo": solo,
				"pairs": [
					(pv, *_short_first(a, b)) for (a, b), pv in pair_vars.items()
				],
			}
			total_pairs += len(pair_vars)
			total_courses += len(courses)
			cohorts_done += 1

		# Publish for group_non_overlap (bundle-aware exclusivity).
		existing = context.extra.get("bundles")
		if isinstance(existing, dict):
			existing.update(bundles_store)
		else:
			context.extra["bundles"] = bundles_store

		status = ConstraintStatus.APPLIED if cohorts_done else ConstraintStatus.SKIPPED
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"cohorts": cohorts_done,
				"candidate_pairs": total_pairs,
				"eligible_courses": total_courses,
				"force_maximal_pairing": force_maximal,
				"forced_pairs": forced_pair_count,
				"certified_pairs": certified_pair_count,
				"forced_singletons": forced_singleton_count,
				"configured_odd_cohort_singletons": configured_singleton_count,
			},
		)

	@staticmethod
	def _hint_maximal_pairing(
		model: cp_model.CpModel,
		courses: List[Tuple[str, object]],
		pair_vars: Dict[Tuple[int, int], cp_model.IntVar],
		solo: Dict[str, cp_model.IntVar],
		allow_partial: bool = False,
	) -> None:
		"""Greedy maximal matching fed as solution hints (warm start).

		Non-partial: match within each equal-hour bucket. Partial: match greedily over
		ALL candidate pairs (across hour buckets) so the solver starts from a maximal
		bundling that already uses the cross-hour pairs — important for large cohorts to
		reach heavy bundling within the time budget.
		"""

		chosen: set = set()
		matched_indices: set = set()

		if allow_partial:
			# Greedy over the whole candidate-pair graph, preferring larger shared hours
			# first (min of the two bases) to lock in the most valuable bundles early.
			def _base(i: int) -> int:
				return int(getattr(courses[i][1], "required_slots", 0))
			ordered = sorted(
				pair_vars.keys(), key=lambda k: -min(_base(k[0]), _base(k[1]))
			)
			for a, b in ordered:
				if a in matched_indices or b in matched_indices:
					continue
				chosen.add((a, b))
				matched_indices.add(a)
				matched_indices.add(b)
		else:
			by_bucket: Dict[int, List[int]] = defaultdict(list)
			for i, (_cid, req) in enumerate(courses):
				by_bucket[int(getattr(req, "required_slots", 0))].append(i)
			for indices in by_bucket.values():
				available = list(indices)
				while available:
					a = available.pop(0)
					partner_pos = None
					for pos, b in enumerate(available):
						key = (min(a, b), max(a, b))
						if key in pair_vars:
							partner_pos = pos
							chosen.add(key)
							matched_indices.add(a)
							matched_indices.add(b)
							break
					if partner_pos is not None:
						available.pop(partner_pos)

		for key, pv in pair_vars.items():
			model.AddHint(pv, 1 if key in chosen else 0)
		for i, (course_id, _req) in enumerate(courses):
			model.AddHint(solo[course_id], 0 if i in matched_indices else 1)

	@staticmethod
	def _link_co_schedule(
		model: cp_model.CpModel,
		slots_a: Mapping[SlotKey, cp_model.IntVar],
		slots_b: Mapping[SlotKey, cp_model.IntVar],
		pair_var: cp_model.IntVar,
	) -> None:
		"""When paired, both courses occupy exactly the same day/slot literals."""

		keys_a = set(slots_a)
		keys_b = set(slots_b)
		for key in keys_a & keys_b:
			model.Add(slots_a[key] == slots_b[key]).OnlyEnforceIf(pair_var)
		# A slot only one course can reach cannot host the pair.
		for key in keys_a - keys_b:
			model.Add(slots_a[key] == 0).OnlyEnforceIf(pair_var)
		for key in keys_b - keys_a:
			model.Add(slots_b[key] == 0).OnlyEnforceIf(pair_var)

	@staticmethod
	def _link_subset(
		model: cp_model.CpModel,
		slots_short: Mapping[SlotKey, cp_model.IntVar],
		slots_long: Mapping[SlotKey, cp_model.IntVar],
		pair_var: cp_model.IntVar,
	) -> None:
		"""Partial pair: the shorter course's slots are a subset of the longer's.

		Wherever the shorter course meets, the longer course also meets (a shared 25+25
		cell); coverage gives the longer course its extra hours in cells the shorter one
		never occupies. A slot the shorter course can reach but the longer cannot cannot
		host the pair.
		"""

		keys_short = set(slots_short)
		keys_long = set(slots_long)
		for key in keys_short & keys_long:
			# short present -> long present at the same cell (short <= long).
			model.Add(slots_short[key] <= slots_long[key]).OnlyEnforceIf(pair_var)
		for key in keys_short - keys_long:
			model.Add(slots_short[key] == 0).OnlyEnforceIf(pair_var)

	@staticmethod
	def _link_shared_room(
		context: ConstraintContext,
		course_a: str,
		course_b: str,
		pair_var: cp_model.IntVar,
	) -> None:
		"""When paired, the two courses use the same room in every shared slot."""

		model = context.model
		rooms_a: Dict[Tuple[int, int, str], cp_model.IntVar] = {}
		for _t, _c, day_idx, slot_idx, room_id, var in iter_theory_room_variables(
			context, course_instance_id=course_a
		):
			rooms_a[(day_idx, slot_idx, str(room_id))] = var
		rooms_b: Dict[Tuple[int, int, str], cp_model.IntVar] = {}
		for _t, _c, day_idx, slot_idx, room_id, var in iter_theory_room_variables(
			context, course_instance_id=course_b
		):
			rooms_b[(day_idx, slot_idx, str(room_id))] = var

		for key in set(rooms_a) & set(rooms_b):
			model.Add(rooms_a[key] == rooms_b[key]).OnlyEnforceIf(pair_var)
		for key in set(rooms_a) - set(rooms_b):
			model.Add(rooms_a[key] == 0).OnlyEnforceIf(pair_var)
		for key in set(rooms_b) - set(rooms_a):
			model.Add(rooms_b[key] == 0).OnlyEnforceIf(pair_var)

	@staticmethod
	def _link_shared_room_subset(
		context: ConstraintContext,
		short_id: str,
		long_id: str,
		pair_var: cp_model.IntVar,
	) -> None:
		"""Partial pair: wherever the shorter course uses a room, the longer course uses
		the same room (shared 25+25 cell). The longer course's extra (solo) cells are
		left free to use any room."""

		model = context.model
		rooms_short: Dict[Tuple[int, int, str], cp_model.IntVar] = {}
		for _t, _c, day_idx, slot_idx, room_id, var in iter_theory_room_variables(
			context, course_instance_id=short_id
		):
			rooms_short[(day_idx, slot_idx, str(room_id))] = var
		rooms_long: Dict[Tuple[int, int, str], cp_model.IntVar] = {}
		for _t, _c, day_idx, slot_idx, room_id, var in iter_theory_room_variables(
			context, course_instance_id=long_id
		):
			rooms_long[(day_idx, slot_idx, str(room_id))] = var

		for key in set(rooms_short) & set(rooms_long):
			# short uses room r at (d,s) -> long uses the same room r at (d,s).
			model.Add(rooms_short[key] <= rooms_long[key]).OnlyEnforceIf(pair_var)
		for key in set(rooms_short) - set(rooms_long):
			model.Add(rooms_short[key] == 0).OnlyEnforceIf(pair_var)

	def _skip(self, reason: str) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=ConstraintStatus.SKIPPED,
			details={"reason": reason},
		)


def build_bundled_theory_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> BundledTheoryConstraint:
	return BundledTheoryConstraint(metadata=metadata, params=params)


__all__ = ["BundledTheoryConstraint", "build_bundled_theory_constraint"]
