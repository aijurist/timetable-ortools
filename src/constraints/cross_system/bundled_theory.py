"""Bundled theory constraint for section-based cohorts (2nd year).

Two theory courses of an eligible cohort may share a single 50-minute slot, split
25min + 25min ("bundling"). The solver decides which courses pair, subject to:

* only courses with equal required theory hours and different teachers may pair;
* a bundled course needs twice as many slot appearances (the 8-half-slot rule);
* a bundled pair is co-scheduled (same day/slot) and shares one room;
* pairing is maximal per hour-bucket (leftover only from an odd count) unless the
  ``force_maximal_pairing`` param is disabled, in which case fewer solos are only
  softly preferred.

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

CohortKey = Tuple[str, Optional[int], Optional[int]]
SlotKey = Tuple[int, int]


def _sanitize(value: object) -> str:
	return re.sub(r"[^0-9A-Za-z]+", "_", str(value)).strip("_") or "x"


class BundledTheoryConstraint(Constraint):
	"""Create bundle decision variables and their coupling constraints."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		theory_block = context.variables.theory
		if not bundle_eligible_cohorts(context.config):
			return self._skip("no eligible cohorts configured")

		force_maximal = bool(self.params.get("force_maximal_pairing", True))
		solo_penalty = int(self.params.get("solo_penalty_weight", 10) or 0)
		enforce_shared_room = bool(self.params.get("enforce_shared_room", True))
		hint_pairing = bool(self.params.get("hint_maximal_pairing", True))

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

		for cohort_key, courses in cohort_courses.items():
			if len(courses) < 2:
				continue

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

			# Candidate pairs: equal required hours + different teacher.
			pair_vars: Dict[Tuple[int, int], cp_model.IntVar] = {}
			for a in range(len(courses)):
				cid_a, req_a = courses[a]
				for b in range(a + 1, len(courses)):
					cid_b, req_b = courses[b]
					if int(getattr(req_a, "required_slots", 0)) != int(getattr(req_b, "required_slots", 0)):
						continue
					if str(getattr(req_a, "teacher_id", "")) == str(getattr(req_b, "teacher_id", "")):
						continue
					pair_vars[(a, b)] = model.NewBoolVar(
						f"bundle_pair_{_sanitize(cid_a)}__{_sanitize(cid_b)}"
					)

			# Role: each course is either solo or in exactly one pair.
			for i, (course_id, _req) in enumerate(courses):
				involved = [pv for (a, b), pv in pair_vars.items() if a == i or b == i]
				model.Add(sum(involved) + solo[course_id] == 1)

			# Maximal pairing per hour-bucket (leftover only from odd count).
			if force_maximal:
				buckets: Dict[int, List[str]] = defaultdict(list)
				for course_id, req in courses:
					buckets[int(getattr(req, "required_slots", 0))].append(course_id)
				for bucket_courses in buckets.values():
					model.Add(sum(solo[c] for c in bucket_courses) == len(bucket_courses) % 2)

			# Coverage tied to pairing: solo -> required_slots, paired -> 2x (8 half-slots).
			# sum(slots) == required_slots + required_slots*is_paired = 2*base - base*solo.
			for course_id, req in courses:
				slot_vars = list(course_slot_map[course_id].values())
				if not slot_vars:
					continue
				base = int(getattr(req, "required_slots", 0))
				if base <= 0:
					continue
				model.Add(sum(slot_vars) == 2 * base - base * solo[course_id])

			# Co-scheduling + shared room per candidate pair.
			for (a, b), pv in pair_vars.items():
				cid_a, _ = courses[a]
				cid_b, _ = courses[b]
				self._link_co_schedule(model, course_slot_map[cid_a], course_slot_map[cid_b], pv)
				if enforce_shared_room:
					self._link_shared_room(context, cid_a, cid_b, pv)

			# Hint a greedy maximal pairing so the solver STARTS bundled and only un-bundles
			# where feasibility forces it (soft mode won't otherwise reach heavy bundling
			# within a time budget). Cheap and safe: hints never make a model infeasible.
			if hint_pairing:
				self._hint_maximal_pairing(model, courses, pair_vars, solo)

			# Objective: prefer fewer solos (harmless alongside force_maximal).
			if solo_penalty:
				for course_id, _ in courses:
					register_objective_penalty(
						context, solo[course_id], weight=solo_penalty, tag="bundled_theory"
					)

			bundles_store[cohort_key] = {
				"courses": [course_id for course_id, _ in courses],
				"solo": solo,
				"pairs": [
					(pv, courses[a][0], courses[b][0]) for (a, b), pv in pair_vars.items()
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
			},
		)

	@staticmethod
	def _hint_maximal_pairing(
		model: cp_model.CpModel,
		courses: List[Tuple[str, object]],
		pair_vars: Dict[Tuple[int, int], cp_model.IntVar],
		solo: Dict[str, cp_model.IntVar],
	) -> None:
		"""Greedy maximal matching within each hour-bucket, fed as solution hints."""

		by_bucket: Dict[int, List[int]] = defaultdict(list)
		for i, (_cid, req) in enumerate(courses):
			by_bucket[int(getattr(req, "required_slots", 0))].append(i)

		chosen: set = set()
		matched_indices: set = set()
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
