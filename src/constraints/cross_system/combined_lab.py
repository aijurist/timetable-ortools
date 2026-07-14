"""Combined lab-block courses (e.g. DBMS / OOP-Java) — solver-chosen STABLE pairing.

These courses (configured via ``model.combined_lab_courses``) are delivered as
``blocks`` x ``block_len`` continuous-slot **lab** sessions in the designated ANEW big
rooms, where two section-instances of the SAME course code may share one room (up to
capacity) so a 140/165-seat room is filled by 2 batches of ~70.

The room sharing itself is opportunistic (see ``lab.room_single_assignment``). This
constraint adds the *stability* rule the user wants:

    If two section-instances share a room for ANY one block, they must be paired for
    ALL of their blocks (identical day / session / room every time). The solver freely
    chooses WHO partners with whom — partners may even be in different departments
    (e.g. AI&ML section-A + CSE section-A) — but a partnership, once formed, is locked
    across all 4 blocks. Each instance has at most one partner; solo is allowed but
    penalised so the solver maximises stable pairing (solve WITH optimization).

Model per course code (pool spans all departments unless ``same_department_only``):
* ``together[i,j]`` bool for each candidate same-code pair;
* co-location at any (day, session, room) cell  =>  ``together[i,j] = 1``;
* ``together[i,j] = 1``  =>  the two instances are IDENTICAL at every cell (so they
  share all blocks, and any cell unique to one side is forced off);
* at most one partner per instance;
* a per-instance ``solo`` penalty registered in the global objective.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import register_objective_penalty


def _combined_config(context: ConstraintContext) -> Tuple[FrozenSet[str], int, int]:
	cfg = getattr(getattr(context.config, "model", None), "combined_lab_courses", {}) or {}
	codes = frozenset(str(c).strip().upper() for c in cfg.get("course_codes", ()) if str(c).strip())
	blocks = int(cfg.get("blocks", 4) or 4)
	block_len = int(cfg.get("block_len", 2) or 2)
	return codes, blocks, block_len


class CombinedLabConstraint(Constraint):
	"""Solver-chosen stable pairing for combined lab-block courses."""

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		model = context.model
		lab_block = context.variables.lab
		codes, blocks, _block_len = _combined_config(context)
		if not codes:
			return self._skip("no combined-lab courses configured")
		if not getattr(lab_block, "assignments", None):
			return self._skip("no lab assignments available")

		enforce_pairing = bool(self.params.get("enforce_stable_pairing", True))
		solo_weight = int(self.params.get("solo_penalty_weight", 1000))
		same_department_only = bool(self.params.get("same_department_only", False))
		# Pairing is O(n^2) in candidate pairs. Pooling EVERY same-code section across all
		# departments (n~32) explodes the reified identity constraints and stalls the solver.
		# Partition each course's sections into department-interleaved buckets of this size and
		# only allow pairing WITHIN a bucket -> linear in n, cross-dept pairing still possible.
		# 0 disables bucketing (pool everything).
		max_pair_pool = int(self.params.get("max_pair_pool", 8) or 0)
		# Room-lock: every block of a course-section stays in ONE room (trainer stays put).
		room_lock = bool(self.params.get("room_lock", False))
		# 3+3 room pools: each group of course codes may use at most room_pool_size rooms,
		# and the pools are disjoint. e.g. [["CS23332","CB23333"], ["CS23333"]].
		room_pool_groups = [
			frozenset(str(c).strip().upper() for c in grp)
			for grp in (self.params.get("room_pool_groups", ()) or ())
		]
		room_pool_size = int(self.params.get("room_pool_size", 3) or 3)
		# Fixed named pools (per-dept-safe global split): [[codes...], [room_numbers...]].
		# Each listed course is HARD-restricted to its pool's rooms -> globally consistent
		# across the sequential per-department solve. Solver-chosen room_pool_groups only
		# works in a single global model, so the seeded solve uses this instead.
		room_pools_fixed = self.params.get("room_pools_fixed", ()) or ()

		# Gather combined-lab instances -> flat cell map {(day, session, room): bool}.
		inst_cells: Dict[str, Dict[Tuple[int, str, str], cp_model.IntVar]] = {}
		inst_code: Dict[str, str] = {}
		inst_dept: Dict[str, str] = {}
		requirements = getattr(lab_block, "requirements", {}) or {}
		for _teacher_id, course_map in lab_block.assignments.items():
			for instance_key, day_map in course_map.items():
				req = requirements.get(instance_key)
				code = str(getattr(req, "course_code", "")).strip().upper() if req else ""
				if not req or code not in codes:
					continue
				cells: Dict[Tuple[int, str, str], cp_model.IntVar] = {}
				for day_idx, session_map in day_map.items():
					for session_name, room_bucket in session_map.items():
						for room_id, var in room_bucket.items():
							cells[(day_idx, session_name, str(room_id))] = var
				if not cells:
					continue
				inst_cells[instance_key] = cells
				inst_code[instance_key] = code
				inst_dept[instance_key] = str(getattr(req, "department", ""))

		if not inst_cells:
			return self._skip("no combined-lab lab instances found")

		# --- Fixed named pools: hard-restrict each course to its pool's rooms ---
		pool_restrictions = 0
		if room_pools_fixed:
			registry = getattr(getattr(context.data, "raw", None), "room_registry", {}) or {}
			def _room_num(room_id: str) -> str:
				info = registry.get(str(room_id), {}) or {}
				return str(info.get("room_number", room_id)).strip()
			code_to_rooms: Dict[str, set] = {}
			for entry in room_pools_fixed:
				try:
					codes_list, rooms_list = entry[0], entry[1]
				except (TypeError, IndexError, KeyError):
					continue
				allowed = {str(r).strip().upper() for r in rooms_list}
				for c in codes_list:
					code_to_rooms[str(c).strip().upper()] = allowed
			for instance_key, cells in inst_cells.items():
				allowed = code_to_rooms.get(inst_code.get(instance_key, ""))
				if not allowed:
					continue
				for (_day, _sess, room_id), var in cells.items():
					if _room_num(room_id).upper() not in allowed:
						model.Add(var == 0)
						pool_restrictions += 1

		# --- Room-lock + 3+3 pool split (gated) ---
		room_active: Dict[str, Dict[str, cp_model.IntVar]] = {}
		rooms_locked = pool_rooms_capped = 0
		if room_lock or room_pool_groups:
			for instance_key, cells in inst_cells.items():
				by_room: Dict[str, List[cp_model.IntVar]] = defaultdict(list)
				for (_day, _sess, room_id), var in cells.items():
					by_room[room_id].append(var)
				ra: Dict[str, cp_model.IntVar] = {}
				for room_id, vars_list in by_room.items():
					active = model.NewBoolVar(f"clab_room_{instance_key}_{room_id}")
					for v in vars_list:
						model.Add(v <= active)  # a cell in this room implies room active
					ra[room_id] = active
				room_active[instance_key] = ra
				if room_lock and ra:
					# All blocks of this section share ONE room.
					model.Add(sum(ra.values()) <= 1)
					rooms_locked += 1
		if room_pool_groups:
			all_rooms = sorted({r for ra in room_active.values() for r in ra})
			pool_room_used: List[Dict[str, cp_model.IntVar]] = []
			for gi, group in enumerate(room_pool_groups):
				used: Dict[str, cp_model.IntVar] = {}
				for room_id in all_rooms:
					pu = model.NewBoolVar(f"clab_pool{gi}_{room_id}")
					used[room_id] = pu
					for instance_key, ra in room_active.items():
						if inst_code.get(instance_key) in group and room_id in ra:
							model.Add(ra[room_id] <= pu)  # instance uses room => pool uses room
				model.Add(sum(used.values()) <= room_pool_size)  # <=3 rooms per pool
				pool_rooms_capped += 1
				pool_room_used.append(used)
			# Pools are disjoint: a room belongs to at most one pool.
			for room_id in all_rooms:
				terms = [pu[room_id] for pu in pool_room_used if room_id in pu]
				if len(terms) > 1:
					model.Add(sum(terms) <= 1)

		if not enforce_pairing:
			return self._result(
				ConstraintStatus.SKIPPED,
				{"reason": "stable pairing disabled", "instances": len(inst_cells)},
			)

		# Pool candidate partners by course code (and department when restricted).
		pools: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
		for instance_key in inst_cells:
			pool_key = (inst_code[instance_key],)
			if same_department_only:
				pool_key = (inst_code[instance_key], inst_dept[instance_key])
			pools[pool_key].append(instance_key)

		# Split each pool into department-interleaved buckets so pairing stays scalable while
		# still mixing departments (a bucket can pair AI&ML-A with CSE-A).
		def _bucketize(instances: List[str]) -> List[List[str]]:
			if not max_pair_pool or len(instances) <= max_pair_pool:
				return [sorted(instances)]
			by_dept: Dict[str, List[str]] = defaultdict(list)
			for key in sorted(instances):
				by_dept[inst_dept[key]].append(key)
			round_robin: List[str] = []
			dept_lists = list(by_dept.values())
			while any(dept_lists):
				for dl in dept_lists:
					if dl:
						round_robin.append(dl.pop(0))
			return [round_robin[i:i + max_pair_pool] for i in range(0, len(round_robin), max_pair_pool)]

		tog_by_instance: Dict[str, List[cp_model.IntVar]] = defaultdict(list)
		pairs = links = eqs = 0
		buckets = [b for _pool_key, instances in pools.items() for b in _bucketize(instances)]
		for instances in buckets:
			for a, b in combinations(instances, 2):
				together = model.NewBoolVar(f"clab_tog_{a}__{b}")
				pairs += 1
				tog_by_instance[a].append(together)
				tog_by_instance[b].append(together)
				cells_a, cells_b = inst_cells[a], inst_cells[b]
				for cell in cells_a.keys() & cells_b.keys():
					va, vb = cells_a[cell], cells_b[cell]
					# co-location at any shared cell => the two are partners
					model.Add(va + vb - 1 <= together)
					# partners => identical usage at every shared cell
					model.Add(va == vb).OnlyEnforceIf(together)
					links += 1
					eqs += 1
				# partners => cells unique to one instance are forced off (identical schedules)
				for cell in cells_a.keys() - cells_b.keys():
					model.Add(cells_a[cell] == 0).OnlyEnforceIf(together)
				for cell in cells_b.keys() - cells_a.keys():
					model.Add(cells_b[cell] == 0).OnlyEnforceIf(together)

		# At most one partner each; penalise remaining solo instances.
		solo_terms = 0
		for instance_key, togs in tog_by_instance.items():
			model.Add(sum(togs) <= 1)
			if solo_weight > 0:
				solo = model.NewBoolVar(f"clab_solo_{instance_key}")
				model.Add(sum(togs) + solo == 1)
				register_objective_penalty(context, solo, solo_weight, tag="combined_lab:solo")
				solo_terms += 1

		return self._result(
			ConstraintStatus.APPLIED if pairs else ConstraintStatus.SKIPPED,
			{
				"instances": len(inst_cells),
				"candidate_pairs": pairs,
				"colocation_links": links,
				"identity_constraints": eqs,
				"solo_penalty_terms": solo_terms,
				"solo_penalty_weight": solo_weight,
				"same_department_only": same_department_only,
				"blocks_each": blocks,
			},
		)

	def _skip(self, reason: str) -> ConstraintApplicationResult:
		return self._result(ConstraintStatus.SKIPPED, {"reason": reason})

	def _result(self, status: str, details: Mapping[str, object]) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=details,
		)


def build_combined_lab_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> CombinedLabConstraint:
	return CombinedLabConstraint(metadata=metadata, params=params)


__all__ = ["CombinedLabConstraint", "build_combined_lab_constraint"]
