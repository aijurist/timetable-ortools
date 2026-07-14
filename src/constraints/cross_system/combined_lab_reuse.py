"""Stable cross-department reuse for externally handled combined labs.

The production runner solves departments sequentially.  This module lets a later
DBMS/OOPS section reuse an earlier section's *complete* room/day/session
footprint, while leaving theory and ordinary labs as hard room blockers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha1
from typing import Callable, Iterable, Mapping, Sequence, Tuple

from ortools.sat.python import cp_model


CombinedCell = Tuple[str, str, str]


def _value(record: object, name: str, default: object = "") -> object:
	if isinstance(record, Mapping):
		return record.get(name, default)
	return getattr(record, name, default)


def normalize_day(value: object) -> str:
	token = str(value or "").strip().lower()
	return {"wednesday": "wed", "thursday": "thur", "friday": "fri"}.get(token, token)


def _sanitize(value: object) -> str:
	return "".join(ch if ch.isalnum() else "_" for ch in str(value))


@dataclass(frozen=True)
class FootprintMember:
	key: str
	instance_id: str
	department: str
	teacher_id: str
	teacher_name: str
	course_code: str


@dataclass(frozen=True)
class CombinedFootprintGroup:
	group_id: str
	family: str
	cells: Tuple[CombinedCell, ...]
	members: Tuple[FootprintMember, ...]


@dataclass(frozen=True)
class StableReuseBinding:
	current_instance_id: str
	prior_group_id: str
	prior_member_keys: Tuple[str, ...]
	cells: Tuple[CombinedCell, ...]
	literal: cp_model.IntVar


@dataclass(frozen=True)
class StableReuseResult:
	bindings: Tuple[StableReuseBinding, ...]
	current_instances: int
	candidate_bindings: int
	blocked_partial_variables: int


def collect_footprint_groups(
	entries: Iterable[object],
	family_by_code: Mapping[str, str],
) -> Tuple[CombinedFootprintGroup, ...]:
	"""Collect identical full footprints into stable co-schedule groups."""

	instance_cells: dict[Tuple[str, str, str], set[CombinedCell]] = defaultdict(set)
	instance_meta: dict[Tuple[str, str, str], FootprintMember] = {}
	for entry in entries:
		course_code = str(_value(entry, "course_code", "")).strip().upper()
		family = family_by_code.get(course_code)
		if not family:
			continue
		instance_id = str(_value(entry, "course_instance_id", "")).strip()
		department = str(_value(entry, "department", "")).strip()
		room = str(_value(entry, "room_number", "") or _value(entry, "room_id", "")).strip()
		day = normalize_day(_value(entry, "day", ""))
		session = str(_value(entry, "session_name", "")).strip()
		if not instance_id or not room or not day or not session:
			continue
		key = (department, instance_id, family)
		instance_cells[key].add((room, day, session))
		member_key = f"{department}::{instance_id}"
		instance_meta[key] = FootprintMember(
			key=member_key,
			instance_id=instance_id,
			department=department,
			teacher_id=str(_value(entry, "teacher_id", "")).strip(),
			teacher_name=str(_value(entry, "teacher_name", "")).strip(),
			course_code=course_code,
		)

	grouped: dict[Tuple[str, Tuple[CombinedCell, ...]], list[FootprintMember]] = defaultdict(list)
	for key, cells in instance_cells.items():
		footprint = tuple(sorted(cells))
		if footprint:
			grouped[(key[2], footprint)].append(instance_meta[key])

	groups = []
	for (family, cells), members in grouped.items():
		digest = sha1(repr((family, cells)).encode("utf-8")).hexdigest()[:12]
		groups.append(
			CombinedFootprintGroup(
				group_id=f"combined_{family.lower()}_{digest}",
				family=family,
				cells=cells,
				members=tuple(sorted(members, key=lambda member: member.key)),
			)
		)
	return tuple(sorted(groups, key=lambda group: (group.family, group.cells)))


def bind_stable_prior_footprints(
	*,
	model: cp_model.CpModel,
	lab_block: object,
	prior_groups: Sequence[CombinedFootprintGroup],
	family_by_code: Mapping[str, str],
	room_number_by_id: Mapping[str, str],
	cell_occupancy: Mapping[CombinedCell, int],
	max_share: Callable[[str], int],
) -> StableReuseResult:
	"""Bind current combined sections to complete reusable prior footprints.

	Any current variable that touches a previously occupied combined-lab cell must
	select exactly one compatible prior footprint.  Selecting it forces every cell
	in that footprint, making the section pairing stable across all sessions.
	"""

	requirements = getattr(lab_block, "requirements", {}) or {}
	patterns = getattr(lab_block, "day_patterns", {}) or {}
	assignments = getattr(lab_block, "assignments", {}) or {}
	instance_cells: dict[str, dict[CombinedCell, cp_model.IntVar]] = defaultdict(dict)
	instance_family: dict[str, str] = {}

	for _teacher_id, course_map in assignments.items():
		for instance_id, day_map in course_map.items():
			requirement = requirements.get(instance_id)
			course_code = str(getattr(requirement, "course_code", "")).strip().upper()
			family = family_by_code.get(course_code)
			if not family:
				continue
			instance_family[instance_id] = family
			pattern = tuple(patterns.get(instance_id, ()) or ())
			for day_index, session_map in day_map.items():
				raw_day = pattern[day_index] if 0 <= day_index < len(pattern) else str(day_index)
				day = normalize_day(raw_day)
				for session_name, room_map in session_map.items():
					for room_id, variable in room_map.items():
						room = str(room_number_by_id.get(str(room_id), str(room_id)))
						instance_cells[instance_id][(room, day, str(session_name))] = variable

	groups_by_family: dict[str, list[CombinedFootprintGroup]] = defaultdict(list)
	existing_cells_by_family: dict[str, set[CombinedCell]] = defaultdict(set)
	for group in prior_groups:
		groups_by_family[group.family].append(group)
		existing_cells_by_family[group.family].update(group.cells)

	bindings: list[StableReuseBinding] = []
	blocked_partial_variables = 0
	for instance_id, cells in instance_cells.items():
		family = instance_family[instance_id]
		requirement = requirements.get(instance_id)
		required_sessions = int(getattr(requirement, "required_sessions", 0) or 0)
		candidate_pairs: list[Tuple[CombinedFootprintGroup, cp_model.IntVar]] = []
		for group in groups_by_family.get(family, ()):
			if required_sessions and len(group.cells) != required_sessions:
				continue
			if not all(cell in cells for cell in group.cells):
				continue
			if not all(cell_occupancy.get(cell, 0) < max_share(cell[0]) for cell in group.cells):
				continue
			literal = model.NewBoolVar(
				f"reuse_{_sanitize(instance_id)}__{_sanitize(group.group_id)}"
			)
			candidate_pairs.append((group, literal))
			for cell in group.cells:
				model.Add(cells[cell] == 1).OnlyEnforceIf(literal)
			bindings.append(
				StableReuseBinding(
					current_instance_id=instance_id,
					prior_group_id=group.group_id,
					prior_member_keys=tuple(member.key for member in group.members),
					cells=group.cells,
					literal=literal,
				)
			)

		if candidate_pairs:
			model.Add(sum(literal for _group, literal in candidate_pairs) <= 1)

		# Reusing only one isolated prior cell would silently change partners between
		# sessions.  Gate every prior cell behind its complete-footprint literal.
		for cell in existing_cells_by_family.get(family, ()):
			variable = cells.get(cell)
			if variable is None:
				continue
			covering = [literal for group, literal in candidate_pairs if cell in group.cells]
			if covering:
				model.Add(variable <= sum(covering))
			else:
				model.Add(variable == 0)
			blocked_partial_variables += 1

	return StableReuseResult(
		bindings=tuple(bindings),
		current_instances=len(instance_cells),
		candidate_bindings=len(bindings),
		blocked_partial_variables=blocked_partial_variables,
	)


def annotate_stable_combined_entries(
	entries: Sequence[object],
	family_by_code: Mapping[str, str],
) -> Tuple[object, ...]:
	"""Add explicit stable co-schedule metadata to extracted lab entries."""

	groups = collect_footprint_groups(entries, family_by_code)
	member_groups = {
		member.key: group
		for group in groups
		if len(group.members) > 1
		for member in group.members
	}
	annotated = []
	for entry in entries:
		member_key = f"{str(_value(entry, 'department', '')).strip()}::{str(_value(entry, 'course_instance_id', '')).strip()}"
		group = member_groups.get(member_key)
		if group is None:
			annotated.append(entry)
			continue
		current_id = str(_value(entry, "course_instance_id", "")).strip()
		partners = [member for member in group.members if member.instance_id != current_id or member.key != member_key]
		partner_teachers = ", ".join(
			member.teacher_name or member.teacher_id for member in partners if member.teacher_name or member.teacher_id
		)
		partner_sections = ", ".join(member.key for member in partners)
		annotated.append(
			replace(
				entry,
				is_co_scheduled=True,
				co_schedule_id=group.group_id,
				co_schedule_group_size=len(group.members),
				co_schedule_partner_teachers=partner_teachers or None,
				co_schedule_info=f"Stable {group.family} footprint with {partner_sections}",
				tags=tuple(sorted(set(_value(entry, "tags", ()) or ()) | {"stable_combined_reuse"})),
			)
		)
	return tuple(annotated)


__all__ = [
	"CombinedCell",
	"CombinedFootprintGroup",
	"FootprintMember",
	"StableReuseBinding",
	"StableReuseResult",
	"annotate_stable_combined_entries",
	"bind_stable_prior_footprints",
	"collect_footprint_groups",
	"normalize_day",
]
