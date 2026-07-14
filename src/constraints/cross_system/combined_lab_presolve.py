"""Global stable-footprint presolve for DBMS/OOPS-style combined labs.

The production scheduler solves departments sequentially, but the shared combined
lab pool is a global resource.  This module plans that resource first:

1. deterministically form the largest compatible section groups (triples only when
   a 210-seat room exists, otherwise pairs, with a singleton only when unavoidable);
2. assign every group one room and one complete multi-session footprint;
3. return per-section locks that departmental models can enforce later.

Teacher overlap is intentionally absent: these courses are delivered by external
trainers.  The section/teacher recorded on each member is retained solely to keep
the chosen group explicit and stable in every scheduled session.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha1
from itertools import combinations
from typing import Iterable, Mapping, Sequence, Tuple

from ortools.sat.python import cp_model

from .combined_lab_reuse import CombinedCell


SectionKey = Tuple[str, str]
PlanKey = Tuple[str, str]


@dataclass(frozen=True)
class PreallocationInstance:
    department_key: str
    instance_id: str
    family: str
    course_code: str
    teacher_id: str
    section_key: SectionKey
    day_pattern: Tuple[str, ...]
    required_sessions: int
    allowed_cells: Tuple[CombinedCell, ...]

    @property
    def key(self) -> PlanKey:
        return self.department_key, self.instance_id


@dataclass(frozen=True)
class StableSectionGroup:
    group_id: str
    family: str
    members: Tuple[PreallocationInstance, ...]
    required_sessions: int
    allowed_cells: Tuple[CombinedCell, ...]

    @property
    def size(self) -> int:
        return len(self.members)


@dataclass(frozen=True)
class CombinedPreallocationPlan:
    status: str
    assignments: Mapping[PlanKey, Tuple[CombinedCell, ...]]
    groups: Tuple[StableSectionGroup, ...]
    objective_value: float | None
    wall_time_seconds: float


def _instance_sort_key(instance: PreallocationInstance) -> tuple[object, ...]:
    return (
        instance.day_pattern,
        instance.department_key,
        instance.section_key,
        instance.course_code,
        instance.teacher_id,
        instance.instance_id,
    )


def _make_group(
    family: str,
    members: Sequence[PreallocationInstance],
    room_capacities: Mapping[str, int],
) -> StableSectionGroup | None:
    if not members:
        return None
    required = members[0].required_sessions
    if required <= 0 or any(member.required_sessions != required for member in members):
        return None
    if len({member.section_key for member in members}) != len(members):
        return None
    common = set(members[0].allowed_cells)
    for member in members[1:]:
        common.intersection_update(member.allowed_cells)
    common = {cell for cell in common if int(room_capacities.get(cell[0], 0)) >= len(members)}
    if len(common) < required:
        return None
    ordered = tuple(sorted(members, key=_instance_sort_key))
    digest = sha1(repr((family, tuple(member.key for member in ordered))).encode("utf-8")).hexdigest()[:12]
    return StableSectionGroup(
        group_id=f"prealloc_{family.lower()}_{digest}",
        family=family,
        members=ordered,
        required_sessions=required,
        allowed_cells=tuple(sorted(common)),
    )


def build_maximal_section_groups(
    instances: Iterable[PreallocationInstance],
    room_capacities: Mapping[str, int],
    preferred_clusters: Mapping[Tuple[str, str], Sequence[Sequence[str]]] | None = None,
    forced_clusters: Mapping[str, Sequence[Sequence[Tuple[str, str]]]] | None = None,
) -> Tuple[StableSectionGroup, ...]:
    """Build deterministic maximal groups while preserving working-day flexibility.

    Sections with the same working-day pattern are grouped first so Monday-only or
    Saturday-only capacity remains usable.  Leftovers may pair across patterns when
    their common Tuesday-Friday footprint is large enough.
    """

    by_family: dict[str, list[PreallocationInstance]] = defaultdict(list)
    for instance in instances:
        by_family[instance.family].append(instance)

    if preferred_clusters:
        return _build_preferred_section_groups(
            by_family=by_family,
            room_capacities=room_capacities,
            preferred_clusters=preferred_clusters,
            forced_clusters=forced_clusters or {},
        )

    groups: list[StableSectionGroup] = []
    for family in sorted(by_family):
        family_instances = sorted(by_family[family], key=_instance_sort_key)
        by_pattern: dict[Tuple[str, ...], list[PreallocationInstance]] = defaultdict(list)
        for instance in family_instances:
            by_pattern[instance.day_pattern].append(instance)
        patterns = sorted(by_pattern)
        required = family_instances[0].required_sessions if family_instances else 0

        triple_cells = {
            cell
            for instance in family_instances
            for cell in instance.allowed_cells
            if int(room_capacities.get(cell[0], 0)) >= 3
        }
        target_triples = min(len(family_instances) // 3, len(triple_cells) // max(1, required))

        # Round-robin across day patterns, rather than exhausting one pattern first.
        while target_triples > 0:
            progress = False
            for pattern in patterns:
                bucket = by_pattern[pattern]
                if len(bucket) < 3 or target_triples <= 0:
                    continue
                candidate = _make_group(family, bucket[:3], room_capacities)
                if candidate is None:
                    continue
                del bucket[:3]
                groups.append(candidate)
                target_triples -= 1
                progress = True
            if not progress:
                break

        leftovers: list[PreallocationInstance] = []
        for pattern in patterns:
            bucket = by_pattern[pattern]
            while len(bucket) >= 2:
                candidate = _make_group(family, bucket[:2], room_capacities)
                if candidate is None:
                    break
                del bucket[:2]
                groups.append(candidate)
            leftovers.extend(bucket)

        leftovers.sort(key=_instance_sort_key)
        while len(leftovers) >= 2:
            first = leftovers.pop(0)
            partner_index = next(
                (
                    index
                    for index, candidate in enumerate(leftovers)
                    if _make_group(family, (first, candidate), room_capacities) is not None
                ),
                None,
            )
            if partner_index is None:
                singleton = _make_group(family, (first,), room_capacities)
                if singleton is None:
                    raise ValueError(f"No feasible cells for combined instance {first.key}")
                groups.append(singleton)
                continue
            partner = leftovers.pop(partner_index)
            pair = _make_group(family, (first, partner), room_capacities)
            if pair is None:  # pragma: no cover - guarded above
                raise AssertionError("compatible pair unexpectedly failed")
            groups.append(pair)
        if leftovers:
            singleton = _make_group(family, (leftovers[0],), room_capacities)
            if singleton is None:
                raise ValueError(f"No feasible cells for combined instance {leftovers[0].key}")
            groups.append(singleton)

    return tuple(sorted(groups, key=lambda group: (group.family, group.group_id)))


def _build_preferred_section_groups(
    *,
    by_family: Mapping[str, Sequence[PreallocationInstance]],
    room_capacities: Mapping[str, int],
    preferred_clusters: Mapping[Tuple[str, str], Sequence[Sequence[str]]],
    forced_clusters: Mapping[str, Sequence[Sequence[Tuple[str, str]]]],
) -> Tuple[StableSectionGroup, ...]:
    """Preserve locally certified pairs, then pack their remaining capacity globally."""

    groups: list[StableSectionGroup] = []
    for family in sorted(by_family):
        family_instances = sorted(by_family[family], key=_instance_sort_key)
        by_member = {
            (instance.department_key, str(instance.section_key[1])): instance
            for instance in family_instances
        }
        claimed: set[PlanKey] = set()
        atoms: list[Tuple[PreallocationInstance, ...]] = []
        forced_member_sets: set[frozenset[PlanKey]] = set()

        for member_specs in forced_clusters.get(family, ()):
            atom = tuple(
                by_member[(str(department), str(section_token))]
                for department, section_token in member_specs
                if (str(department), str(section_token)) in by_member
            )
            if not atom:
                continue
            if len(atom) != len(member_specs):
                raise ValueError(f"Forced combined group {family} references missing sections: {member_specs}")
            if any(member.key in claimed for member in atom):
                raise ValueError(f"Duplicate forced combined group member in {family}: {member_specs}")
            if _make_group(family, atom, room_capacities) is None:
                raise ValueError(f"Incompatible forced combined group for {family}: {member_specs}")
            claimed.update(member.key for member in atom)
            forced_member_sets.add(frozenset(member.key for member in atom))
            atoms.append(tuple(sorted(atom, key=_instance_sort_key)))

        for department, cluster_family in sorted(preferred_clusters):
            if cluster_family != family:
                continue
            if not any(member_department == department for member_department, _section in by_member):
                continue
            for section_tokens in preferred_clusters[(department, cluster_family)]:
                atom = tuple(
                    by_member[(department, str(section_token))]
                    for section_token in section_tokens
                    if (department, str(section_token)) in by_member
                )
                if len(atom) != len(section_tokens):
                    missing = sorted(
                        str(token)
                        for token in section_tokens
                        if (department, str(token)) not in by_member
                    )
                    raise ValueError(
                        f"Combined pairing hint {department}/{family} references missing sections {missing}"
                    )
                claimed_members = [member.key in claimed for member in atom]
                if all(claimed_members):
                    continue
                if any(claimed_members):
                    raise ValueError(f"Partially duplicated combined pairing hint in {department}/{family}")
                if _make_group(family, atom, room_capacities) is None:
                    raise ValueError(f"Incompatible combined pairing hint for {department}/{family}: {section_tokens}")
                claimed.update(member.key for member in atom)
                atoms.append(tuple(sorted(atom, key=_instance_sort_key)))

        atoms.extend((instance,) for instance in family_instances if instance.key not in claimed)
        atoms.sort(key=lambda atom: tuple(_instance_sort_key(member) for member in atom))

        required = family_instances[0].required_sessions if family_instances else 0
        triple_cells = {
            cell
            for instance in family_instances
            for cell in instance.allowed_cells
            if int(room_capacities.get(cell[0], 0)) >= 3
        }
        target_triples = min(len(family_instances) // 3, len(triple_cells) // max(1, required))
        used: set[int] = set()
        for index, atom in enumerate(atoms):
            if frozenset(member.key for member in atom) not in forced_member_sets:
                continue
            group = _make_group(family, atom, room_capacities)
            if group is None:  # pragma: no cover - validated above
                raise AssertionError("forced group unexpectedly became incompatible")
            groups.append(group)
            used.add(index)
        forced_triples = sum(
            1
            for atom in atoms
            if len(atom) == 3 and frozenset(member.key for member in atom) in forced_member_sets
        )
        triples_left = max(0, target_triples - forced_triples)

        # Promote an already-certified local pair with one section from another
        # department. This preserves the local compatibility while using KS02's
        # third seat wherever the global capacity calculation requires it.
        pair_buckets: dict[Tuple[str, ...], list[int]] = defaultdict(list)
        for index, atom in enumerate(atoms):
            if len(atom) == 2:
                pair_buckets[atom[0].day_pattern].append(index)
        pair_order: list[int] = []
        pair_patterns = sorted(pair_buckets)
        while any(pair_buckets.values()):
            for pattern in pair_patterns:
                if pair_buckets[pattern]:
                    pair_order.append(pair_buckets[pattern].pop(0))

        for pair_index in pair_order:
            if triples_left <= 0:
                break
            pair_atom = atoms[pair_index]
            if pair_index in used:
                continue
            pair_departments = {member.department_key for member in pair_atom}
            single_order = sorted(
                range(len(atoms)),
                key=lambda index: (
                    0 if atoms[index][0].day_pattern == pair_atom[0].day_pattern else 1,
                    tuple(_instance_sort_key(member) for member in atoms[index]),
                ),
            )
            for single_index in single_order:
                single_atom = atoms[single_index]
                if single_index in used or single_index == pair_index or len(single_atom) != 1:
                    continue
                if single_atom[0].department_key in pair_departments:
                    continue
                candidate = _make_group(family, (*pair_atom, *single_atom), room_capacities)
                if candidate is None:
                    continue
                groups.append(candidate)
                used.update((pair_index, single_index))
                triples_left -= 1
                break

        # If more triples are needed, combine three singletons from distinct
        # departments. Never invent a new same-department pairing here.
        while triples_left > 0:
            candidate_group = None
            candidate_indexes = None
            free_singletons = [
                index for index, atom in enumerate(atoms) if index not in used and len(atom) == 1
            ]
            for indexes in combinations(free_singletons, 3):
                members = tuple(atoms[index][0] for index in indexes)
                if len({member.department_key for member in members}) != 3:
                    continue
                candidate_group = _make_group(family, members, room_capacities)
                if candidate_group is not None:
                    candidate_indexes = indexes
                    break
            if candidate_group is None or candidate_indexes is None:
                raise ValueError(f"Cannot form required capacity-preserving {family} triples")
            groups.append(candidate_group)
            used.update(candidate_indexes)
            triples_left -= 1

        remaining_pairs: list[Tuple[PreallocationInstance, ...]] = []
        remaining_singletons: list[Tuple[PreallocationInstance, ...]] = []
        for index, atom in enumerate(atoms):
            if index in used:
                continue
            if len(atom) == 2:
                remaining_pairs.append(atom)
            elif len(atom) == 1:
                remaining_singletons.append(atom)
            else:  # pragma: no cover - forced triples are consumed above
                raise AssertionError(f"Unexpected remaining atom size {len(atom)}")

        for atom in remaining_pairs:
            group = _make_group(family, atom, room_capacities)
            if group is None:  # pragma: no cover - validated above
                raise AssertionError("certified pair unexpectedly became incompatible")
            groups.append(group)

        while len(remaining_singletons) >= 2:
            first = remaining_singletons.pop(0)
            if len(first[0].allowed_cells) == first[0].required_sessions:
                group = _make_group(family, first, room_capacities)
                if group is None:  # pragma: no cover - fixed footprint validated upstream
                    raise ValueError(f"No feasible cells for combined instance {first[0].key}")
                groups.append(group)
                continue
            partner_index = next(
                (
                    index
                    for index, candidate in enumerate(remaining_singletons)
                    if candidate[0].department_key != first[0].department_key
                    and len(candidate[0].allowed_cells) != candidate[0].required_sessions
                    and _make_group(family, (*first, *candidate), room_capacities) is not None
                ),
                None,
            )
            if partner_index is None:
                group = _make_group(family, first, room_capacities)
            else:
                partner = remaining_singletons.pop(partner_index)
                group = _make_group(family, (*first, *partner), room_capacities)
            if group is None:
                raise ValueError(f"No feasible cells for combined instance {first[0].key}")
            groups.append(group)
        if remaining_singletons:
            group = _make_group(family, remaining_singletons[0], room_capacities)
            if group is None:
                raise ValueError(f"No feasible cells for combined instance {remaining_singletons[0][0].key}")
            groups.append(group)

    return tuple(sorted(groups, key=lambda group: (group.family, group.group_id)))


def solve_combined_preallocation(
    *,
    groups: Sequence[StableSectionGroup],
    room_capacities: Mapping[str, int],
    fixed_occupancy: Mapping[CombinedCell, int] | None = None,
    max_daily_sessions: int = 2,
    max_section_daily_sessions: int | None = 2,
    preferred_section_daily_sessions: int | None = 2,
    time_limit_seconds: float = 60.0,
    workers: int = 8,
) -> CombinedPreallocationPlan:
    """Assign every stable group a complete room/day/session footprint."""

    fixed_occupancy = fixed_occupancy or {}
    model = cp_model.CpModel()
    variables: dict[Tuple[str, CombinedCell], cp_model.IntVar] = {}
    group_rooms: dict[Tuple[str, str], cp_model.IntVar] = {}
    repeated_group_days: list[cp_model.IntVar] = []

    for group in groups:
        cells = [
            cell
            for cell in group.allowed_cells
            if int(room_capacities.get(cell[0], 0)) - int(fixed_occupancy.get(cell, 0)) >= group.size
        ]
        if len(cells) < group.required_sessions:
            return CombinedPreallocationPlan("INFEASIBLE", {}, tuple(groups), None, 0.0)
        rooms = sorted({cell[0] for cell in cells})
        for room in rooms:
            group_rooms[(group.group_id, room)] = model.NewBoolVar(
                f"prealloc_room_{group.group_id}_{room}"
            )
        model.Add(sum(group_rooms[(group.group_id, room)] for room in rooms) == 1)
        group_vars = []
        by_day: dict[str, list[cp_model.IntVar]] = defaultdict(list)
        for cell in cells:
            variable = model.NewBoolVar(
                f"prealloc_cell_{group.group_id}_{cell[0]}_{cell[1]}_{cell[2]}"
            )
            variables[(group.group_id, cell)] = variable
            group_vars.append(variable)
            by_day[cell[1]].append(variable)
            model.Add(variable <= group_rooms[(group.group_id, cell[0])])
        model.Add(sum(group_vars) == group.required_sessions)
        for day, day_variables in by_day.items():
            model.Add(sum(day_variables) <= max_daily_sessions)
            if max_daily_sessions > 1:
                repeated = model.NewBoolVar(f"prealloc_repeat_{group.group_id}_{day}")
                model.Add(sum(day_variables) <= 1 + (max_daily_sessions - 1) * repeated)
                repeated_group_days.append(repeated)

    all_cells = sorted({cell for _group_id, cell in variables})
    for cell in all_cells:
        model.Add(
            sum(
                group.size * variables[(group.group_id, cell)]
                for group in groups
                if (group.group_id, cell) in variables
            )
            <= int(room_capacities.get(cell[0], 0)) - int(fixed_occupancy.get(cell, 0))
        )

    # Separate groups may use spare seats in the same room, but only as a stable
    # partnership: sharing any one cell forces their complete footprints to be
    # identical. This permits two certified singletons (or a pair + singleton in
    # KS02) to pack together without changing partners between sessions.
    for first, second in combinations(groups, 2):
        first_cells = {
            cell for cell in first.allowed_cells if (first.group_id, cell) in variables
        }
        second_cells = {
            cell for cell in second.allowed_cells if (second.group_id, cell) in variables
        }
        shared_cells = sorted(first_cells & second_cells)
        if not shared_cells:
            continue
        colocated_cells = []
        for cell in shared_cells:
            first_var = variables[(first.group_id, cell)]
            second_var = variables[(second.group_id, cell)]
            colocated = model.NewBoolVar(
                f"prealloc_colocated_{first.group_id}_{second.group_id}_{cell[0]}_{cell[1]}_{cell[2]}"
            )
            model.Add(colocated <= first_var)
            model.Add(colocated <= second_var)
            model.Add(colocated >= first_var + second_var - 1)
            colocated_cells.append(colocated)
        together = model.NewBoolVar(
            f"prealloc_together_{first.group_id}_{second.group_id}"
        )
        model.AddMaxEquality(together, colocated_cells)
        for cell in first_cells | second_cells:
            first_var = variables.get((first.group_id, cell))
            second_var = variables.get((second.group_id, cell))
            if first_var is not None and second_var is not None:
                model.Add(first_var == second_var).OnlyEnforceIf(together)
            elif first_var is not None:
                model.Add(first_var == 0).OnlyEnforceIf(together)
            elif second_var is not None:
                model.Add(second_var == 0).OnlyEnforceIf(together)

    # A student section may not attend DBMS and OOPS at the same lab time.
    section_terms: dict[Tuple[SectionKey, str, str], list[cp_model.IntVar]] = defaultdict(list)
    for group in groups:
        for section_key in {member.section_key for member in group.members}:
            for cell in group.allowed_cells:
                variable = variables.get((group.group_id, cell))
                if variable is not None:
                    section_terms[(section_key, cell[1], cell[2])].append(variable)
    for terms in section_terms.values():
        if len(terms) > 1:
            model.Add(sum(terms) <= 1)

    # Protect the downstream section timetable, not the nominal teachers: DBMS
    # and OOPS may each use two blocks on a day when room capacity requires it,
    # but the same student section must not lose more than two combined-lab
    # blocks on that day across both subjects.
    section_daily_excess: list[cp_model.IntVar] = []
    if max_section_daily_sessions is not None:
        section_day_terms: dict[Tuple[SectionKey, str], list[cp_model.IntVar]] = defaultdict(list)
        for group in groups:
            for section_key in {member.section_key for member in group.members}:
                for cell in group.allowed_cells:
                    variable = variables.get((group.group_id, cell))
                    if variable is not None:
                        section_day_terms[(section_key, cell[1])].append(variable)
        for terms in section_day_terms.values():
            model.Add(sum(terms) <= int(max_section_daily_sessions))
            if (
                preferred_section_daily_sessions is not None
                and preferred_section_daily_sessions < max_section_daily_sessions
            ):
                excess = model.NewIntVar(
                    0,
                    int(max_section_daily_sessions - preferred_section_daily_sessions),
                    f"prealloc_section_daily_excess_{len(section_daily_excess)}",
                )
                model.Add(excess >= sum(terms) - int(preferred_section_daily_sessions))
                section_daily_excess.append(excess)

    # Concentrate combined teaching into fewer global time windows. This leaves
    # larger contiguous regions for ordinary theory/labs in the department pass.
    time_used = []
    for day_session in sorted({(cell[1], cell[2]) for cell in all_cells}):
        terms = [
            variable
            for (group_id, cell), variable in variables.items()
            if (cell[1], cell[2]) == day_session
        ]
        used = model.NewBoolVar(f"prealloc_time_{day_session[0]}_{day_session[1]}")
        model.AddMaxEquality(used, terms)
        time_used.append(used)
    tie_breaker = sum(
        (index + 1) * variables[key]
        for index, key in enumerate(sorted(variables, key=lambda item: (item[1], item[0])))
    )
    # First minimize the same-subject double days that room capacity makes
    # unavoidable, then compact global trainer windows, then select one stable
    # deterministic optimum.
    model.Minimize(
        100_000_000 * sum(section_daily_excess)
        + 10_000_000 * sum(repeated_group_days)
        + 100_000 * sum(time_used)
        + tie_breaker
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.1, float(time_limit_seconds))
    solver.parameters.num_search_workers = max(1, int(workers))
    solver.parameters.random_seed = 1
    status_code = solver.Solve(model)
    status = solver.StatusName(status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return CombinedPreallocationPlan(status, {}, tuple(groups), None, solver.WallTime())

    assignments: dict[PlanKey, Tuple[CombinedCell, ...]] = {}
    for group in groups:
        footprint = tuple(
            sorted(
                cell
                for cell in group.allowed_cells
                if (group.group_id, cell) in variables and solver.Value(variables[(group.group_id, cell)])
            )
        )
        for member in group.members:
            assignments[member.key] = footprint
    return CombinedPreallocationPlan(
        status=status,
        assignments=assignments,
        groups=tuple(groups),
        objective_value=solver.ObjectiveValue(),
        wall_time_seconds=solver.WallTime(),
    )


__all__ = [
    "CombinedPreallocationPlan",
    "PreallocationInstance",
    "StableSectionGroup",
    "build_maximal_section_groups",
    "solve_combined_preallocation",
]
